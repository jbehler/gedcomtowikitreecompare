import pytest

from wtcompare import wikitree as wtmod
from wtcompare.wikitree import WikiTree


class FakeResp:
    def __init__(self, status, headers=None, payload=None):
        self.status_code, self.headers, self._payload = status, headers or {}, payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self, responses):
        self.responses, self.calls = list(responses), []
        self.cookies = type("C", (), {"get_dict": lambda s: {"wikidb_wtb_UserName": "Behler-1"}})()
        self.headers = {}

    def post(self, url, data=None, **kw):
        self.calls.append(data)
        return self.responses.pop(0)


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr(wtmod.time, "sleep", lambda s: None)


def test_login_sends_appid_and_retries_429():
    wt = WikiTree(log=lambda s: None)
    wt.session = FakeSession([
        FakeResp(429, {"Retry-After": "3"}),
        FakeResp(302, {"Location": "https://x/?authcode=abc"}),
        FakeResp(200),
    ])
    assert wt.login("a@b.de", "pw") == "Behler-1"
    assert all(c["appId"] == wtmod.APP_ID for c in wt.session.calls)
    assert wt.session.calls[-1]["authcode"] == "abc"


def test_persistent_429_gives_clear_message():
    wt = WikiTree(log=lambda s: None)
    wt.session = FakeSession([FakeResp(429)] * 5)
    with pytest.raises(RuntimeError, match="zu viele Anfragen"):
        wt.login("a@b.de", "pw")


def test_login_reads_username_from_json():
    wt = WikiTree(log=lambda s: None)
    wt.session = FakeSession([
        FakeResp(302, {"Location": "https://x/?authcode=abc"}),
        FakeResp(200, payload={"clientLogin": {"result": "Success", "username": "Behler-77", "userid": 123}}),
    ])
    wt.session.cookies = type("C", (), {"get_dict": lambda s: {}})()
    assert wt.login("a@b.de", "pw") == "Behler-77"


def test_login_not_confirmed():
    wt = WikiTree(log=lambda s: None)
    wt.session = FakeSession([
        FakeResp(302, {"Location": "https://x/?authcode=abc"}),
        FakeResp(200, payload={"clientLogin": {"result": "error"}}),
    ])
    with pytest.raises(RuntimeError, match="nicht bestätigt"):
        wt.login("a@b.de", "pw")
    assert not wt.logged_in
