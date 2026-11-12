import hashlib
import itertools

import pytest

from wtcompare.gdrive import RemoteFile
from wtcompare.project import ProjectStore
from wtcompare.sync import Conflict, Syncer, last_synced

from conftest import make_cache


class FakeDrive:
    """Drive-Ersatz im Speicher (gleiche Schnittstelle wie gdrive.Drive)."""

    def __init__(self):
        self.files: dict[str, dict] = {}
        self._ids = itertools.count(1)
        self._t = itertools.count(1)

    def _rf(self, fid):
        f = self.files[fid]
        return RemoteFile(fid, f["name"], f"2026-11-12T10:00:{next(self._t):02d}Z",
                          hashlib.md5(f["data"]).hexdigest(), len(f["data"]), dict(f["props"]))

    def list(self):
        return [self._rf(i) for i in self.files]

    def upload(self, name, data, props, file_id=None):
        fid = file_id or f"f{next(self._ids)}"
        self.files[fid] = {"name": name, "data": data, "props": props}
        return self._rf(fid)

    def download(self, fid):
        return self.files[fid]["data"]

    def delete(self, fid):
        del self.files[fid]


@pytest.fixture
def setup(tmp_path, ged_bytes):
    drive = FakeDrive()
    a = ProjectStore(tmp_path / "pc")
    b = ProjectStore(tmp_path / "handy")
    p = a.create("Familie")
    p.set_gedcom(ged_bytes, "familie.ged")
    make_cache(p.cache_path)
    p.settings.wt_start, p.settings.ged_start = "Behler-64", "@I3@"
    p.save()
    return drive, a, b, p


def test_roundtrip_between_devices(setup):
    drive, a, b, p = setup
    sa, sb = Syncer(drive, a, "PC"), Syncer(drive, b, "Handy")
    assert sa.sync(p).action == "hochgeladen"
    assert sa.sync(p).action == "aktuell"
    assert last_synced(p)

    # Handy holt das Projekt
    remote = sb.remotes()[p.settings.uid]
    assert remote.props["name"] == "Familie"
    q = sb.import_remote(remote)
    assert q.settings.uid == p.settings.uid and q.has_gedcom and q.cache_path.exists()
    assert sb.sync(q).action == "aktuell"

    # Handy ändert eine Zuordnung und einen Lauf -> hochladen; PC holt es
    q.set_manual(5, "@I6@")
    q.run(q.wikitree(offline=True, log=lambda s: None), log=lambda s: None)
    assert sb.sync(q).action == "hochgeladen"
    r = sa.sync(p)
    assert r.action == "heruntergeladen"
    assert r.project.mappings.manual == {"5": "@I6@"} and len(r.project.runs()) == 1


def test_conflict_and_resolution(setup):
    drive, a, b, p = setup
    sa, sb = Syncer(drive, a, "PC"), Syncer(drive, b, "Handy")
    sa.sync(p)
    q = sb.import_remote(sb.remotes()[p.settings.uid])
    p.set_manual(5, "@I6@")
    q.set_ignored(5, True)
    assert sb.sync(q).action == "hochgeladen"
    with pytest.raises(Conflict):
        sa.sync(p)
    r = sa.sync(p, prefer="remote")
    assert r.action == "heruntergeladen" and r.project.mappings.ignored == [5] and r.project.mappings.manual == {}
    assert sa.sync(r.project).action == "aktuell"


def test_first_sync_with_existing_remote_is_conflict(setup, ged_bytes):
    drive, a, b, p = setup
    Syncer(drive, a).sync(p)
    # gleiches Projekt (gleiche uid) liegt auf einem zweiten Gerät ohne Abgleich-Stand
    q = b.create("Kopie")
    q.settings.uid = p.settings.uid
    q.save()
    with pytest.raises(Conflict):
        Syncer(drive, b).sync(q)


def test_unpack_rejects_bad_paths(tmp_path):
    import io
    import zipfile
    from wtcompare.sync import unpack
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("project.json", "{}")
        z.writestr("../boese.txt", "x")
    with pytest.raises(RuntimeError, match="Ungültiger Pfad"):
        unpack(buf.getvalue(), tmp_path / "p")
