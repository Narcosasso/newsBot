import hashlib
import hmac
import json

import pytest
from fastapi.testclient import TestClient

from cardbot import app as app_module
from cardbot.app import Container, create_app
from cardbot.config import Settings
from cardbot.db import make_engine, make_session_factory
from cardbot.whatsapp.webhook import parse_events, verify_signature

SECRET = "app-secret"


def sign(body: bytes) -> str:
    return "sha256=" + hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()


def text_payload(msg_id: str, wa_id: str = "393330000000", body: str = "ciao") -> dict:
    return {"entry": [{"changes": [{"value": {"messages": [
        {"id": msg_id, "from": wa_id, "type": "text", "text": {"body": body}}]}}]}]}


@pytest.fixture
def client(monkeypatch):
    processed = []

    async def fake_process(container, ev):
        processed.append(ev)

    monkeypatch.setattr(app_module, "process_event", fake_process)
    settings = Settings(whatsapp_app_secret=SECRET, whatsapp_verify_token="verify-me",
                        allowed_wa_ids="393330000000", database_url="sqlite://")
    container = Container(settings, make_session_factory(make_engine("sqlite://")), whatsapp=None, engine=None)
    return TestClient(create_app(container)), processed


def test_signature_helpers():
    body = b'{"a":1}'
    assert verify_signature(SECRET, body, sign(body))
    assert not verify_signature(SECRET, body, "sha256=deadbeef")
    assert not verify_signature(SECRET, body, None)
    assert not verify_signature("", body, sign(body))


def test_verify_challenge(client):
    c, _ = client
    ok = c.get("/webhook", params={"hub.mode": "subscribe", "hub.verify_token": "verify-me", "hub.challenge": "42"})
    assert ok.status_code == 200 and ok.text == "42"
    bad = c.get("/webhook", params={"hub.mode": "subscribe", "hub.verify_token": "nope", "hub.challenge": "42"})
    assert bad.status_code == 403


def test_rejects_bad_signature(client):
    c, processed = client
    body = json.dumps(text_payload("m1")).encode()
    r = c.post("/webhook", content=body, headers={"X-Hub-Signature-256": "sha256=00"})
    assert r.status_code == 403 and processed == []


def test_accepts_and_dedups_retries(client):
    c, processed = client
    body = json.dumps(text_payload("m1")).encode()
    for _ in range(3):  # Meta ritenta lo stesso webhook
        r = c.post("/webhook", content=body, headers={"X-Hub-Signature-256": sign(body)})
        assert r.status_code == 200
    assert [e.message_id for e in processed] == ["m1"]


def test_ignores_unknown_numbers(client):
    c, processed = client
    body = json.dumps(text_payload("m2", wa_id="15550001111")).encode()
    assert c.post("/webhook", content=body, headers={"X-Hub-Signature-256": sign(body)}).status_code == 200
    assert processed == []


def test_parse_events_kinds():
    payload = {"entry": [{"changes": [{"value": {
        "statuses": [{"id": "s1", "status": "delivered"}],
        "messages": [
            {"id": "a", "from": "39", "type": "image", "image": {"id": "MEDIA", "mime_type": "image/jpeg",
                                                                 "caption": "ita, eng"}},
            {"id": "b", "from": "39", "type": "interactive",
             "interactive": {"type": "button_reply", "button_reply": {"id": "cand:1", "title": "2"}}},
            {"id": "c", "from": "39", "type": "sticker", "sticker": {}},
        ]}}]}]}
    events = parse_events(payload)
    assert [(e.message_id, e.kind) for e in events] == [("a", "image"), ("b", "button"), ("c", "other")]
    assert events[0].media_id == "MEDIA" and events[0].text == "ita, eng"
    assert events[1].button_id == "cand:1"


def test_health_endpoints(client):
    c, _ = client
    assert c.get("/health").json() == {"status": "ok"}  # usato su Cloud Run (/healthz lì è riservato)
    assert c.get("/healthz").status_code == 200
