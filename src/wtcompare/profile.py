"""Alle verfügbaren Angaben einer Person, aufbereitet als Vorlage zum Anlegen des Profils.

Format (JSON-fähig, wird mit dem Lauf gespeichert):
    {"sections": [{"title": "Person", "rows": [{"label": ..., "value": ..., "copy": ...}, ...]}, ...]}
"value" ist die Anzeige, "copy" der Text für die Zwischenablage (fehlt er, wird "value" kopiert).
"""

from __future__ import annotations

from typing import Callable

from .dates import PDate, parse_ged_date, parse_wt_date
from .gedcom import Gedcom
from .wikitree import WikiTree

TAGS = {
    "BIRT": "Geburt", "CHR": "Taufe", "BAPM": "Taufe", "DEAT": "Tod", "BURI": "Begräbnis", "CREM": "Einäscherung",
    "ADOP": "Adoption", "BARM": "Bar Mizwa", "BASM": "Bat Mizwa", "BLES": "Segnung", "CHRA": "Erwachsenentaufe",
    "CONF": "Konfirmation", "FCOM": "Erstkommunion", "ORDN": "Ordination", "NATU": "Einbürgerung",
    "EMIG": "Auswanderung", "IMMI": "Einwanderung", "CENS": "Volkszählung", "PROB": "Testamentseröffnung",
    "WILL": "Testament", "GRAD": "Abschluss", "RETI": "Ruhestand", "EVEN": "Ereignis", "OCCU": "Beruf",
    "RESI": "Wohnort", "EDUC": "Ausbildung", "RELI": "Religion", "TITL": "Titel", "NATI": "Nationalität",
    "CAST": "Stand", "DSCR": "Beschreibung", "PROP": "Besitz", "SSN": "Sozialversicherungsnr.", "IDNO": "Kennnummer",
    "NCHI": "Anzahl Kinder", "NMR": "Anzahl Ehen", "FACT": "Fakt", "_MILT": "Militärdienst", "_MILI": "Militärdienst",
    "_DEG": "Abschluss", "_ELEC": "Wahl", "_EMPLOY": "Anstellung", "_MDCL": "Medizinisches", "_HEIG": "Größe",
    "_WEIG": "Gewicht", "MARR": "Heirat", "DIV": "Scheidung", "ENGA": "Verlobung", "MARB": "Aufgebot",
    "MARC": "Ehevertrag", "MARL": "Heiratserlaubnis", "MARS": "Ehevereinbarung", "ANUL": "Annullierung",
    "DIVF": "Scheidungsantrag",
}
# Unterstrukturen, die keine eigenen Angaben für ein Profil sind
SKIP = {"NAME", "SEX", "FAMC", "FAMS", "NOTE", "SOUR", "OBJE", "CHAN", "RIN", "RFN", "AFN", "REFN", "_UID", "_UPD",
        "SUBM", "ANCI", "DESI", "ASSO", "ALIA", "_PHOTO", "_PRIM", "_CUTOUT", "_PARENTRIN", "_PPEXCLUDE",
        "HUSB", "WIFE", "CHIL", "_FREL", "_MREL"}


def _sub(node, tag):
    return [c for c in node[3] if c[0] == tag]


def _first(node, tag, default=""):
    s = _sub(node, tag)
    return s[0][1].strip() if s else default


def _iso(d: PDate) -> str:
    if d.empty:
        return ""
    return f"{d.y:04d}" + (f"-{d.m:02d}" if d.m else "") + (f"-{d.d:02d}" if d.d else "")


def _row(label: str, value: str, copy: str | None = None) -> dict | None:
    value = (value or "").strip()
    if not value:
        return None
    r = {"label": label, "value": value}
    if copy and copy != value:
        r["copy"] = copy
    return r


def _date_row(label: str, raw: str) -> dict | None:
    d = parse_ged_date(raw)
    if d.empty:
        return _row(label, raw)
    shown = str(d)
    if raw and raw.upper() != shown.upper():
        shown += f"  (GEDCOM: {raw})"
    return _row(label, shown, _iso(d))


class _Sections:
    def __init__(self):
        self.list: list[dict] = []

    def add(self, title: str, rows: list):
        rows = [r for r in rows if r]
        if rows:
            self.list.append({"title": title, "rows": rows})


# ================================================================== GEDCOM
def ged_details(ged: Gedcom, xref: str, wt_of: Callable[[str], str | None] = lambda x: None) -> dict:
    """Alles, was die GEDCOM zu einer Person hergibt. wt_of(xref) liefert die WikiTree-ID einer
    bereits zugeordneten Person (für Verwandte), sonst None."""
    rec = ged.record(xref)
    p = ged.indi.get(xref)
    if rec is None or p is None:
        return {"sections": []}
    S = _Sections()
    sources: list[tuple[str, list]] = []   # (Bezug, SOUR-Knoten)
    notes: list[tuple[str, str]] = []

    def collect(node, ref):
        for s in _sub(node, "SOUR"):
            sources.append((ref, s))
        for n in _sub(node, "NOTE"):
            notes.append((ref, _note_text(ged, n)))

    # --- Person
    rows = []
    for i, n in enumerate(_sub(rec, "NAME")):
        typ = _first(n, "TYPE").lower()
        given = _first(n, "GIVN") or n[1].split("/")[0].strip()
        surn = _first(n, "SURN") or (n[1].split("/")[1].strip() if n[1].count("/") >= 2 else "")
        if i == 0:
            rows += [_row("Vorname(n)", given), _row("Nachname bei Geburt", surn)]
        else:
            label = {"married": "Ehename", "aka": "Auch bekannt als", "birth": "Geburtsname",
                     "nickname": "Spitzname"}.get(typ, f"Weiterer Name{f' ({typ})' if typ else ''}")
            rows.append(_row(label, " ".join(x for x in (given, surn) if x)))
        rows += [_row("Spitzname", _first(n, "NICK")), _row("Namenspräfix", _first(n, "NPFX")),
                 _row("Namenssuffix", _first(n, "NSFX")), _row("Ehename", _first(n, "_MARNM"))]
        collect(n, "Name")
    rows.append(_row("Geschlecht", {"M": "männlich", "F": "weiblich"}.get(p.sex, p.sex)))
    rows.append(_row("GEDCOM-ID", xref))
    S.add("Person", rows)

    # --- Ereignisse und Fakten
    rows = []
    for ev in rec[3]:
        tag = ev[0]
        if tag in SKIP:
            continue
        label = TAGS.get(tag, tag.lstrip("_").capitalize())
        if tag in ("EVEN", "FACT") and _first(ev, "TYPE"):
            label = _first(ev, "TYPE")
        rows += _event_rows(label, ev)
        collect(ev, label)
    S.add("Ereignisse und Fakten", rows)

    # --- Familie
    def who(x):
        if not x or x not in ged.indi:
            return None
        w = wt_of(x)
        return ged.indi[x].label() + (f"  –  WikiTree {w}" if w else "  –  noch nicht auf WikiTree"), ged.indi[x].label()

    rows = []
    for fx, pedi in p.famc:
        f = ged.fam.get(fx)
        if not f:
            continue
        extra = f" ({pedi})" if pedi and pedi != "birth" else ""
        for role, x in (("Vater", f.husb), ("Mutter", f.wife)):
            v = who(x)
            if v:
                rows.append(_row(role + extra, v[0], v[1]))
    for fx in p.fams:
        f = ged.fam.get(fx)
        if not f:
            continue
        other = f.wife if f.husb == xref else f.husb
        v = who(other)
        frec = ged.record(fx)
        if v:
            rows.append(_row("Partner", v[0], v[1]))
        if frec is not None:
            for ev in frec[3]:
                if ev[0] in SKIP or ev[0] not in TAGS:
                    continue
                label = TAGS[ev[0]] + (f" mit {ged.indi[other].name}" if other in ged.indi else "")
                rows += _event_rows(label, ev)
                collect(ev, label)
            collect(frec, "Familie" + (f" mit {ged.indi[other].name}" if other in ged.indi else ""))
        for c in f.chil:
            v = who(c)
            if v:
                rows.append(_row("Kind", v[0], v[1]))
    S.add("Familie", rows)

    # --- Notizen
    collect(rec, "Person")
    S.add("Notizen", [_row(ref, txt) for ref, txt in notes])

    # --- Quellen
    rows = []
    for ref, s in sources:
        rows += _source_rows(ged, ref, s)
    S.add("Quellen", rows)

    # --- Medien
    rows = []
    for o in _sub(rec, "OBJE"):
        node = ged.record(o[1].strip()) if o[1].strip().startswith("@") else o
        if node is None:
            continue
        files = _sub(node, "FILE")
        title = _first(node, "TITL") or (_first(files[0], "TITL") if files else "")
        for f in files or [None]:
            rows.append(_row(title or "Medium", (f[1].strip() if f else "") or title))
    S.add("Medien", rows)
    return {"sections": S.list}


def _event_rows(label: str, ev) -> list:
    parts = []
    if ev[1].strip() and ev[1].strip().upper() != "Y":
        parts.append(_row(label, ev[1].strip()))
    date = _first(ev, "DATE")
    place = _first(ev, "PLAC")
    addr = _first(ev, "ADDR")
    if date:
        parts.append(_date_row(f"{label}: Datum", date))
    if place:
        parts.append(_row(f"{label}: Ort", place))
    if addr:
        parts.append(_row(f"{label}: Adresse", addr.replace("\n", ", ")))
    for t, lab in (("AGE", "Alter"), ("CAUS", "Ursache"), ("AGNC", "Stelle")):
        parts.append(_row(f"{label}: {lab}", _first(ev, t)))
    if ev[0] in ("EVEN", "FACT") and not any(parts):
        parts.append(_row(label, "ja"))
    if not any(parts) and ev[1].strip().upper() == "Y":
        parts.append(_row(label, "ja (ohne Datum/Ort)"))
    return parts


def _note_text(ged: Gedcom, n) -> str:
    v = n[1].strip()
    if v.startswith("@") and v.endswith("@"):
        rec = ged.record(v)
        return rec[1].strip() if rec is not None else ""
    return v


def _source_rows(ged: Gedcom, ref: str, s) -> list:
    v = s[1].strip()
    srec = ged.record(v) if v.startswith("@") else None
    title = ""
    rows = []
    if srec is not None:
        title = _first(srec, "TITL") or _first(srec, "ABBR")
        info = [_first(srec, "AUTH"), _first(srec, "PUBL")]
        repo = _sub(srec, "REPO")
        if repo and repo[0][1].strip().startswith("@"):
            rrec = ged.record(repo[0][1].strip())
            if rrec is not None:
                info.append(_first(rrec, "NAME"))
        for t in ("_LINK", "WWW", "_URL"):
            info.append(_first(srec, t))
        txt = _first(srec, "TEXT")
        if txt:
            info.append(txt)
        detail = " · ".join(x for x in info if x)
    else:
        title, detail = v, ""
    page = _first(s, "PAGE")
    data = _sub(s, "DATA")
    cite = []
    if page:
        cite.append(f"Fundstelle: {page}")
    if data:
        d, t = _first(data[0], "DATE"), _first(data[0], "TEXT")
        if d:
            cite.append(f"Datum: {d}")
        if t:
            cite.append(t)
    for t in ("_LINK", "WWW", "_URL"):
        if _first(s, t):
            cite.append(_first(s, t))
    for n in _sub(s, "NOTE"):
        cite.append(_note_text(ged, n))
    text = " · ".join(x for x in [title, detail, *cite] if x)
    rows.append(_row(f"Quelle ({ref})", text))
    return rows


# ================================================================== WikiTree
def wt_details(wt: WikiTree, i: int, ged_of: Callable[[int], str | None] = lambda w: None) -> dict:
    """Alles, was im WikiTree-Cache zu einem Profil steht. ged_of(id) liefert die GEDCOM-XREF einer
    bereits zugeordneten Person, sonst None."""
    p = wt.people.get(i, {})
    S = _Sections()
    ds = p.get("DataStatus") if isinstance(p.get("DataStatus"), dict) else {}

    def wdate(label, key):
        d = wt.date(i, key)
        if d.empty:
            return None
        return _row(label, str(d), _iso(d))

    nick = p.get("Nicknames")
    S.add("Person", [
        _row("WikiTree-ID", p.get("Name", "")),
        _row("Vorname", p.get("FirstName", "")), _row("Weitere Vornamen", p.get("MiddleName", "")),
        _row("Rufname", p.get("RealName", "") if p.get("RealName") != p.get("FirstName") else ""),
        _row("Spitzname", ", ".join(nick) if isinstance(nick, list) else (nick or "")),
        _row("Präfix", p.get("Prefix", "")), _row("Suffix", p.get("Suffix", "")),
        _row("Nachname bei Geburt", p.get("LastNameAtBirth", "")),
        _row("Aktueller Nachname", p.get("LastNameCurrent", "")
             if p.get("LastNameCurrent") != p.get("LastNameAtBirth") else ""),
        _row("Weitere Nachnamen", p.get("LastNameOther", "")),
        _row("Geschlecht", {"Male": "männlich", "Female": "weiblich"}.get(p.get("Gender", ""), p.get("Gender", ""))),
        _row("Lebt", "ja" if str(p.get("IsLiving", "")) == "1" else ""),
    ])
    S.add("Lebensdaten", [
        wdate("Geburt: Datum", "Birth"), _row("Geburt: Ort", p.get("BirthLocation", "")),
        wdate("Tod: Datum", "Death"), _row("Tod: Ort", p.get("DeathLocation", "")),
        _row("Datenstatus", ", ".join(f"{k}: {v}" for k, v in ds.items() if v) if ds else ""),
    ])

    def who(j):
        g = ged_of(j)
        return wt.label(j) + f"  –  {wt.wtid(j)}" + (f"  –  GEDCOM {g}" if g else "  –  nicht in GEDCOM"), wt.label(j)

    rows = []
    rel = wt.relatives.get(i)
    parents = list(rel["parents"]) if rel else []
    for k in ("Father", "Mother"):
        v = p.get(k)
        if isinstance(v, int) and v > 0 and v not in parents:
            parents.append(v)
    for j in parents:
        role = "Vater" if p.get("Father") == j else "Mutter" if p.get("Mother") == j else "Elternteil"
        rows.append(_row(role, *who(j)))
    if rel:
        for k, m in rel["spouses"].items():
            j = int(k)
            rows.append(_row("Partner", *who(j)))
            md = parse_wt_date(m.get("date"))
            if not md.empty:
                rows.append(_row(f"Heirat mit {wt.name(j)}: Datum", str(md), _iso(md)))
            rows.append(_row(f"Heirat mit {wt.name(j)}: Ort", m.get("place", "")))
        for j in rel["children"]:
            rows.append(_row("Kind", *who(j)))
    S.add("Familie", rows)
    S.add("Hinweis", [_row("Biografie und Quellen",
                           "stehen auf dem WikiTree-Profil (nicht im Cache) – Profil öffnen")])
    return {"sections": S.list}


def as_text(details: dict, title: str = "") -> str:
    """Ganzer Block als Text für die Zwischenablage."""
    out = [title] if title else []
    for sec in details.get("sections", []):
        out.append(f"\n{sec['title']}")
        for r in sec["rows"]:
            out.append(f"{r['label']}: {r['value']}")
    return "\n".join(out).strip()
