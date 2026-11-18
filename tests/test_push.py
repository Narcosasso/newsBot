"""Notifiche push: chiavi VAPID, iscrizione del dispositivo, invio e pulizia delle iscrizioni scadute."""

import pytest
from pywebpush import WebPushException

from cardbot import push as push_mod
from cardbot.db import PushSubscription, get_or_create_user, make_engine, make_session_factory
from cardbot.push import PushSender, load_keys
from tests.test_app_api import logged, make_client  # noqa: F401 (fixture)

SUB = {"endpoint": "https://web.push.apple.com/abc", "keys": {"p256dh": "BPk3", "auth": "a1b2"}}


class Resp:
    def __init__(self, status):
        self.status_code = status


@pytest.fixture
def sessions():
    return make_session_factory(make_engine("sqlite://"))


def test_keys_are_created_once_and_reused(sessions):
    with sessions() as s:
        first = load_keys(s)
        again = load_keys(s)
    assert first == again and len(first.public_key) == 87
    with sessions() as s:
        assert load_keys(s, "PUB", "PRIV").public_key == "PUB"   # chiavi da configurazione


async def test_send_and_drop_expired_subscriptions(sessions, monkeypatch):
    calls = []

    def fake_webpush(info, data, **kw):
        calls.append(info["endpoint"])
        if info["endpoint"].endswith("gone"):
            raise WebPushException("Gone", response=Resp(410))
        return Resp(201)

    monkeypatch.setattr(push_mod, "webpush", fake_webpush)
    with sessions() as s:
        user, _ = get_or_create_user(s, "393330000000")
        for ep in ("https://push.example/ok", "https://push.example/gone"):
            s.add(PushSubscription(user_id=user.id, endpoint=ep, p256dh="k", auth="a", failures=0))
        s.commit()
        uid = user.id
    sent = await PushSender(sessions).send_to_user(uid, "PokeVault", "Prova")
    assert sent == 1 and len(calls) == 2
    with sessions() as s:
        assert [x.endpoint for x in s.query(PushSubscription).all()] == ["https://push.example/ok"]


def test_push_api(make_client, monkeypatch):
    monkeypatch.setattr(push_mod, "webpush", lambda *a, **k: Resp(201))
    client, _ = logged(make_client)
    assert len(client.get("/api/push/key").json()["public_key"]) == 87
    assert client.post("/api/push/subscribe", json=SUB).json()["ok"]
    assert client.post("/api/push/subscribe", json=SUB).json()["ok"]          # stesso dispositivo: nessun doppione
    st = client.get("/api/push/status", params={"endpoint": SUB["endpoint"]}).json()
    assert st == {"devices": 1, "this_device": True}
    assert client.post("/api/push/test").json()["sent"] == 1
    client.post("/api/push/unsubscribe", json={"endpoint": SUB["endpoint"]})
    assert client.post("/api/push/test").status_code == 502


def test_price_history_api(make_client):
    from datetime import date
    from cardbot.db import PriceHistory
    client, sessions = logged(make_client)
    with sessions() as s:
        for d, base, holo in ((1, 10.0, 3.0), (2, 11.0, 3.1)):
            s.add(PriceHistory(id_product=5, fields="base", day=date(2026, 11, d), trend=base))
            s.add(PriceHistory(id_product=5, fields="holo", day=date(2026, 11, d), trend=holo))
        s.commit()
    pts = client.get("/api/price-history/5", params={"near": 3}).json()["points"]
    assert [p["price"] for p in pts] == [3.0, 3.1]
    pts = client.get("/api/price-history/5", params={"near": 11}).json()["points"]
    assert [p["price"] for p in pts] == [10.0, 11.0]
