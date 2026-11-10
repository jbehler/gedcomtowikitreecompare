"""Datumsmodell für GEDCOM- und WikiTree-Daten."""

from __future__ import annotations

import re
from dataclasses import dataclass

MONTHS = {m: i for i, m in enumerate(
    ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"], 1)}
# deutsche Monatskürzel, falls ein Export sie enthält
MONTHS.update({"MRZ": 3, "MÄR": 3, "MAI": 5, "OKT": 10, "DEZ": 12})


@dataclass
class PDate:
    y: int | None = None
    m: int | None = None
    d: int | None = None
    qual: str = ""          # "", "abt", "bef", "aft", "bet"
    raw: str = ""
    y2: int | None = None   # Endjahr bei "BET x AND y" / "FROM x TO y"

    @property
    def empty(self) -> bool:
        return self.y is None

    @property
    def precision(self) -> int:
        return 0 if self.y is None else 1 if self.m is None else 2 if self.d is None else 3

    def __str__(self) -> str:
        if self.empty:
            return ""
        q = {"abt": "ca. ", "bef": "vor ", "aft": "nach ", "bet": "zw. "}.get(self.qual, "")
        if self.d:
            s = f"{q}{self.d:02d}.{self.m:02d}.{self.y}"
        elif self.m:
            s = f"{q}{self.m:02d}.{self.y}"
        else:
            s = f"{q}{self.y}"
        if self.qual == "bet" and self.y2 and self.y2 != self.y:
            s += f" und {self.y2}"
        return s


def _parse_part(t: str) -> tuple[int | None, int | None, int | None]:
    toks = re.findall(r"[A-ZÄÖÜ]+|\d+", t)
    y = m = d = None
    nums = []
    for tok in toks:
        if tok.isdigit():
            nums.append(int(tok))
        elif tok[:3] in MONTHS:
            m = MONTHS[tok[:3]]
    years = [n for n in nums if n > 31]
    if years:
        y = years[-1]
    days = [n for n in nums if 1 <= n <= 31]
    if m and days:
        d = days[0]
    elif not m and len(nums) == 3 and y:   # z. B. 12 03 1850
        d, m = nums[0], (nums[1] if 1 <= nums[1] <= 12 else None)
        if m is None:
            d = None
    return y, m, d


def parse_ged_date(s: str | None) -> PDate:
    if not s:
        return PDate()
    raw = s.strip()
    t = raw.upper()
    t = re.sub(r"\(.*?\)", " ", t)            # Datumsphrasen "(unbekannt)" entfernen
    t = re.sub(r"@#D[A-Z ]+@", " ", t)        # Kalender-Escape (@#DJULIAN@ …)
    t = re.sub(r"(\d{3,4})/\d{1,2}\b", r"\1", t)   # Doppeldatierung 1700/01
    t = t.replace(".", " ")
    qual = ""
    if re.match(r"^\s*(ABT|ABOUT|EST|CAL|CA|CIRCA|UM|INT)\b", t):
        qual = "abt" if not t.lstrip().startswith("INT") else ""
    elif re.match(r"^\s*(BEF|BEFORE|VOR)\b", t):
        qual = "bef"
    elif re.match(r"^\s*(AFT|AFTER|NACH)\b", t):
        qual = "aft"
    elif re.match(r"^\s*(BET|FROM)\b", t):
        qual = "bet"
    y2 = None
    if qual == "bet":
        parts = re.split(r"\b(?:AND|TO)\b", t)
        if len(parts) > 1:
            y2 = _parse_part(parts[1])[0]
        t = parts[0]
    elif re.match(r"^\s*TO\b", t):     # "TO 1850" = spätestens
        qual = "bef"
    y, m, d = _parse_part(t)
    if y is None:
        return PDate(raw=raw)
    if qual == "bet" and y2 is None:
        qual = "aft" if t.lstrip().startswith("FROM") else "abt"
    return PDate(y, m, d, qual, raw, y2)


# WikiTree DataStatus-Werte für Daten. Bekannt aus Profilen: "guess", "certain", "before", "after",
# "uncertain" – die API-Doku listet die Werte nicht vollständig auf.
_WT_QUAL = {"guess": "abt", "uncertain": "abt", "before": "bef", "after": "aft"}


def parse_wt_date(s: str | None, status: str | None = None) -> PDate:
    if not s or s.startswith("0000"):
        return PDate()
    parts = s.split("-")
    try:
        y, m, d = (int(p) for p in parts[:3])
    except ValueError:
        return PDate(raw=s)
    qual = _WT_QUAL.get((status or "").lower(), "")
    return PDate(y or None, m or None, d or None, qual, s)


def year_range(p: PDate, tol_abt: int = 2) -> tuple[float, float]:
    """Jahresbereich, den ein Datum (mit Qualifikator) abdeckt."""
    if p.empty:
        return float("-inf"), float("inf")
    if p.qual == "bef":
        return float("-inf"), p.y
    if p.qual == "aft":
        return p.y, float("inf")
    if p.qual == "bet":
        return p.y, (p.y2 or p.y)
    if p.qual == "abt":
        return p.y - tol_abt, p.y + tol_abt
    return p.y, p.y
