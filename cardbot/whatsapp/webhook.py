"""Verifica e parsing dei webhook della WhatsApp Cloud API."""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from typing import Any


def verify_signature(app_secret: str, body: bytes, header: str | None) -> bool:
    """Controlla l'header X-Hub-Signature-256 ("sha256=<hmac hex del body con l'App Secret>")."""
    if not app_secret or not header or not header.startswith("sha256="):
        return False
    expected = hmac.new(app_secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header.removeprefix("sha256="))


@dataclass
class InboundEvent:
    message_id: str
    wa_id: str
    kind: str  # text | image | button | other
    text: str | None = None
    button_id: str | None = None
    media_id: str | None = None
    media_type: str | None = None


def parse_events(payload: dict[str, Any]) -> list[InboundEvent]:
    """Estrae i messaggi in arrivo; ignora le notifiche di stato (sent/delivered/read)."""
    events: list[InboundEvent] = []
    for entry in payload.get("entry") or []:
        for change in entry.get("changes") or []:
            value = change.get("value") or {}
            for m in value.get("messages") or []:
                mtype = m.get("type")
                ev = InboundEvent(message_id=m.get("id", ""), wa_id=m.get("from", ""), kind="other")
                if mtype == "text":
                    ev.kind, ev.text = "text", (m.get("text") or {}).get("body")
                elif mtype == "image":
                    img = m.get("image") or {}
                    ev.kind, ev.media_id, ev.media_type = "image", img.get("id"), img.get("mime_type")
                    ev.text = img.get("caption")
                elif mtype == "interactive":
                    inter = m.get("interactive") or {}
                    reply = inter.get("button_reply") or inter.get("list_reply") or {}
                    ev.kind, ev.button_id, ev.text = "button", reply.get("id"), reply.get("title")
                elif mtype == "button":  # risposta a un bottone di un template
                    ev.kind, ev.button_id = "button", (m.get("button") or {}).get("payload")
                    ev.text = (m.get("button") or {}).get("text")
                if ev.message_id and ev.wa_id:
                    events.append(ev)
    return events
