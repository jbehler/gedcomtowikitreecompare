"""Google Drive (versteckter App-Ordner "appDataFolder") mit Geräte-Anmeldung (OAuth 2.0 für
"TV and Limited-Input Devices").

Ablauf laut Google-Doku:
  1. POST https://oauth2.googleapis.com/device/code  (client_id, scope) -> device_code, user_code,
     verification_url, interval, expires_in
  2. Nutzer gibt user_code auf verification_url ein
  3. App fragt https://oauth2.googleapis.com/token ab (client_id, client_secret, device_code,
     grant_type=urn:ietf:params:oauth:grant-type:device_code) bis Zustimmung oder Ablauf
Scope: drive.appdata (nicht sensibel; nur der versteckte App-Ordner) + openid/email für die Anzeige.
"""

from __future__ import annotations

import base64
import json
import time
from dataclasses import dataclass
from typing import Callable

DEVICE_URL = "https://oauth2.googleapis.com/device/code"
TOKEN_URL = "https://oauth2.googleapis.com/token"
API = "https://www.googleapis.com/drive/v3"
UPLOAD = "https://www.googleapis.com/upload/drive/v3"
SCOPES = "openid email https://www.googleapis.com/auth/drive.appdata"


class DriveError(RuntimeError):
    pass


class AuthExpired(DriveError):
    """Refresh-Token ungültig (widerrufen, oder Google-App im Status "Testing" -> 7 Tage)."""


@dataclass
class RemoteFile:
    id: str
    name: str
    modified: str
    md5: str
    size: int
    props: dict


def _email_from_id_token(tok: str | None) -> str:
    """Nur zur Anzeige: E-Mail aus dem id_token lesen (ohne Signaturprüfung)."""
    try:
        payload = tok.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        return json.loads(base64.urlsafe_b64decode(payload)).get("email", "")
    except Exception:
        return ""


class Drive:
    def __init__(self, client_id: str, client_secret: str, refresh_token: str = "", session=None):
        self.client_id = client_id.strip()
        self.client_secret = client_secret.strip()
        self.refresh_token = refresh_token
        self._access = ""
        self._access_until = 0.0
        self._session = session

    @property
    def s(self):
        if self._session is None:
            import requests
            self._session = requests.Session()
        return self._session

    # ---------------------------------------------------------------- Anmeldung
    def start_device_flow(self) -> dict:
        r = self.s.post(DEVICE_URL, data={"client_id": self.client_id, "scope": SCOPES}, timeout=30)
        data = _json(r)
        if r.status_code != 200 or "device_code" not in data:
            raise DriveError(f"Google lehnt die Anmeldung ab: {data.get('error_description') or data.get('error') or r.status_code}. "
                             "Client-ID prüfen (Typ „TVs and Limited Input devices“).")
        return data

    def poll_device_flow(self, flow: dict, should_stop: Callable[[], bool] = lambda: False) -> str:
        """Wartet, bis der Nutzer zugestimmt hat. Liefert die E-Mail (falls vorhanden)."""
        interval = int(flow.get("interval") or 5)
        deadline = time.time() + int(flow.get("expires_in") or 1800)
        while time.time() < deadline:
            for _ in range(interval):
                if should_stop():
                    raise DriveError("Anmeldung abgebrochen.")
                time.sleep(1)
            r = self.s.post(TOKEN_URL, data={
                "client_id": self.client_id, "client_secret": self.client_secret,
                "device_code": flow["device_code"],
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code"}, timeout=30)
            data = _json(r)
            err = data.get("error")
            if r.status_code == 200 and data.get("access_token"):
                self.refresh_token = data.get("refresh_token", self.refresh_token)
                self._set_access(data)
                return _email_from_id_token(data.get("id_token"))
            if err == "authorization_pending":
                continue
            if err == "slow_down":
                interval += 5
                continue
            if err == "access_denied":
                raise DriveError("Zugriff in Google abgelehnt.")
            if err == "expired_token":
                break
            raise DriveError(f"Google-Anmeldung fehlgeschlagen: {data.get('error_description') or err or r.status_code}")
        raise DriveError("Der Anmeldecode ist abgelaufen. Bitte neu verbinden.")

    def _set_access(self, data: dict):
        self._access = data["access_token"]
        self._access_until = time.time() + int(data.get("expires_in") or 3600) - 60

    def _token(self) -> str:
        if self._access and time.time() < self._access_until:
            return self._access
        if not self.refresh_token:
            raise AuthExpired("Nicht mit Google Drive verbunden.")
        r = self.s.post(TOKEN_URL, data={"client_id": self.client_id, "client_secret": self.client_secret,
                                         "refresh_token": self.refresh_token, "grant_type": "refresh_token"},
                        timeout=30)
        data = _json(r)
        if r.status_code != 200 or not data.get("access_token"):
            if data.get("error") in ("invalid_grant", "unauthorized_client", "invalid_client"):
                raise AuthExpired("Die Google-Anmeldung ist abgelaufen oder wurde widerrufen. Bitte neu verbinden. "
                                  "(Steht die Google-App noch auf „Testing“, läuft sie nach 7 Tagen ab.)")
            raise DriveError(f"Google-Token konnte nicht erneuert werden: {data.get('error') or r.status_code}")
        self._set_access(data)
        return self._access

    def _req(self, method: str, url: str, headers: dict | None = None, **kw):
        r = None
        for attempt in range(4):
            h = {**(headers or {}), "Authorization": f"Bearer {self._token()}"}
            r = self.s.request(method, url, headers=h, timeout=300, **kw)
            if r.status_code == 401 and attempt == 0:
                self._access = ""          # Token abgelaufen -> einmal erneuern
                continue
            if r.status_code in (429, 500, 502, 503, 504):
                time.sleep(2 ** attempt * 2)
                continue
            if r.status_code >= 400:
                d = _json(r)
                msg = (d.get("error") or {}).get("message") if isinstance(d.get("error"), dict) else d.get("error")
                raise DriveError(f"Google Drive: {msg or r.status_code}")
            return r
        raise DriveError(f"Google Drive antwortet nicht (HTTP {r.status_code}).")

    # ---------------------------------------------------------------- Dateien
    FIELDS = "id,name,modifiedTime,md5Checksum,size,appProperties"

    def list(self) -> list[RemoteFile]:
        out, token = [], None
        while True:
            params = {"spaces": "appDataFolder", "fields": f"nextPageToken,files({self.FIELDS})", "pageSize": 100}
            if token:
                params["pageToken"] = token
            d = _json(self._req("GET", f"{API}/files", params=params))
            out += [_remote(f) for f in d.get("files", [])]
            token = d.get("nextPageToken")
            if not token:
                return out

    def upload(self, name: str, data: bytes, props: dict, file_id: str | None = None) -> RemoteFile:
        """Resumable Upload (für Dateien über 5 MB empfohlen); neu anlegen oder Inhalt ersetzen."""
        meta = {"name": name, "appProperties": props}
        if file_id:
            url, method = f"{UPLOAD}/files/{file_id}", "PATCH"
        else:
            url, method = f"{UPLOAD}/files", "POST"
            meta["parents"] = ["appDataFolder"]
        r = self._req(method, url, params={"uploadType": "resumable", "fields": self.FIELDS},
                      headers={"Content-Type": "application/json; charset=UTF-8",
                               "X-Upload-Content-Type": "application/zip",
                               "X-Upload-Content-Length": str(len(data))},
                      data=json.dumps(meta))
        loc = r.headers.get("Location")
        if not loc:
            raise DriveError("Google Drive: keine Upload-Adresse erhalten.")
        r = self._req("PUT", loc, headers={"Content-Type": "application/zip"}, data=data)
        return _remote(_json(r))

    def download(self, file_id: str) -> bytes:
        return self._req("GET", f"{API}/files/{file_id}", params={"alt": "media"}).content

    def delete(self, file_id: str):
        self._req("DELETE", f"{API}/files/{file_id}")


def _json(r) -> dict:
    try:
        d = r.json()
        return d if isinstance(d, dict) else {}
    except ValueError:
        return {}


def _remote(f: dict) -> RemoteFile:
    return RemoteFile(f.get("id", ""), f.get("name", ""), f.get("modifiedTime", ""), f.get("md5Checksum", ""),
                      int(f.get("size") or 0), f.get("appProperties") or {})
