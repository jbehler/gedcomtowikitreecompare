"""Projekte über Google Drive (versteckter App-Ordner) zwischen Geräten abgleichen.

Je Projekt liegt in Drive eine ZIP-Datei "projekt-<uid>.zip" mit allen Projektdateien
(GEDCOM-Kopie, WikiTree-Cache, Zuordnungen, Einstellungen, Läufe). Pro Gerät merkt sich
sync.json im Projektordner den Stand des letzten Abgleichs. Damit wird entschieden:

    nur lokal geändert      -> hochladen
    nur in Drive geändert   -> herunterladen
    beides geändert         -> Konflikt (Nutzer entscheidet)
"""

from __future__ import annotations

import hashlib
import io
import json
import shutil
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .gdrive import Drive, RemoteFile
from .project import Project, ProjectStore

SYNC_FILE = "sync.json"
SKIP = {SYNC_FILE}


class Conflict(Exception):
    def __init__(self, project: Project, remote: RemoteFile):
        super().__init__(f"„{project.settings.name}“ wurde auf diesem Gerät und in Google Drive geändert.")
        self.project, self.remote = project, remote


@dataclass
class SyncResult:
    action: str          # "hochgeladen" | "heruntergeladen" | "aktuell"
    project: Project


def _files(folder: Path):
    for f in sorted(folder.rglob("*")):
        if f.is_file() and f.name not in SKIP and not f.name.endswith(".tmp"):
            yield f


def content_hash(folder: Path) -> str:
    h = hashlib.sha256()
    for f in _files(folder):
        h.update(f.relative_to(folder).as_posix().encode() + b"\0")
        h.update(f.read_bytes())
        h.update(b"\0")
    return h.hexdigest()


def pack(folder: Path) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for f in _files(folder):
            z.write(f, f.relative_to(folder).as_posix())
    return buf.getvalue()


def unpack(data: bytes, folder: Path):
    """Projektordner durch den ZIP-Inhalt ersetzen (sync.json bleibt erhalten)."""
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        names = z.namelist()
        if "project.json" not in names:
            raise RuntimeError("Die Datei aus Google Drive ist kein Projekt.")
        for n in names:   # Schutz vor Pfaden außerhalb des Ordners
            if n.startswith("/") or ".." in Path(n).parts:
                raise RuntimeError(f"Ungültiger Pfad im Projekt-Archiv: {n}")
        tmp = folder.with_name(folder.name + ".sync-tmp")
        if tmp.exists():
            shutil.rmtree(tmp)
        tmp.mkdir(parents=True)
        z.extractall(tmp)
    folder.mkdir(parents=True, exist_ok=True)
    for f in list(_files(folder)):
        f.unlink()
    for d in sorted((p for p in folder.rglob("*") if p.is_dir()), reverse=True):
        if not any(d.iterdir()):
            d.rmdir()
    for f in tmp.rglob("*"):
        if f.is_file():
            dst = folder / f.relative_to(tmp)
            dst.parent.mkdir(parents=True, exist_ok=True)
            f.replace(dst)
    shutil.rmtree(tmp)


def _state(p: Project) -> dict:
    f = p.dir / SYNC_FILE
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save_state(p: Project, remote: RemoteFile):
    (p.dir / SYNC_FILE).write_text(json.dumps({
        "file_id": remote.id, "remote_md5": remote.md5, "local_hash": content_hash(p.dir),
        "synced": datetime.now().isoformat(timespec="seconds")}), encoding="utf-8")


def last_synced(p: Project) -> str:
    return _state(p).get("synced", "")


def remote_name(uid: str) -> str:
    return f"projekt-{uid}.zip"


class Syncer:
    def __init__(self, drive: Drive, store: ProjectStore, device: str = ""):
        self.drive, self.store, self.device = drive, store, device

    def remotes(self) -> dict[str, RemoteFile]:
        """uid -> Datei in Drive."""
        out = {}
        for f in self.drive.list():
            uid = f.props.get("uid") or (f.name[8:-4] if f.name.startswith("projekt-") and f.name.endswith(".zip") else "")
            if uid and (uid not in out or f.modified > out[uid].modified):
                out[uid] = f
        return out

    def upload(self, p: Project, remote: RemoteFile | None = None) -> RemoteFile:
        props = {"uid": p.settings.uid, "name": p.settings.name[:100], "device": self.device[:100],
                 "updated": datetime.now().isoformat(timespec="seconds")}
        r = self.drive.upload(remote_name(p.settings.uid), pack(p.dir), props, remote.id if remote else None)
        _save_state(p, r)
        return r

    def download(self, p: Project, remote: RemoteFile) -> Project:
        unpack(self.drive.download(remote.id), p.dir)
        fresh = Project(p.dir)
        _save_state(fresh, remote)
        return fresh

    def sync(self, p: Project, remote: RemoteFile | None = None, prefer: str = "") -> SyncResult:
        """prefer: "" (automatisch), "local" (dieses Gerät gewinnt), "remote" (Drive gewinnt)."""
        if remote is None:
            remote = self.remotes().get(p.settings.uid)
        st = _state(p)
        if remote is None:
            self.upload(p)
            return SyncResult("hochgeladen", p)
        local_changed = content_hash(p.dir) != st.get("local_hash")
        remote_changed = remote.md5 != st.get("remote_md5")
        if prefer == "local":
            self.upload(p, remote)
            return SyncResult("hochgeladen", p)
        if prefer == "remote":
            return SyncResult("heruntergeladen", self.download(p, remote))
        if not st:   # erster Abgleich auf diesem Gerät, aber Drive hat schon einen Stand
            raise Conflict(p, remote)
        if local_changed and remote_changed:
            raise Conflict(p, remote)
        if remote_changed:
            return SyncResult("heruntergeladen", self.download(p, remote))
        if local_changed:
            self.upload(p, remote)
            return SyncResult("hochgeladen", p)
        return SyncResult("aktuell", p)

    def import_remote(self, remote: RemoteFile) -> Project:
        """Projekt aus Drive, das es auf diesem Gerät noch nicht gibt, anlegen."""
        d = self.store.new_dir(remote.props.get("name") or "Projekt")
        unpack(self.drive.download(remote.id), d)
        p = Project(d)
        _save_state(p, remote)
        return p

    def delete_remote(self, p: Project):
        r = self.remotes().get(p.settings.uid)
        if r:
            self.drive.delete(r.id)
