"""Kommandozeile (wie das ursprüngliche Skript wt_ged_compare.py)."""

from __future__ import annotations

import argparse
import getpass
import os
import sys
from datetime import datetime
from pathlib import Path

from .gedcom import Gedcom
from .matching import Comparer, build_result
from .report import csv_bytes, html_bytes
from .wikitree import WikiTree


def main(argv=None):
    ap = argparse.ArgumentParser(description="Vergleicht WikiTree-Watchlist-Profile mit einer GEDCOM-Datei.")
    ap.add_argument("gedcom", type=Path, help="GEDCOM-Datei (z. B. MyHeritage-Export)")
    ap.add_argument("--wt-start", required=True, help="WikiTree-ID des Startprofils, z. B. Behler-64")
    ap.add_argument("--ged-start", required=True,
                    help="Startperson in der GEDCOM: XREF (z. B. @I500001@) oder 'Vorname Nachname Geburtsjahr'")
    ap.add_argument("--email", default=os.environ.get("WT_EMAIL"), help="WikiTree-Login (oder Umgebungsvariable WT_EMAIL)")
    ap.add_argument("--cache", type=Path, default=Path("wikitree_cache.json"), help="Cache-Datei für WikiTree-Daten")
    ap.add_argument("--offline", action="store_true", help="Nur Cache verwenden, nichts von WikiTree abrufen")
    ap.add_argument("--refresh", action="store_true", help="Cache verwerfen und alles neu abrufen")
    ap.add_argument("--out", type=Path, default=Path("vergleich"), help="Ausgabe-Präfix (ergibt .html und .csv)")
    ap.add_argument("--threshold", type=float, default=0.6, help="Mindest-Ähnlichkeit für Zuordnung (0–1, Standard 0.6)")
    ap.add_argument("--expand-all", action="store_true",
                    help="Auch über Profile außerhalb der Watchlist weiterlaufen (mehr API-Abrufe)")
    ap.add_argument("--delay", type=float, default=0.5, help="Pause zwischen API-Abrufen in Sekunden")
    a = ap.parse_args(argv)

    print(f"GEDCOM lesen: {a.gedcom}")
    ged = Gedcom(a.gedcom)
    print(f"  {len(ged.indi)} Personen, {len(ged.fam)} Familien")
    hits = ged.search(a.ged_start)
    if not hits:
        sys.exit(f"Startperson '{a.ged_start}' nicht in der GEDCOM gefunden.")
    exact = ged.get(a.ged_start)
    if not exact and len(hits) > 1:
        print("Mehrere Treffer für die Startperson – bitte XREF angeben:")
        for _, p in hits[:10]:
            print(f"  {p.xref}  {p.label()}")
        sys.exit(1)
    g0 = (exact or hits[0][1]).xref

    if a.refresh and a.cache.exists():
        a.cache.unlink()
    wt = WikiTree(a.cache, a.offline, a.delay)
    try:
        if not a.offline and not wt.watchlist:
            email = a.email or input("WikiTree E-Mail: ")
            pw = os.environ.get("WT_PASSWORD") or getpass.getpass("WikiTree Passwort: ")
            print(f"Angemeldet als {wt.login(email, pw)}")
            print("Watchlist abrufen …")
            wt.fetch_watchlist()
            print("Verwandte der Watchlist-Profile abrufen …")
            wt.fetch_relatives(wt.watchlist)
            wt.save()
        w0 = wt.resolve(a.wt_start)
        print(f"Startpaar: {ged.indi[g0].label()}  <->  {wt.wtid(w0)} {wt.label(w0)}")
        cmp = Comparer(ged, wt, a.threshold, log=print)
        cmp.run(g0, w0, only_watchlist_expand=not a.expand_all)
    finally:
        if not a.offline:
            wt.save()

    res = build_result(cmp, {"title": "WikiTree <-> GEDCOM Vergleich",
                             "info": f"{a.gedcom.name} · Start {a.wt_start} <-> {g0} · Watchlist {len(wt.watchlist)} Profile · "
                                     f"erstellt {datetime.now():%d.%m.%Y %H:%M}"})
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.with_suffix(".html").write_bytes(html_bytes(res))
    a.out.with_suffix(".csv").write_bytes(csv_bytes(res))
    print(f"\nZugeordnet: {len(res['persons'])} Personen ({sum(1 for p in res['persons'] if p['watch'])} davon auf der Watchlist), "
          f"{len(res['missing'])} fehlende Personen, {len(res['unmatched'])} Watchlist-Profile ohne Zuordnung")
    print(f"Bericht: {a.out.with_suffix('.html')}  |  {a.out.with_suffix('.csv')}")


if __name__ == "__main__":
    main()
