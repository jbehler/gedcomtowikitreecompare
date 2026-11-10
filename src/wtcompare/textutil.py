"""Normalisierung und Ähnlichkeit von Namen/Orten."""

from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher
from functools import lru_cache

try:
    from rapidfuzz import fuzz as _rf_fuzz
except ImportError:  # optional (auf Android nicht vorhanden)
    _rf_fuzz = None

_UMLAUT = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss", "æ": "ae", "ø": "oe"})


@lru_cache(maxsize=200_000)
def norm(s: str | None) -> str:
    if not s:
        return ""
    s = s.casefold().translate(_UMLAUT)
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return " ".join(s.split())


def sim(a: str | None, b: str | None) -> float:
    a, b = norm(a), norm(b)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    if _rf_fuzz:
        return _rf_fuzz.token_sort_ratio(a, b) / 100.0
    a2, b2 = " ".join(sorted(a.split())), " ".join(sorted(b.split()))
    return SequenceMatcher(None, a2, b2).ratio()


def given_sim(a: str | None, b: str | None) -> float:
    """Vornamen: volle Ähnlichkeit, aber auch Teilübereinstimmung (Rufname) berücksichtigen."""
    full = sim(a, b)
    ta, tb = set(norm(a).split()), set(norm(b).split())
    if ta and tb:
        overlap = len(ta & tb) / min(len(ta), len(tb))
        full = max(full, 0.85 * overlap)
    return full
