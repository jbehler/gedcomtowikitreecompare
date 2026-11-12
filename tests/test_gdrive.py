import base64
import json

import pytest

from wtcompare import gdrive
from wtcompare.gdrive import AuthExpired, Drive


class R:
    def __init__(self, status=200, payload=None, headers=None, content=b""):
        self.status_code, self._p, self.headers, self.content = status, payload, headers or {}, content

    def json(self):
        if self._p is None:
            raise ValueError
        return self._p


class S:
    def __init__(self, responses):
        self.responses, self.calls = list(responses), []

    def post(self, url, data=None, **kw):
        self.calls.append(("POST", url, data, kw.get("headers")))
        return self.responses.pop(0)

    def request(self, method, url, headers=None, **kw):
        self.calls.append((method, url, kw.get("data"), headers))
        return self.responses.pop(0)


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr(gdrive.time, "sleep", lambda s: None)


def _idtok(email):
    body = base64.urlsafe_b64encode(json.dumps({"email": email}).encode()).decode().rstrip("=")
    return f"x.{body}.y"


def test_device_flow():
    s = S([R(200, {"device_code": "dc", "user_code": "ABCD-EFGH", "verification_url": "https://www.google.com/device",
                   "interval": 1, "expires_in": 60}),
           R(428, {"error": "authorization_pending"}),
           R(200, {"access_token": "at", "refresh_token": "rt", "expires_in": 3600, "id_token": _idtok("a@b.de")})])
    d = Drive("cid", "secret", session=s)
    flow = d.start_device_flow()
    assert flow["user_code"] == "ABCD-EFGH"
    assert d.poll_device_flow(flow) == "a@b.de"
    assert d.refresh_token == "rt"
    token_call = s.calls[-1][2]
    assert token_call["grant_type"] == "urn:ietf:params:oauth:grant-type:device_code"
    assert token_call["client_secret"] == "secret"
    assert "drive.appdata" in s.calls[0][2]["scope"]


def test_refresh_and_resumable_upload():
    s = S([R(200, {"access_token": "at2", "expires_in": 3600}),                     # Refresh
           R(200, {}, {"Location": "https://upload/session/1"}),                   # Session starten
           R(200, {"id": "f1", "name": "projekt-u.zip", "md5Checksum": "m", "size": "3",
                   "modifiedTime": "t", "appProperties": {"uid": "u"}})])          # Inhalt
    d = Drive("cid", "secret", "rt", session=s)
    f = d.upload("projekt-u.zip", b"abc", {"uid": "u"})
    assert f.id == "f1" and f.props["uid"] == "u"
    start = s.calls[1]
    assert start[0] == "POST" and "uploadType=resumable" not in start[1]   # Parameter gehen über params
    meta = json.loads(start[2])
    assert meta["parents"] == ["appDataFolder"]
    assert start[3]["Authorization"] == "Bearer at2"
    assert s.calls[2][:3] == ("PUT", "https://upload/session/1", b"abc")


def test_expired_refresh_token():
    d = Drive("cid", "secret", "rt", session=S([R(400, {"error": "invalid_grant"})]))
    with pytest.raises(AuthExpired, match="neu verbinden"):
        d.list()
