#!/usr/bin/env python3
"""Kommandozeilen-Version des WikiTree <-> GEDCOM Vergleichs (die App liegt in src/main.py)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from wtcompare.cli import main  # noqa: E402

if __name__ == "__main__":
    main()
