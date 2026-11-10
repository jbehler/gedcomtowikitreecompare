"""Projekte: GEDCOM-Kopie, WikiTree-Cache, manuelle Zuordnungen und gespeicherte Läufe."""

from __future__ import annotations

import json
import re
import shutil
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable

from .gedcom import Gedcom
from .matching import Comparer, build_result
from .wikitree import WikiTree


def _slug(name: str) -> str:
    s = re.sub(r"[^A-Za-z0-9_-]+", "-", name.strip()).strip("-")
    return s[:40] or "projekt"


def _write_json(path: Path, data):
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(path)


@dataclass
class ProjectSettings:
    name: str
    created: str = ""
    gedcom_name: str = ""          # Originaldateiname der GEDCOM
    gedcom_loaded: str = ""        # Zeitpunkt des letzten Einlesens
    wt_start: str = ""             # WikiTree-ID des Startprofils, z. B. Behler-64
    ged_start: str = ""            # XREF der Startperson in der GEDCOM
    threshold: float = 0.6
    expand_all: bool = False


@dataclass
class Mappings:
    manual: dict[str, str] = field(default_factory=dict)   # WikiTree-Id (str) -> GEDCOM-XREF
    ignored: list[int] = field(default_factory=list)       # Watchlist-Profile ohne Gegenstück


class Project:
    def __init__(self, folder: Path):
        self.dir = folder
        self.settings = ProjectSettings(**json.loads((folder / "project.json").read_text(encoding="utf-8")))
        self._ged: Gedcom | None = None
        mp = folder / "mappings.json"
        self.mappings = Mappings(**json.loads(mp.read_text(encoding="utf-8"))) if mp.exists() else Mappings()

    # ---------------------------------------------------------------- Dateien
    @property
    def gedcom_path(self) -> Path:
        return self.dir / "gedcom.ged"

    @property
    def cache_path(self) -> Path:
        return self.dir / "wikitree_cache.json"

    @property
    def runs_dir(self) -> Path:
        d = self.dir / "runs"
        d.mkdir(exist_ok=True)
        return d

    def save(self):
        _write_json(self.dir / "project.json", asdict(self.settings))
        _write_json(self.dir / "mappings.json", asdict(self.mappings))

    # ---------------------------------------------------------------- GEDCOM
    def set_gedcom(self, data: bytes, original_name: str):
        Gedcom(data)   # erst prüfen, dann übernehmen
        self.gedcom_path.write_bytes(data)
        self.settings.gedcom_name = original_name
        self.settings.gedcom_loaded = datetime.now().isoformat(timespec="seconds")
        self._ged = None
        self.save()

    @property
    def has_gedcom(self) -> bool:
        return self.gedcom_path.exists()

    def gedcom(self) -> Gedcom:
        if self._ged is None:
            if not self.has_gedcom:
                raise RuntimeError("Für dieses Projekt ist noch keine GEDCOM-Datei geladen.")
            self._ged = Gedcom(self.gedcom_path)
        return self._ged

    # ---------------------------------------------------------------- WikiTree
    def wikitree(self, offline=False, log: Callable[[str], None] = print,
                 cancel: threading.Event | None = None, delay: float = 0.5) -> WikiTree:
        return WikiTree(self.cache_path, offline=offline, delay=delay, log=log, cancel=cancel)

    def refresh_wikitree(self, wt: WikiTree, log: Callable[[str], None] = print):
        """Watchlist und Verwandte neu von WikiTree holen (Anmeldung nötig) und Cache ersetzen."""
        if not wt.logged_in:
            raise RuntimeError("Für die Watchlist ist eine Anmeldung bei WikiTree nötig.")
        wt.clear()
        log("Watchlist abrufen …")
        wt.fetch_watchlist()
        log("Verwandte der Watchlist-Profile abrufen …")
        wt.fetch_relatives(wt.watchlist)
        wt.save()
        log(f"WikiTree-Daten gespeichert: {len(wt.watchlist)} Watchlist-Profile, {len(wt.people)} Profile insgesamt")

    # ---------------------------------------------------------------- Zuordnungen
    def set_manual(self, wid: int, xref: str | None):
        k = str(wid)
        if xref:
            # eine GEDCOM-Person nur einem Profil zuordnen
            for other, x in list(self.mappings.manual.items()):
                if x == xref and other != k:
                    del self.mappings.manual[other]
            self.mappings.manual[k] = xref
            if wid in self.mappings.ignored:
                self.mappings.ignored.remove(wid)
        else:
            self.mappings.manual.pop(k, None)
        self.save()

    def set_ignored(self, wid: int, ignored: bool):
        if ignored and wid not in self.mappings.ignored:
            self.mappings.ignored.append(wid)
            self.mappings.manual.pop(str(wid), None)
        elif not ignored and wid in self.mappings.ignored:
            self.mappings.ignored.remove(wid)
        self.save()

    # ---------------------------------------------------------------- Läufe
    def run(self, wt: WikiTree, log: Callable[[str], None] = print) -> dict:
        s = self.settings
        if not s.wt_start or not s.ged_start:
            raise RuntimeError("Startpaar fehlt: bitte Startperson in GEDCOM und WikiTree wählen.")
        ged = self.gedcom()
        if s.ged_start not in ged.indi:
            raise RuntimeError(f"Startperson {s.ged_start} ist nicht (mehr) in der GEDCOM.")
        try:
            if not wt.offline and wt.watchlist:
                missing = [i for i in wt.watchlist if i not in wt.relatives]
                if missing:
                    log("Verwandte der Watchlist-Profile abrufen …")
                    wt.fetch_relatives(missing)
            w0 = wt.resolve(s.wt_start)
            log(f"Startpaar: {ged.indi[s.ged_start].label()}  <->  {wt.wtid(w0)} {wt.label(w0)}")
            cmp = Comparer(ged, wt, s.threshold, log=log)
            cmp.run(s.ged_start, w0, only_watchlist_expand=not s.expand_all,
                    manual={int(k): v for k, v in self.mappings.manual.items()},
                    ignored=set(self.mappings.ignored))
        finally:
            if not wt.offline:
                wt.save()
        now = datetime.now()
        meta = {"title": "WikiTree <-> GEDCOM Vergleich", "project": s.name,
                "created": now.isoformat(timespec="seconds"),
                "info": f"{s.gedcom_name} · Start {s.wt_start} <-> {s.ged_start} · Watchlist {len(wt.watchlist)} Profile · "
                        f"erstellt {now:%d.%m.%Y %H:%M}",
                "wikitree_cache": wt.saved, "threshold": s.threshold, "expand_all": s.expand_all,
                "manual": len(self.mappings.manual)}
        res = build_result(cmp, meta)
        path, i = self.runs_dir / f"{now:%Y%m%d-%H%M%S}.json", 2
        while path.exists():
            path, i = self.runs_dir / f"{now:%Y%m%d-%H%M%S}-{i}.json", i + 1
        _write_json(path, res)
        res["meta"]["file"] = path.name
        return res

    def runs(self) -> list[Path]:
        key = lambda p: (p.name[:15], len(p.name), p.name)   # Zeitstempel, dann Zähler -2, -3 …
        return sorted(self.runs_dir.glob("*.json"), key=key, reverse=True)

    @staticmethod
    def load_run(path: Path) -> dict:
        return json.loads(path.read_text(encoding="utf-8"))

    def delete_run(self, path: Path):
        if path.parent == self.runs_dir:
            path.unlink(missing_ok=True)


class ProjectStore:
    """Verwaltet alle Projekte in einem Datenordner."""

    def __init__(self, root: Path):
        self.root = root / "projects"
        self.root.mkdir(parents=True, exist_ok=True)

    def list(self) -> list[Project]:
        out = []
        for d in sorted(self.root.iterdir()):
            if (d / "project.json").exists():
                try:
                    out.append(Project(d))
                except (ValueError, TypeError, json.JSONDecodeError):
                    continue
        return out

    def create(self, name: str) -> Project:
        name = name.strip() or "Projekt"
        base = _slug(name)
        d, i = self.root / base, 2
        while d.exists():
            d, i = self.root / f"{base}-{i}", i + 1
        d.mkdir(parents=True)
        _write_json(d / "project.json", asdict(ProjectSettings(name, datetime.now().isoformat(timespec="seconds"))))
        return Project(d)

    def delete(self, p: Project):
        if p.dir.parent == self.root:
            shutil.rmtree(p.dir)

    def rename(self, p: Project, name: str):
        p.settings.name = name.strip() or p.settings.name
        p.save()
