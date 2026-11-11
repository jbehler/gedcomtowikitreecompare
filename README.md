# WikiTree ↔ GEDCOM Vergleich

Vergleicht die Profile deiner WikiTree-Watchlist mit einer GEDCOM-Datei (z. B. MyHeritage-Export).
Als **App für Windows und Android** (Flet 1.1.2) und weiterhin als **Kommandozeilen-Skript**.

Benutzt nur die offizielle, lesende WikiTree-API. Auf WikiTree wird nichts verändert.

## Was die App kann

- **Projekte:** mehrere getrennte Projekte, jeweils mit eigener GEDCOM-Kopie, WikiTree-Cache, Zuordnungen und Läufen.
- **Startpaar per Suche:**
  - GEDCOM nach Name/Jahr/XREF durchsuchen.
  - WikiTree in den geladenen Daten durchsuchen, online über die WikiTree-Suche (`searchPerson`) oder per WikiTree-ID.
- **Vergleich:** Namen, Geburt, Tod, Ehe (Datum/Ort), Eltern/Partner/Kinder und fehlende Personen. Läuft im Hintergrund und lässt sich abbrechen.
- **Ergebnis:** filterbar (nur Unterschiede, „ähnlich“ ausblenden, nur Watchlist, Suche); Export als HTML-Bericht und CSV.
- **Fehlende Personen mit allen Profildaten**, als Vorlage zum schnellen Anlegen:
  - „fehlt auf WikiTree“: alles aus der GEDCOM, also Namen (auch Spitz-/Ehenamen), Geschlecht, alle Ereignisse und Fakten (Geburt, Taufe, Tod, Begräbnis, Beruf, Wohnort …), Eltern, Partner mit Heirat, Kinder (jeweils mit WikiTree-ID, falls schon zugeordnet), Notizen, Quellen mit Fundstelle und Archiv sowie Medien.
  - „fehlt in GEDCOM“: alles aus dem WikiTree-Cache (Namen, Lebensdaten, Orte, Datenstatus, Familie). Biografie und Quellen stehen auf dem WikiTree-Profil.
  - Kopieren-Knopf pro Angabe (Daten als JJJJ-MM-TT) und „Alles kopieren“.
  - Knopf zum Öffnen des Verwandten auf WikiTree, an den die Person angehängt wird.
- **Manuelle Zuordnung:**
  - Watchlist-Profile ohne Zuordnung per Klick einer GEDCOM-Person zuweisen oder als „kein Gegenstück“ markieren.
  - Die Zuordnung wird gespeichert, beim nächsten Lauf als fester Ankerpunkt benutzt und der Abgleich läuft von dort weiter.
- **Verlauf:** jeder Lauf wird gespeichert. Zwei Läufe lassen sich vergleichen: neue und behobene Abweichungen, neu zugeordnete Personen, Personen, die nicht mehr oder neu fehlen.

## App am PC starten (Entwicklung)

```bash
pip install "flet[all]==1.1.2" requests rapidfuzz
```

```bash
flet run
```

(im Projektordner; Einstiegspunkt ist `src/main.py`)

## App bauen

Voraussetzungen laut Flet-Doku: Flutter wird beim ersten Build automatisch geladen.

**Windows** (muss auf Windows gebaut werden, Visual Studio 2022/2026 mit „Desktop development with C++“):

```bash
flet build windows
```

**Android-APK** (geht auf Windows, macOS, Linux; JDK 17 und Android SDK werden bei Bedarf automatisch installiert):

```bash
flet build apk
```

Die Ergebnisse liegen in `build/windows` bzw. `build/apk`. Die APK lässt sich direkt aufs Handy kopieren und installieren
(„Installation aus unbekannten Quellen“ erlauben). Für eine kleinere APK: `flet build apk --split-per-abi`.

## Android-App über GitHub (ohne eigenes Android SDK)

GitHub baut die APK automatisch, sobald ein Versions-Tag wie `v1.0.0` gepusht wird, und hängt sie an ein
Release. Für öffentliche Repos ist das kostenlos.

**Einmalig: Signierschlüssel anlegen.** Jede Version muss mit demselben Schlüssel signiert sein, sonst lässt
sie sich nicht über die alte installieren.

```powershell
py -m pip install cryptography
```
```powershell
py tools\keystore_erzeugen.py
```

Das Skript legt `upload-keystore.jks` und `upload-keystore-base64.txt` in deinem Benutzerordner an (nicht im
Repo) und zeigt ein Passwort an. Dann auf GitHub im Repo **Settings → Secrets and variables → Actions →
New repository secret** zwei Secrets anlegen:

| Name | Wert |
|---|---|
| `ANDROID_KEYSTORE_BASE64` | kompletter Inhalt von `upload-keystore-base64.txt` |
| `ANDROID_KEYSTORE_PASSWORD` | das angezeigte Passwort |

`upload-keystore.jks` und das Passwort sicher aufbewahren (Backup). Die `…-base64.txt` danach löschen.

**Neue Version veröffentlichen:** In GitHub Desktop **History** → Rechtsklick auf den neuesten Commit →
**Create Tag…** → z. B. `v1.0.0` → **Push origin**. Unter **Actions** läuft dann „Android-APK“ (dauert
einige Minuten), danach liegt die APK unter **Releases**.

**Auf dem Handy:** Release-Seite öffnen, `WikiTree-GEDCOM-Vergleich-….apk` herunterladen, antippen und
installieren. Android fragt einmalig, ob der Browser/Dateimanager Apps installieren darf. Bei späteren
Versionen genauso, die Daten bleiben erhalten.

## Kommandozeile (wie bisher)

```bash
pip install requests rapidfuzz
```

```bash
python wt_ged_compare.py MeinExport.ged --wt-start Behler-64 --ged-start "Vorname Behler 1890"
```

- `--wt-start`: WikiTree-ID des Startprofils
- `--ged-start`: dieselbe Person in der GEDCOM, als XREF (`@I500123@`) oder als „Vorname Nachname Geburtsjahr“.
- E-Mail und Passwort werden abgefragt oder aus `WT_EMAIL` und `WT_PASSWORD` gelesen. Gespeichert wird beides nicht.
- `--offline` (nur Cache), `--refresh` (Cache neu), `--expand-all`, `--threshold 0.7`

Ergebnis: `vergleich.html` und `vergleich.csv`; WikiTree-Daten in `wikitree_cache.json`.

## Statuswerte

gleich · ähnlich (Schreibvariante, gleicher Ort mit anderen Verwaltungsebenen, verträgliche ca./vor/nach-Angaben,
Taufe/Begräbnis 1–60 Tage nach dem WikiTree-Datum) · genauer GEDCOM / genauer WikiTree · abweichend ·
nur GEDCOM / nur WikiTree · fehlt auf WikiTree / fehlt in GEDCOM

## Änderungen gegenüber dem ursprünglichen Skript

- Eltern ohne Geschlechtsangabe werden über die WikiTree-Felder `Father`/`Mother` zugeordnet statt immer als „Mutter“; ist die Rolle unklar, wird nicht geraten.
- „vor“/„nach“/„zwischen“-Daten werden als Zeitraum verglichen (z. B. „vor 1850“ vs. 1849 = ähnlich statt abweichend); exaktes Datum vs. „ca.“ im selben Jahr = „genauer …“.
- GEDCOM:
  - Taufdatum wird auch genutzt, wenn bei der Geburt nur der Ort steht (ebenso Begräbnis/Einäscherung beim Tod).
  - Doppeldatierungen (`1700/01`), Datumsphrasen und Kalender-Angaben werden nicht mehr als Tag fehlgedeutet.
  - `CONC`/`CONT`-Zeilen werden immer der richtigen Zeile angehängt.
  - Leibliche Eltern (`PEDI`) werden vor Adoptiv-/Pflegeeltern bevorzugt.
  - Die Zeichenkodierung (`CHAR`) aus dem Kopf der Datei wird beachtet.
- Die Kandidatensuche für Profile ohne Zuordnung filtert vorab über das Geburtsjahr (deutlich schneller bei großen GEDCOMs).
- `getWatchlist`: Die API-Doku nennt als Ergebnisfeld sowohl `watchlist` als auch `items`; beides wird gelesen.

## Tests

```bash
pip install pytest
```

```bash
pytest
```
