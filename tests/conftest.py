import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

DATA = Path(__file__).parent / "data"


@pytest.fixture
def ged_bytes():
    return (DATA / "familie.ged").read_bytes()


def make_cache(path: Path):
    """Kleiner WikiTree-Cache: Vater, Mutter (ohne Gender!), Kind, Enkel + ein Profil ohne Gegenstück."""
    P = lambda i, name, first, last, birth="0000-00-00", death="0000-00-00", g="", father=0, mother=0, **kw: {
        "Id": i, "Name": name, "FirstName": first, "LastNameAtBirth": last, "BirthDate": birth,
        "DeathDate": death, "Gender": g, "Father": father, "Mother": mother, **kw}
    people = {
        1: P(1, "Behler-1", "Johann", "Behler", "1850-03-12", "1910-00-00", "Male"),
        2: P(2, "Schmidt-7", "Maria", "Schmidt", "1855-00-00", "", "", LastNameCurrent="Behler"),
        3: P(3, "Behler-64", "Heinrich", "Behler", "1880-05-01", "1950-02-02", "Male", 1, 2,
             BirthLocation="Dortmund, Westfalen, Preußen"),
        4: P(4, "Behler-65", "Karl", "Behler", "1912-00-00", "", "Male", 3, 0),
        5: P(5, "Fremd-1", "Otto", "Fremd", "1700-00-00", "", "Male"),
        6: P(6, "Behler-66", "Fritz", "Behler", "1918-07-09", "1944-00-00", "Male", 3, 0,
             BirthLocation="Dortmund", Nicknames="Fritze", DataStatus={"DeathDate": "guess"}),
    }
    rel = {
        1: {"parents": [], "children": [3], "spouses": {"2": {"date": "1878-06-01", "place": "Dortmund"}}},
        2: {"parents": [], "children": [3], "spouses": {"1": {"date": "1878-06-01", "place": "Dortmund"}}},
        3: {"parents": [1, 2], "children": [4, 6], "spouses": {}},
        4: {"parents": [3], "children": [], "spouses": {}},
        5: {"parents": [], "children": [], "spouses": {}},
    }
    path.write_text(json.dumps({"watchlist": [1, 2, 3, 4, 5], "people": people, "relatives": rel}), encoding="utf-8")
