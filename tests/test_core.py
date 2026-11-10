from wtcompare.dates import parse_ged_date, parse_wt_date
from wtcompare.gedcom import Gedcom
from wtcompare.matching import cmp_date, cmp_event_alt
from wtcompare.project import ProjectStore
from wtcompare.report import csv_bytes, html_bytes
from wtcompare.rundiff import diff_runs

from conftest import make_cache


def test_parse_dates():
    d = parse_ged_date("12 MAR 1850")
    assert (d.y, d.m, d.d, d.qual) == (1850, 3, 12, "")
    assert parse_ged_date("JAN 1700/01").d is None          # Doppeldatierung ist kein Tag
    b = parse_ged_date("BET 1850 AND 1855")
    assert (b.qual, b.y, b.y2) == ("bet", 1850, 1855)
    assert parse_ged_date("(unbekannt)").empty
    assert parse_ged_date("ABT 1855").qual == "abt"
    assert parse_wt_date("1855-00-00", "guess").qual == "abt"


def test_cmp_date_qualifiers():
    assert cmp_date("x", parse_ged_date("BEF 1850"), parse_wt_date("1849-00-00")).status == "ähnlich"
    assert cmp_date("x", parse_ged_date("BEF 1850"), parse_wt_date("1860-00-00")).status == "abweichend"
    assert cmp_date("x", parse_ged_date("1855"), parse_wt_date("1855-00-00", "guess")).status == "genauer GEDCOM"
    assert cmp_date("x", parse_ged_date("1855"), parse_wt_date("1856-00-00")).status == "abweichend"
    assert cmp_date("x", parse_ged_date("3 MAY 1855"), parse_wt_date("1855-05-00")).status == "genauer GEDCOM"
    f = cmp_event_alt("Geburt", parse_ged_date("20 MAY 1880"), parse_wt_date("1880-05-01"), True, "Taufe.")
    assert f.status == "ähnlich" and "19 Tage" in f.hinweis


def test_gedcom(ged_bytes):
    g = Gedcom(ged_bytes)
    assert len(g.indi) == 6 and len(g.fam) == 2
    h = g.indi["@I3@"]
    assert h.birth_is_chr and h.birth.d == 20 and h.birth_place.startswith("Dortmund")
    assert g.parents("@I3@") == ("@I1@", "@I2@")
    assert g.indi["@I2@"].married == "Behler"
    assert g.fam["@F2@"].chil == ["@I4@", "@I5@"]
    assert g.search("Heinrich Behler 1880")[0][1].xref == "@I3@"
    assert g.search("hein beh")[0][1].xref == "@I3@"
    assert g.search("I4")[0][1].xref == "@I4@"


def _project(tmp_path, ged_bytes):
    store = ProjectStore(tmp_path)
    p = store.create("Test Familie")
    p.set_gedcom(ged_bytes, "familie.ged")
    make_cache(p.cache_path)
    p.settings.wt_start, p.settings.ged_start = "Behler-64", "@I3@"
    p.save()
    return store, p


def test_full_run_and_manual(tmp_path, ged_bytes):
    store, p = _project(tmp_path, ged_bytes)
    wt = p.wikitree(offline=True, log=lambda s: None)
    res = p.run(wt, log=lambda s: None)
    by_w = {x["w"]: x for x in res["persons"]}
    # Mutter hat kein Gender, wird aber über das Feld Mother korrekt als Mutter erkannt
    assert by_w["Schmidt-7"]["g"] == "@I2@"
    assert set(by_w) == {"Behler-1", "Schmidt-7", "Behler-64", "Behler-65"}
    stat = {f["kat"]: f["status"] for f in by_w["Behler-64"]["f"]}
    assert stat["Tod"] == "abweichend"
    assert stat["Geburt"] == "ähnlich"
    assert stat["Geburtsort"] == "ähnlich"
    assert any(m["who"].startswith("Anna Behler") and m["status"] == "fehlt auf WikiTree" for m in res["missing"])
    assert [u["w"] for u in res["unmatched"]] == ["Fremd-1"]
    assert res["unmatched"][0]["cands"][0]["g"] == "@I6@"

    # manuelle Zuordnung -> nächster Lauf hat Fremd-1 zugeordnet
    p.set_manual(5, "@I6@")
    res2 = p.run(p.wikitree(offline=True, log=lambda s: None), log=lambda s: None)
    assert res2["unmatched"] == []
    assert {x["w"]: x for x in res2["persons"]}["Fremd-1"]["how"] == "manuell zugeordnet"

    d = diff_runs(res, res2)
    assert d["summary"].get("neu zugeordnet") == 1
    assert [u["w"] for u in d["unmatched_gone"]] == ["Fremd-1"]
    assert len(p.runs()) == 2

    # ignorieren
    p.set_manual(5, None)
    p.set_ignored(5, True)
    res3 = p.run(p.wikitree(offline=True, log=lambda s: None), log=lambda s: None)
    assert res3["unmatched"] == []

    assert b"Behler-64" in html_bytes(res) and csv_bytes(res).startswith(b"\xef\xbb\xbf")
    assert [x.settings.name for x in store.list()] == ["Test Familie"]


def test_diff_detects_fix(tmp_path, ged_bytes):
    _, p = _project(tmp_path, ged_bytes)
    res = p.run(p.wikitree(offline=True, log=lambda s: None), log=lambda s: None)
    fixed = p.gedcom_path.read_text(encoding="utf-8").replace("2 DATE 2 FEB 1951", "2 DATE 2 FEB 1950")
    p.set_gedcom(fixed.encode("utf-8"), "familie.ged")
    res2 = p.run(p.wikitree(offline=True, log=lambda s: None), log=lambda s: None)
    d = diff_runs(res, res2)
    assert any(c["art"] == "behoben" and c["kat"] == "Tod" and c["w"] == "Behler-64" for c in d["changes"])


def test_cli(tmp_path, ged_bytes):
    from wtcompare.cli import main
    ged = tmp_path / "f.ged"
    ged.write_bytes(ged_bytes)
    cache = tmp_path / "c.json"
    make_cache(cache)
    out = tmp_path / "out" / "vergleich"
    main([str(ged), "--wt-start", "Behler-64", "--ged-start", "Heinrich Behler 1880", "--cache", str(cache),
          "--offline", "--out", str(out)])
    assert out.with_suffix(".html").exists() and out.with_suffix(".csv").exists()
