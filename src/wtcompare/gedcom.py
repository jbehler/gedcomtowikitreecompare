"""GEDCOM einlesen (5.5/5.5.1, wie von MyHeritage, Ancestry, Gramps usw. exportiert)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from .dates import PDate, parse_ged_date
from .textutil import given_sim, norm, sim


@dataclass
class GPerson:
    xref: str
    given: str = ""
    surname: str = ""
    married: str = ""
    sex: str = ""
    birth: PDate = field(default_factory=PDate)
    birth_place: str = ""
    birth_is_chr: bool = False
    death: PDate = field(default_factory=PDate)
    death_place: str = ""
    death_is_buri: bool = False
    famc: list = field(default_factory=list)   # [(fam_xref, pedi)]
    fams: list = field(default_factory=list)

    @property
    def name(self) -> str:
        return f"{self.given} {self.surname}".strip()

    def label(self) -> str:
        life = f"{self.birth or '?'} – {self.death or ''}".strip(" –")
        return f"{self.name} ({life})" if life and life != "?" else self.name


@dataclass
class GFamily:
    xref: str
    husb: str | None = None
    wife: str | None = None
    chil: list = field(default_factory=list)
    marr: PDate = field(default_factory=PDate)
    marr_place: str = ""


def _decode(data: bytes) -> str:
    head = data[:4000].decode("latin-1", errors="replace").upper()
    mm = re.search(r"^\s*1\s+CHAR\s+(\S+)", head, re.M)
    declared = (mm.group(1) if mm else "").upper()
    order = ["utf-8-sig", "cp1252"]
    if declared in ("ANSI", "WINDOWS-1252", "CP1252", "IBMPC"):
        order = ["cp1252", "utf-8-sig"]
    elif declared == "UNICODE" and data[:2] in (b"\xff\xfe", b"\xfe\xff"):
        order = ["utf-16"]
    for enc in order:
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    # ANSEL o. Ä.: Umlaute können falsch erscheinen
    return data.decode("utf-8", errors="replace")


class Gedcom:
    def __init__(self, source: Path | str | bytes):
        self.indi: dict[str, GPerson] = {}
        self.fam: dict[str, GFamily] = {}
        data = source if isinstance(source, (bytes, bytearray)) else Path(source).read_bytes()
        self._parse(_decode(bytes(data)))

    @staticmethod
    def _lines(text: str):
        rx = re.compile(r"^\s*(\d+)\s+(@[^@]+@\s+)?(\S+)(?:\s(.*))?$")
        for line in text.splitlines():
            mm = rx.match(line)
            if mm:
                yield int(mm.group(1)), (mm.group(2) or "").strip(), mm.group(3).upper(), (mm.group(4) or "")

    @classmethod
    def tree(cls, text: str) -> list:
        """GEDCOM-Text als Baum: Knoten = [tag, value, xref, children]; liefert den ROOT-Knoten."""
        root = ["ROOT", "", "", []]
        stack = [(-1, root)]
        for lvl, xref, tag, val in cls._lines(text):
            if tag in ("CONC", "CONT"):
                parent = next((n for lv, n in reversed(stack) if lv < lvl), root)
                parent[1] += ("\n" if tag == "CONT" else "") + val
                continue
            node = [tag, val, xref, []]
            while stack and stack[-1][0] >= lvl:
                stack.pop()
            stack[-1][1][3].append(node)
            stack.append((lvl, node))
        return root

    def record(self, xref: str) -> list | None:
        """Kompletter Datensatz (INDI, FAM, SOUR, NOTE, OBJE, REPO …) als Baum – wird bei Bedarf geparst."""
        raw = self.raw.get(xref)
        if raw is None:
            return None
        root = self.tree(raw)
        return root[3][0] if root[3] else None

    def _parse(self, text: str):
        # Datensätze als Rohtext aufheben (spart Speicher); Kerndaten sofort auswerten
        self.raw: dict[str, str] = {}
        text = text.replace("\r\n", "\n").replace("\r", "\n")

        def sub(node, tag):
            return [c for c in node[3] if c[0] == tag]

        def first(node, tag, default=""):
            s = sub(node, tag)
            return s[0][1].strip() if s else default

        for chunk in re.split(r"\n(?=[ \t]*0[ \t])", text):
            root = self.tree(chunk)
            if not root[3]:
                continue
            rec = root[3][0]
            if rec[2]:
                self.raw[rec[2]] = chunk
            tag, _val, xref, _ = rec
            if tag == "INDI":
                p = GPerson(xref)
                names = sub(rec, "NAME")
                if names:
                    n = names[0]
                    mm = re.match(r"^([^/]*)/?([^/]*)/?(.*)$", n[1])
                    p.given = first(n, "GIVN") or (mm.group(1).strip() if mm else n[1])
                    p.surname = first(n, "SURN") or (mm.group(2).strip() if mm else "")
                    p.married = first(n, "_MARNM")
                    for n2 in names[1:]:
                        if first(n2, "TYPE").lower() in ("married", "marriage", "aka") and not p.married:
                            m2 = re.search(r"/([^/]+)/", n2[1])
                            p.married = m2.group(1).strip() if m2 else ""
                p.sex = first(rec, "SEX").upper()[:1]
                for evtag, attr in (("BIRT", "birth"), ("DEAT", "death")):
                    ev = sub(rec, evtag)
                    if ev:
                        setattr(p, attr, parse_ged_date(first(ev[0], "DATE")))
                        setattr(p, attr + "_place", first(ev[0], "PLAC"))
                # Ersatz: Taufe für Geburt, Begräbnis für Tod – auch wenn nur das Datum fehlt
                for alt_tags, attr, flag in ((("CHR", "BAPM"), "birth", "birth_is_chr"),
                                             (("BURI", "CREM"), "death", "death_is_buri")):
                    if not getattr(p, attr).empty:
                        continue
                    for alt in alt_tags:
                        ev = sub(rec, alt)
                        if not ev:
                            continue
                        d = parse_ged_date(first(ev[0], "DATE"))
                        place = first(ev[0], "PLAC")
                        if d.empty and not place:
                            continue
                        if not d.empty:
                            setattr(p, attr, d)
                            setattr(p, flag, True)
                        if not getattr(p, attr + "_place"):
                            setattr(p, attr + "_place", place)
                        break
                for c in sub(rec, "FAMC"):
                    p.famc.append((c[1].strip(), first(c, "PEDI").lower()))
                p.fams = [c[1].strip() for c in sub(rec, "FAMS")]
                self.indi[xref] = p
            elif tag == "FAM":
                f = GFamily(xref, first(rec, "HUSB") or None, first(rec, "WIFE") or None,
                            [c[1].strip() for c in sub(rec, "CHIL")])
                ev = sub(rec, "MARR")
                if ev:
                    f.marr = parse_ged_date(first(ev[0], "DATE"))
                    f.marr_place = first(ev[0], "PLAC")
                self.fam[xref] = f

    # ---------------------------------------------------------------- Verwandtschaft
    def parents(self, x: str) -> tuple[str | None, str | None]:
        """Leibliche Eltern bevorzugen (PEDI birth/leer vor adopted/foster)."""
        famc = sorted(self.indi[x].famc, key=lambda t: 0 if t[1] in ("", "birth") else 1)
        for fx, _ in famc:
            f = self.fam.get(fx)
            if f:
                h = f.husb if f.husb in self.indi else None
                w = f.wife if f.wife in self.indi else None
                return h, w
        return None, None

    def spouses(self, x: str) -> list[tuple[str, GFamily]]:
        out = []
        for fx in self.indi[x].fams:
            f = self.fam.get(fx)
            if not f:
                continue
            other = f.wife if f.husb == x else f.husb
            if other and other in self.indi:
                out.append((other, f))
        return out

    def children(self, x: str) -> list[str]:
        out = []
        for fx in self.indi[x].fams:
            f = self.fam.get(fx)
            if f:
                out += [c for c in f.chil if c in self.indi and c not in out]
        return out

    # ---------------------------------------------------------------- Suche
    def get(self, query: str) -> GPerson | None:
        q = query.strip()
        x = q if q.startswith("@") else f"@{q}@"
        return self.indi.get(x)

    def search(self, query: str, limit: int = 30) -> list[tuple[float, GPerson]]:
        """Suche per XREF (@I123@ / I123) oder 'Vorname Nachname [Geburtsjahr]'.
        Liefert (Score, Person), bestes zuerst. Geburtsjahr erlaubt ±2 Jahre."""
        q = query.strip()
        if not q:
            return []
        p = self.get(q)
        if p:
            return [(1.0, p)]
        year = None
        mm = re.search(r"(\d{4})\s*$", q)
        if mm:
            year = int(mm.group(1))
            q = q[:mm.start()].strip()
        nq = norm(q)
        toks = nq.split()
        res = []
        for p in self.indi.values():
            if year is not None and (p.birth.y is None or abs(p.birth.y - year) > 2):
                continue
            if not toks:
                s = 1.0
            else:
                full = norm(f"{p.given} {p.surname} {p.married}")
                ptoks = full.split()
                # jedes Suchwort muss als Präfix eines Namensteils vorkommen ODER der Name ist sehr ähnlich
                prefix_hits = sum(1 for t in toks if any(pt.startswith(t) for pt in ptoks))
                s = max(sim(q, p.name), given_sim(q, p.name) * 0.95)
                if prefix_hits == len(toks):
                    s = max(s, 0.8 + 0.2 * sim(q, p.name))
                if s < 0.75:
                    continue
            if year is not None and p.birth.y != year:
                s -= 0.05 * abs(p.birth.y - year)
            res.append((s, p))
        res.sort(key=lambda t: (-t[0], t[1].name))
        return res[:limit]
