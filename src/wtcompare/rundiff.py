"""Zwei gespeicherte Läufe vergleichen: Was hat sich seit dem letzten Mal geändert?"""

from __future__ import annotations

from collections import Counter

from .matching import SEVERITY

PROBLEM = {s for s, v in SEVERITY.items() if v >= 1}   # abweichend, nur …, genauer …


def _finding_keys(person: dict) -> dict:
    """Eindeutiger Schlüssel je Feststellung: (Kategorie, Hinweis-Bezug, laufende Nr.)."""
    out, cnt = {}, Counter()
    for f in person["f"]:
        ref = f["hinweis"] if f["kat"] in ("Ehe", "Eheort") else ""
        if f["kat"] == "Eltern":
            ref = f["hinweis"].split(" ")[0]   # Vater/Mutter
        base = (f["kat"], ref)
        cnt[base] += 1
        out[(*base, cnt[base])] = f
    return out


def diff_runs(old: dict, new: dict) -> dict:
    """Liefert Listen von Änderungen. Personen werden über die WikiTree-ID verknüpft."""
    po = {p["w"]: p for p in old["persons"]}
    pn = {p["w"]: p for p in new["persons"]}
    changes = []   # {"w","name","kat","art","alt","neu"}
    for w, p in pn.items():
        if w not in po:
            changes.append({"w": w, "name": p["wname"], "kat": "Person", "art": "neu zugeordnet",
                            "alt": "", "neu": f"{p['g']} {p['gname']}"})
            continue
        q = po[w]
        if q["g"] != p["g"]:
            changes.append({"w": w, "name": p["wname"], "kat": "Person", "art": "andere GEDCOM-Person",
                            "alt": f"{q['g']} {q['gname']}", "neu": f"{p['g']} {p['gname']}"})
        fo, fn = _finding_keys(q), _finding_keys(p)
        for k in fo.keys() | fn.keys():
            a, b = fo.get(k), fn.get(k)
            kat = (a or b)["kat"]
            if a and b and (a["status"], a["ged"], a["wt"]) == (b["status"], b["ged"], b["wt"]):
                continue
            sa = a["status"] if a else ""
            sb = b["status"] if b else ""
            if sa in PROBLEM and sb not in PROBLEM:
                art = "behoben"
            elif sb in PROBLEM and sa not in PROBLEM:
                art = "neue Abweichung"
            elif sa != sb:
                art = "Status geändert"
            else:
                art = "Wert geändert"
            fmt = lambda f: f"{f['status']}: GEDCOM „{f['ged']}“ / WikiTree „{f['wt']}“" if f else "–"
            changes.append({"w": w, "name": p["wname"], "kat": kat, "art": art, "alt": fmt(a), "neu": fmt(b)})
    for w, q in po.items():
        if w not in pn:
            changes.append({"w": w, "name": q["wname"], "kat": "Person", "art": "nicht mehr zugeordnet",
                            "alt": f"{q['g']} {q['gname']}", "neu": ""})

    mk = lambda m: (m["status"], m["who"], m["rel"])
    mo, mn = {mk(m): m for m in old["missing"]}, {mk(m): m for m in new["missing"]}
    missing_new = [mn[k] for k in mn.keys() - mo.keys()]
    missing_gone = [mo[k] for k in mo.keys() - mn.keys()]
    uo, un = {u["w"]: u for u in old["unmatched"]}, {u["w"]: u for u in new["unmatched"]}
    unmatched_new = [un[k] for k in un.keys() - uo.keys()]
    unmatched_gone = [uo[k] for k in uo.keys() - un.keys()]
    order = {"neue Abweichung": 0, "andere GEDCOM-Person": 1, "nicht mehr zugeordnet": 2, "Status geändert": 3,
             "Wert geändert": 4, "behoben": 5, "neu zugeordnet": 6}
    changes.sort(key=lambda c: (order.get(c["art"], 9), c["name"]))
    return {"old": old["meta"], "new": new["meta"], "changes": changes,
            "missing_new": missing_new, "missing_gone": missing_gone,
            "unmatched_new": unmatched_new, "unmatched_gone": unmatched_gone,
            "summary": dict(Counter(c["art"] for c in changes))}
