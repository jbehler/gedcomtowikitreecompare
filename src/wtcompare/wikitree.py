"""Lesender Zugriff auf die offizielle WikiTree-API (https://github.com/wikitree/wikitree-api).

Es wird nichts auf WikiTree verändert.
"""

from __future__ import annotations

import json
import re
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Callable
from urllib.parse import unquote

from .dates import parse_wt_date

API_URL = "https://api.wikitree.com/api.php"
APP_ID = "GedcomWatchlistCompare"
WT_FIELDS = ("Id,Name,FirstName,MiddleName,RealName,LastNameAtBirth,LastNameCurrent,LastNameOther,"
             "BirthDate,DeathDate,BirthLocation,DeathLocation,Gender,Father,Mother,DataStatus,IsLiving,Privacy")


class Cancelled(Exception):
    pass


def _as_dict(v) -> dict:
    """PHP liefert leere Objekte manchmal als [] – vereinheitlichen."""
    if isinstance(v, dict):
        return v
    if isinstance(v, list):
        return {str(i.get("Id")): i for i in v if isinstance(i, dict) and i.get("Id")}
    return {}


def _first(res):
    return res[0] if isinstance(res, list) and res else res


class WikiTree:
    """Hält alle abgerufenen WikiTree-Profile; lädt fehlende bei Bedarf nach (mit Cache)."""

    def __init__(self, cache_path: Path | None = None, offline: bool = False, delay: float = 0.5,
                 log: Callable[[str], None] = print, cancel: threading.Event | None = None):
        self.cache_path = cache_path
        self.offline = offline
        self.delay = delay
        self.log = log
        self.cancel = cancel
        self.session = None
        self.user = ""
        self.people: dict[int, dict] = {}       # Id -> Profil
        self.relatives: dict[int, dict] = {}    # Id -> {"parents": [...], "spouses": {id: marriage}, "children": [...]}
        self.watchlist: list[int] = []
        self.name_to_id: dict[str, int] = {}
        self.saved = ""
        if cache_path and cache_path.exists():
            data = json.loads(cache_path.read_text(encoding="utf-8"))
            self.people = {int(k): v for k, v in data.get("people", {}).items()}
            self.relatives = {int(k): v for k, v in data.get("relatives", {}).items()}
            self.watchlist = [int(x) for x in data.get("watchlist", [])]
            self.saved = data.get("saved", "")
            for i, p in self.people.items():
                if p.get("Name"):
                    self.name_to_id[p["Name"]] = i

    def save(self):
        if not self.cache_path:
            return
        self.saved = datetime.now().isoformat(timespec="seconds")
        tmp = self.cache_path.with_suffix(".tmp")
        tmp.write_text(json.dumps({
            "saved": self.saved,
            "watchlist": self.watchlist,
            "people": self.people,
            "relatives": self.relatives,
        }, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.cache_path)

    def clear(self):
        self.people, self.relatives, self.watchlist, self.name_to_id = {}, {}, [], {}

    # ---------------------------------------------------------------- HTTP
    def _check_cancel(self):
        if self.cancel is not None and self.cancel.is_set():
            raise Cancelled()

    def _session(self):
        import requests
        if self.session is None:
            self.session = requests.Session()
            self.session.headers["User-Agent"] = f"{APP_ID}/1.0"
        return self.session

    def _post(self, data: dict):
        if self.offline:
            raise RuntimeError("Offline-Modus: Daten fehlen im Cache – ohne Offline-Modus erneut starten.")
        self._check_cancel()
        s = self._session()
        data = {**data, "appId": APP_ID}
        r = None
        for attempt in range(4):
            r = s.post(API_URL, data=data, timeout=60)
            if r.status_code == 429 or r.status_code >= 500:
                time.sleep(5 * (attempt + 1))
                self._check_cancel()
                continue
            r.raise_for_status()
            time.sleep(self.delay)
            return r.json()
        r.raise_for_status()
        raise RuntimeError(f"WikiTree antwortet nicht (HTTP {r.status_code}).")

    @property
    def logged_in(self) -> bool:
        return bool(self.user)

    def login(self, email: str, password: str) -> str:
        """Login wie im offiziellen Python-Beispiel der WikiTree-API (examples/authentication/python.py)."""
        s = self._session()
        r = s.post(API_URL, data={"action": "clientLogin", "doLogin": 1,
                                  "wpEmail": email, "wpPassword": password},
                   allow_redirects=False, timeout=60)
        r.raise_for_status()
        loc = r.headers.get("Location", "")
        mm = re.search(r"authcode=(.+)$", loc)
        if r.status_code != 302 or not mm:
            raise RuntimeError("WikiTree-Login fehlgeschlagen (kein authcode). E-Mail/Passwort prüfen.")
        r = s.post(API_URL, data={"action": "clientLogin", "authcode": mm.group(1)},
                   allow_redirects=False, timeout=60)
        r.raise_for_status()
        cookies = s.cookies.get_dict()
        self.user = unquote(cookies.get("wikidb_wtb_UserName", "")) or "?"
        return self.user

    def logout(self):
        self.session = None
        self.user = ""

    # ---------------------------------------------------------------- Abrufe
    def _store(self, prof: dict) -> int | None:
        try:
            i = int(prof.get("Id"))
        except (TypeError, ValueError):
            return None
        if i <= 0:
            return None
        old = self.people.get(i, {})
        merged = {**old, **{k: v for k, v in prof.items()
                            if k not in ("Parents", "Children", "Spouses", "Siblings", "index")}}
        self.people[i] = merged
        if merged.get("Name"):
            self.name_to_id[merged["Name"]] = i
        return i

    def fetch_watchlist(self):
        """getWatchlist braucht Anmeldung."""
        self.watchlist = []
        offset, limit = 0, 100
        while True:
            item = _first(self._post({"action": "getWatchlist", "limit": limit, "offset": offset,
                                      "getSpace": 0, "getPerson": 1, "fields": WT_FIELDS}))
            if not isinstance(item, dict):
                raise RuntimeError(f"Unerwartete Antwort von getWatchlist: {str(item)[:300]}")
            if item.get("status") not in (None, 0, "0", ""):
                raise RuntimeError(f"getWatchlist-Fehler: {item.get('status')}")
            total = int(item.get("watchlistCount") or 0)
            # Die Doku nennt sowohl "watchlist" als auch "items" als Ergebnisfeld.
            batch = item.get("watchlist") or item.get("items") or []
            for prof in batch:
                if isinstance(prof, dict) and isinstance(prof.get("person"), dict):
                    prof = prof["person"]
                i = self._store(prof)
                if i and i not in self.watchlist:
                    self.watchlist.append(i)
            offset += limit
            self.log(f"Watchlist: {len(self.watchlist)}/{total}")
            if not batch or offset >= total:
                break
        if not self.watchlist:
            self.log("WARNUNG: Watchlist ist leer – Login erfolgreich?")

    def fetch_relatives(self, ids: list[int], batch_size: int = 20):
        todo = [i for i in ids if i not in self.relatives]
        for k in range(0, len(todo), batch_size):
            chunk = todo[k:k + batch_size]
            item = _first(self._post({"action": "getRelatives", "keys": ",".join(map(str, chunk)),
                                      "fields": WT_FIELDS, "getParents": 1, "getChildren": 1,
                                      "getSpouses": 1}))
            for it in (item or {}).get("items", []) or []:
                person = it.get("person") or {}
                pid = self._store(person)
                if not pid:
                    continue
                rel = {"parents": [], "children": [], "spouses": {}}
                for p in _as_dict(person.get("Parents")).values():
                    j = self._store(p)
                    if j:
                        rel["parents"].append(j)
                for c in _as_dict(person.get("Children")).values():
                    j = self._store(c)
                    if j:
                        rel["children"].append(j)
                for s in _as_dict(person.get("Spouses")).values():
                    j = self._store(s)
                    if j:
                        rel["spouses"][str(j)] = {"date": s.get("marriage_date", ""),
                                                  "place": s.get("marriage_location", "")}
                self.relatives[pid] = rel
            for i in chunk:   # private/unbekannte Profile nicht endlos neu anfragen
                self.relatives.setdefault(i, {"parents": [], "children": [], "spouses": {}})
            if len(todo) > batch_size:
                self.log(f"Verwandte geladen: {min(k + batch_size, len(todo))}/{len(todo)}")

    def get_profile(self, key: str) -> int:
        item = _first(self._post({"action": "getProfile", "key": key, "fields": WT_FIELDS}))
        i = self._store((item or {}).get("profile") or {})
        if not i:
            raise RuntimeError(f"WikiTree-Profil {key} nicht gefunden.")
        return i

    def resolve(self, key: str) -> int:
        key = key.strip()
        if key in self.name_to_id:
            return self.name_to_id[key]
        if key.isdigit():   # interne User-Id (getRelatives akzeptiert sie)
            return int(key)
        return self.get_profile(key)

    def search_person(self, first: str = "", last: str = "", birth_year: int | None = None,
                      only_watchlist: bool = False, limit: int = 30) -> list[int]:
        """searchPerson der WikiTree-API. Ob ohne Anmeldung alle Treffer kommen, ist nicht dokumentiert."""
        data = {"action": "searchPerson", "FirstName": first, "LastName": last,
                "limit": limit, "fields": WT_FIELDS}
        if birth_year:
            data.update({"BirthDate": f"{birth_year}-01-01", "dateSpread": 2})
        if only_watchlist:
            data["watchlist"] = 1
        item = _first(self._post(data))
        if not isinstance(item, dict):
            return []
        if item.get("status") not in (None, 0, "0", ""):
            raise RuntimeError(f"Suche fehlgeschlagen: {item.get('status')}")
        out = []
        for m in item.get("matches") or []:
            i = self._store(m) if isinstance(m, dict) else None
            if i:
                out.append(i)
        return out

    def rel(self, i: int) -> dict:
        if i not in self.relatives:
            self.fetch_relatives([i])
        r = self.relatives[i]
        r = {"parents": list(r["parents"]), "children": list(r["children"]), "spouses": dict(r["spouses"])}
        p = self.people.get(i, {})
        # Eltern auch aus Father/Mother ableiten (falls Parents leer)
        for k in ("Father", "Mother"):
            v = p.get(k)
            if isinstance(v, int) and v > 0 and v not in r["parents"]:
                r["parents"].append(v)
        return r

    # ---------------------------------------------------------------- Profilzugriff
    def given(self, i):
        p = self.people.get(i, {})
        return " ".join(x for x in (p.get("FirstName"), p.get("MiddleName")) if x)

    def surname(self, i):
        return self.people.get(i, {}).get("LastNameAtBirth", "") or ""

    def sex(self, i):
        g = (self.people.get(i, {}).get("Gender") or "")
        return "M" if g.startswith("M") else "F" if g.startswith("F") else ""

    def date(self, i, kind):  # kind = Birth / Death
        p = self.people.get(i, {})
        ds = p.get("DataStatus") or {}
        return parse_wt_date(p.get(f"{kind}Date"), ds.get(f"{kind}Date") if isinstance(ds, dict) else None)

    def name(self, i):
        p = self.people.get(i, {})
        return f"{self.given(i)} {self.surname(i)}".strip() or p.get("Name", str(i))

    def label(self, i):
        b, d = self.date(i, "Birth"), self.date(i, "Death")
        life = f"{b or '?'} – {d or ''}".strip(" –")
        n = self.name(i)
        return f"{n} ({life})" if life != "?" else n

    def wtid(self, i):
        return self.people.get(i, {}).get("Name", str(i))
