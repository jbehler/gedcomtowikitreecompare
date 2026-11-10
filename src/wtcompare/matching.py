"""Zuordnung GEDCOM <-> WikiTree und Feldvergleich."""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime
from typing import Callable

from .dates import PDate, parse_wt_date, year_range
from .gedcom import Gedcom, GPerson
from .profile import ged_details, wt_details
from .textutil import given_sim, norm, sim
from .wikitree import WikiTree

STATUSES = ["abweichend", "nur GEDCOM", "nur WikiTree", "genauer GEDCOM", "genauer WikiTree", "ähnlich", "gleich"]
SEVERITY = {"abweichend": 3, "nur GEDCOM": 2, "nur WikiTree": 2, "fehlt auf WikiTree": 2,
            "fehlt in GEDCOM": 2, "genauer GEDCOM": 1, "genauer WikiTree": 1, "ähnlich": 0.5, "gleich": 0}


def year_score(a: PDate, b: PDate) -> float:
    if a.empty or b.empty:
        return 0.5
    d = abs(a.y - b.y)
    return 1.0 if d == 0 else 0.85 if d <= 1 else 0.6 if d <= 3 else 0.3 if d <= 6 else 0.0


def pair_score(g: GPerson, wt: WikiTree, w: int, ignore_surname=False) -> float:
    ws = wt.sex(w)
    if g.sex and ws and g.sex != ws:
        return 0.0
    gs = given_sim(g.given, wt.given(w))
    ss = 1.0 if ignore_surname else max(sim(g.surname, wt.surname(w)),
                                        sim(g.married, wt.people.get(w, {}).get("LastNameCurrent")) * 0.9)
    ys = year_score(g.birth, wt.date(w, "Birth"))
    return 0.4 * gs + 0.3 * ss + 0.3 * ys


def greedy_match(cands_g, cands_w, scorer, threshold):
    scored = sorted(((scorer(g, w), g, w) for g in cands_g for w in cands_w), key=lambda t: -t[0])
    used_g, used_w, out = set(), set(), []
    for s, g, w in scored:
        if s < threshold or g in used_g or w in used_w:
            continue
        used_g.add(g)
        used_w.add(w)
        out.append((g, w, s))
    return out


@dataclass
class Finding:
    kat: str          # Kategorie
    status: str       # siehe STATUSES
    ged: str = ""
    wt: str = ""
    hinweis: str = ""


def _join(*parts):
    return " ".join(p for p in parts if p).strip()


def cmp_date(kat, g: PDate, w: PDate, hinweis="") -> Finding:
    gs, ws = str(g), str(w)
    if g.empty and w.empty:
        return Finding(kat, "gleich", "", "", hinweis)
    if g.empty:
        return Finding(kat, "nur WikiTree", gs, ws, hinweis)
    if w.empty:
        return Finding(kat, "nur GEDCOM", gs, ws, hinweis)
    if not (g.qual or w.qual):
        if g.y != w.y:
            return Finding(kat, "abweichend", gs, ws, hinweis)
    else:
        glo, ghi = year_range(g)
        wlo, whi = year_range(w)
        if ghi < wlo or whi < glo:
            return Finding(kat, "abweichend", gs, ws, hinweis)
        if g.y != w.y or g.qual in ("bef", "aft", "bet") or w.qual in ("bef", "aft", "bet"):
            if g.qual == w.qual and g.y == w.y and g.y2 == w.y2:
                pass  # gleicher Qualifikator, gleiches Jahr -> unten weiter vergleichen
            else:
                return Finding(kat, "ähnlich", gs, ws,
                               _join(hinweis, "Angaben sind verträglich (ca./vor/nach/zwischen)."))
    common = min(g.precision, w.precision)
    same = (common < 2 or g.m == w.m) and (common < 3 or g.d == w.d)
    if not same:
        return Finding(kat, "abweichend", gs, ws, hinweis)
    if g.precision > w.precision:
        return Finding(kat, "genauer GEDCOM", gs, ws, hinweis)
    if w.precision > g.precision:
        return Finding(kat, "genauer WikiTree", gs, ws, hinweis)
    if g.qual != w.qual:
        if not g.qual:
            return Finding(kat, "genauer GEDCOM", gs, ws, _join(hinweis, "WikiTree nur ungefähr."))
        if not w.qual:
            return Finding(kat, "genauer WikiTree", gs, ws, _join(hinweis, "GEDCOM nur ungefähr."))
        return Finding(kat, "ähnlich", gs, ws, _join(hinweis, "Unterschiedliche Genauigkeitsangabe."))
    return Finding(kat, "gleich", gs, ws, hinweis)


def cmp_event_alt(kat, g: PDate, w: PDate, is_alt: bool, note: str) -> Finding:
    """Wie cmp_date; liegt in der GEDCOM nur Taufe/Begräbnis vor, gilt ein Abstand von
    0–60 Tagen nach dem WikiTree-Datum als plausibel ("ähnlich")."""
    f = cmp_date(kat, g, w, note if is_alt else "")
    if is_alt and f.status in ("abweichend", "gleich", "genauer GEDCOM", "genauer WikiTree") \
            and g.precision == 3 and w.precision == 3:
        try:
            delta = (datetime(g.y, g.m, g.d) - datetime(w.y, w.m, w.d)).days
        except ValueError:
            return f
        if 0 < delta <= 60:
            f.status = "ähnlich"
            f.hinweis = f"{note} Liegt {delta} Tage nach dem WikiTree-Datum – plausibel."
    return f


_PLACE_DROP = {"deutschland", "germany", "deutsches reich", "preussen", "prussia", "koenigreich preussen",
               "nordrhein westfalen", "westfalen", "rheinprovinz", "provinz westfalen", "de"}


def place_core(s: str) -> list[str]:
    return [norm(p) for p in (s or "").split(",") if norm(p) and norm(p) not in _PLACE_DROP]


def cmp_place(kat, g: str, w: str, hinweis="") -> Finding:
    if not g and not w:
        return Finding(kat, "gleich", hinweis=hinweis)
    if not g:
        return Finding(kat, "nur WikiTree", g, w, hinweis)
    if not w:
        return Finding(kat, "nur GEDCOM", g, w, hinweis)
    if norm(g) == norm(w):
        return Finding(kat, "gleich", g, w, hinweis)
    cg, cw = place_core(g), place_core(w)
    if cg and cw and (cg[0] == cw[0] or sim(cg[0], cw[0]) >= 0.9):
        return Finding(kat, "ähnlich", g, w, _join(hinweis, "Gleicher Ort, andere Schreibweise/Verwaltungsebenen."))
    if sim(g, w) >= 0.85:
        return Finding(kat, "ähnlich", g, w, hinweis)
    return Finding(kat, "abweichend", g, w, hinweis)


def cmp_name(kat, g: str, w: str, given=False) -> Finding:
    if not g and not w:
        return Finding(kat, "gleich")
    if not g:
        return Finding(kat, "nur WikiTree", g, w)
    if not w:
        return Finding(kat, "nur GEDCOM", g, w)
    if norm(g) == norm(w):
        return Finding(kat, "gleich", g, w)
    s = given_sim(g, w) if given else sim(g, w)
    if s >= 0.8:
        return Finding(kat, "ähnlich", g, w, "Schreibvariante oder zusätzliche Vornamen.")
    return Finding(kat, "abweichend", g, w)


class Comparer:
    def __init__(self, ged: Gedcom, wt: WikiTree, threshold: float = 0.6,
                 log: Callable[[str], None] = lambda s: None):
        self.ged, self.wt, self.th, self.log = ged, wt, threshold, log
        self.g2w: dict[str, int] = {}
        self.w2g: dict[int, str] = {}
        self.how: dict[str, str] = {}
        self.findings: dict[str, list[Finding]] = defaultdict(list)
        self.missing: list[dict] = []
        self.done_fams: set[str] = set()
        self.unmatched: list = []

    def link(self, g, w, how):
        self.g2w[g] = w
        self.w2g[w] = g
        self.how[g] = how

    def run(self, g0: str, w0: int, only_watchlist_expand: bool = True,
            manual: dict[int, str] | None = None, ignored: set[int] | None = None):
        """manual: feste Zuordnungen WikiTree-Id -> GEDCOM-XREF (Vorrang vor dem automatischen Abgleich).
        ignored: Watchlist-Profile, die bewusst kein GEDCOM-Gegenstück haben."""
        wl = set(self.wt.watchlist)
        manual = {int(w): g for w, g in (manual or {}).items() if g in self.ged.indi}
        ignored = set(ignored or ())
        self.link(g0, w0, "Startpaar")
        roots = {(g0, w0)}
        for w, g in manual.items():
            if g in self.g2w or w in self.w2g:
                continue
            self.link(g, w, "manuell zugeordnet")
            roots.add((g, w))
        q = deque(roots)
        seen = set()
        n = 0
        while q:
            g, w = q.popleft()
            if (g, w) in seen:
                continue
            seen.add((g, w))
            if only_watchlist_expand and w not in wl and (g, w) not in roots:
                continue
            n += 1
            if n % 25 == 0:
                self.log(f"Abgleich: {n} Personen abgelaufen, {len(self.g2w)} zugeordnet")
            for ng, nw in self._relatives(g, w):
                q.append((ng, nw))
        self.log(f"Abgleich fertig: {len(self.g2w)} Paare")
        for g, w in self.g2w.items():
            self._compare_fields(g, w)
        self.unmatched = []
        free_g = [x for x in self.ged.indi if x not in self.g2w]
        for w in self.wt.watchlist:
            if w in self.w2g or w in ignored:
                continue
            self.unmatched.append((w, self.candidates(w, free_g)))

    def candidates(self, w: int, pool: list[str] | None = None, n: int = 3, min_score: float = 0.5):
        """Beste GEDCOM-Kandidaten für ein WikiTree-Profil (Vorfilter über das Geburtsjahr)."""
        pool = pool if pool is not None else [x for x in self.ged.indi if x not in self.g2w]
        wb = self.wt.date(w, "Birth")
        out = []
        for x in pool:
            p = self.ged.indi[x]
            if not wb.empty and not p.birth.empty and abs(p.birth.y - wb.y) > 10:
                continue
            s = pair_score(p, self.wt, w)
            if s >= min_score:
                out.append((s, x))
        out.sort(key=lambda t: -t[0])
        return out[:n]

    def _wt_parents(self, w: int, parents: list[int]) -> dict:
        """Vater/Mutter bestimmen: zuerst über die Felder Father/Mother, dann über das Geschlecht."""
        prof = self.wt.people.get(w, {})
        wp = {"Vater": None, "Mutter": None}
        rest = []
        for j in parents:
            if prof.get("Father") == j:
                wp["Vater"] = j
            elif prof.get("Mother") == j:
                wp["Mutter"] = j
            else:
                rest.append(j)
        for j in rest:
            sx = self.wt.sex(j)
            if sx == "M" and wp["Vater"] is None:
                wp["Vater"] = j
            elif sx == "F" and wp["Mutter"] is None:
                wp["Mutter"] = j
            elif sx == "" and wp["Vater"] is None and wp["Mutter"] is not None:
                wp["Vater"] = j
            elif sx == "" and wp["Mutter"] is None and wp["Vater"] is not None:
                wp["Mutter"] = j
            # sonst: Rolle unklar -> nicht raten
        return wp

    def _relatives(self, g, w):
        ged, wt = self.ged, self.wt
        r = wt.rel(w)
        new_pairs = []
        gp = dict(zip(("Vater", "Mutter"), ged.parents(g)))
        wp = self._wt_parents(w, r["parents"])
        for role in ("Vater", "Mutter"):
            gx, wx = gp[role], wp[role]
            if gx and wx:
                if gx in self.g2w or wx in self.w2g:
                    if self.g2w.get(gx) != wx:
                        self.findings[g].append(Finding("Eltern", "abweichend",
                                                        ged.indi[gx].label(), wt.label(wx),
                                                        f"{role} ist auf beiden Seiten verschiedenen Personen zugeordnet."))
                    continue
                s = pair_score(ged.indi[gx], wt, wx)
                if s >= self.th - 0.15:
                    self.link(gx, wx, f"{role} von {ged.indi[g].name}")
                    new_pairs.append((gx, wx))
                else:
                    self.findings[g].append(Finding("Eltern", "abweichend", ged.indi[gx].label(), wt.label(wx),
                                                    f"{role} passt nicht zusammen (Ähnlichkeit {s:.2f})."))
            elif gx and not wx:
                self._missing("fehlt auf WikiTree", f"{role} von", g, w, ged.indi[gx].label(), gx)
            elif wx and not gx:
                self._missing("fehlt in GEDCOM", f"{role} von", g, w, wt.label(wx), wx)

        # Partner
        gsp = {x: f for x, f in ged.spouses(g)}
        wsp = {int(k): v for k, v in r["spouses"].items()}
        matches = greedy_match([x for x in gsp if x not in self.g2w or self.g2w[x] in wsp],
                               [y for y in wsp if y not in self.w2g or self.w2g[y] in gsp],
                               lambda a, b: 1.0 if self.g2w.get(a) == b else pair_score(ged.indi[a], wt, b, ignore_surname=True),
                               self.th - 0.1)
        mg, mw = set(), set()
        for a, b, _ in matches:
            mg.add(a)
            mw.add(b)
            if a not in self.g2w:
                self.link(a, b, f"Partner von {ged.indi[g].name}")
                new_pairs.append((a, b))
            fam = gsp[a]
            m = wsp[b]
            who = f"mit {ged.indi[a].name}"
            if fam.xref not in self.done_fams:
                self.done_fams.add(fam.xref)
                self.findings[g].append(cmp_date("Ehe", fam.marr, parse_wt_date(m.get("date")), who))
                self.findings[g].append(cmp_place("Eheort", fam.marr_place, m.get("place", ""), who))
        for a in gsp:
            if a not in mg:
                self._missing("fehlt auf WikiTree", "Partner von", g, w, ged.indi[a].label(), a)
        for b in wsp:
            if b not in mw:
                self._missing("fehlt in GEDCOM", "Partner von", g, w, wt.label(b), b)

        # Kinder
        gch, wch = ged.children(g), r["children"]
        matches = greedy_match([x for x in gch if x not in self.g2w or self.g2w[x] in wch],
                               [y for y in wch if y not in self.w2g or self.w2g[y] in gch],
                               lambda a, b: 1.0 if self.g2w.get(a) == b else pair_score(ged.indi[a], wt, b),
                               self.th)
        mg = {a for a, _, _ in matches}
        mw = {b for _, b, _ in matches}
        for a, b, _ in matches:
            if a not in self.g2w:
                self.link(a, b, f"Kind von {ged.indi[g].name}")
                new_pairs.append((a, b))
        for a in gch:
            if a not in mg:
                self._missing("fehlt auf WikiTree", "Kind von", g, w, ged.indi[a].label(), a)
        for b in wch:
            if b not in mw:
                self._missing("fehlt in GEDCOM", "Kind von", g, w, wt.label(b), b)
        return new_pairs

    def _missing(self, status, rel, g, w, who, key):
        self.missing.append({"status": status, "rel": rel, "g": g, "w": w, "who": who, "key": key})

    def _compare_fields(self, g, w):
        p, wt = self.ged.indi[g], self.wt
        prof = wt.people.get(w, {})
        head = [cmp_name("Vorname(n)", p.given, wt.given(w), given=True),
                cmp_name("Geburtsname", p.surname, wt.surname(w))]
        if p.married or (prof.get("LastNameCurrent") and norm(prof.get("LastNameCurrent")) != norm(wt.surname(w))):
            head.append(cmp_name("Ehename", p.married, prof.get("LastNameCurrent", "")))
        F = self.findings[g]
        F[0:0] = head
        if p.sex and wt.sex(w) and p.sex != wt.sex(w):
            F.append(Finding("Geschlecht", "abweichend", p.sex, wt.sex(w)))
        F.append(cmp_event_alt("Geburt", p.birth, wt.date(w, "Birth"), p.birth_is_chr,
                               "GEDCOM: Taufdatum statt Geburt."))
        F.append(cmp_place("Geburtsort", p.birth_place, prof.get("BirthLocation", "")))
        F.append(cmp_event_alt("Tod", p.death, wt.date(w, "Death"), p.death_is_buri,
                               "GEDCOM: Begräbnisdatum statt Tod."))
        F.append(cmp_place("Sterbeort", p.death_place, prof.get("DeathLocation", "")))


def build_result(cmp: Comparer, meta: dict) -> dict:
    """Ergebnis als reine Daten (JSON-fähig): Grundlage für Anzeige, Export und Laufvergleich."""
    ged, wt = cmp.ged, cmp.wt
    wl = set(wt.watchlist)
    persons = []
    for g, w in cmp.g2w.items():
        fs = cmp.findings.get(g, [])
        persons.append({
            "g": g, "w": wt.wtid(w), "wid": w, "gname": ged.indi[g].label(), "wname": wt.label(w),
            "watch": w in wl, "how": cmp.how.get(g, ""),
            "score": sum(SEVERITY.get(f.status, 0) for f in fs),
            "f": [f.__dict__ for f in fs],
        })
    persons.sort(key=lambda p: -p["score"])
    # fehlende Personen: Duplikate entfernen; Personen, die später doch zugeordnet wurden, ignorieren
    seen, missing = set(), []
    for m in cmp.missing:
        k = (m["status"], m["key"])
        if k in seen:
            continue
        if m["status"] == "fehlt auf WikiTree" and m["key"] in cmp.g2w:
            continue
        if m["status"] == "fehlt in GEDCOM" and m["key"] in cmp.w2g:
            continue
        seen.add(k)
        on_wt = m["status"] == "fehlt auf WikiTree"
        if on_wt:
            details = ged_details(ged, m["key"], wt_of=lambda x: wt.wtid(cmp.g2w[x]) if x in cmp.g2w else None)
        else:
            details = wt_details(wt, m["key"], ged_of=lambda j: cmp.w2g.get(j))
        missing.append({"status": m["status"], "who": m["who"],
                        "rel": f"{m['rel']} {ged.indi[m['g']].name}",
                        "wid": wt.wtid(m["key"]) if not on_wt else wt.wtid(m["w"]),
                        "g": m["key"] if on_wt else m["g"],
                        # Verwandter, an den die Person angehängt wird (WikiTree-ID + Name)
                        "anchor": wt.wtid(m["w"]), "anchor_name": wt.label(m["w"]),
                        "details": details})
    unmatched = [{"w": wt.wtid(w), "wid": w, "wname": wt.label(w),
                  "cands": [{"g": x, "name": ged.indi[x].label(), "s": round(s, 2)} for s, x in c]}
                 for w, c in cmp.unmatched]
    return {"meta": meta, "persons": persons, "missing": missing, "unmatched": unmatched}
