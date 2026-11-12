"""Client minimale per la WhatsApp Cloud API (Graph API di Meta)."""

from __future__ import annotations

import logging

import httpx

log = logging.getLogger(__name__)

GRAPH = "https://graph.facebook.com"
MAX_BUTTON_TITLE = 20
MAX_BODY = 1024
MAX_TEXT = 4096


class WhatsAppError(RuntimeError):
    pass


class WhatsAppClient:
    def __init__(self, token: str, phone_number_id: str, api_version: str = "v24.0",
                 client: httpx.AsyncClient | None = None) -> None:
        self._token = token
        self._phone_id = phone_number_id
        self._base = f"{GRAPH}/{api_version}"
        self._http = client or httpx.AsyncClient(timeout=30.0)

    @property
    def _auth(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._token}"}

    async def _post_message(self, payload: dict) -> str | None:
        body = {"messaging_product": "whatsapp", "recipient_type": "individual", **payload}
        resp = await self._http.post(f"{self._base}/{self._phone_id}/messages", json=body, headers=self._auth)
        if resp.status_code >= 400:
            log.error("WhatsApp send error %s: %s", resp.status_code, resp.text[:500])
            raise WhatsAppError(f"Invio fallito ({resp.status_code})")
        messages = resp.json().get("messages") or [{}]
        return messages[0].get("id")  # wamid, utile per l'idempotenza delle notifiche

    async def send_text(self, to: str, text: str) -> None:
        for chunk in _chunks(text, MAX_TEXT):
            await self._post_message({"to": to, "type": "text", "text": {"body": chunk, "preview_url": False}})

    async def send_buttons(self, to: str, body: str, buttons: list[tuple[str, str]]) -> None:
        if not buttons:
            await self.send_text(to, body)
            return
        await self._post_message({
            "to": to,
            "type": "interactive",
            "interactive": {
                "type": "button",
                "body": {"text": body[:MAX_BODY]},
                "action": {"buttons": [
                    {"type": "reply", "reply": {"id": bid, "title": title[:MAX_BUTTON_TITLE]}}
                    for bid, title in buttons[:3]
                ]},
            },
        })

    async def download_media(self, media_id: str) -> tuple[bytes, str]:
        meta = await self._http.get(f"{self._base}/{media_id}", headers=self._auth)
        meta.raise_for_status()
        info = meta.json()
        data = await self._http.get(info["url"], headers=self._auth)
        data.raise_for_status()
        return data.content, info.get("mime_type", "image/jpeg")


def _chunks(text: str, size: int) -> list[str]:
    if len(text) <= size:
        return [text]
    out, current = [], ""
    for line in text.split("\n"):
        if len(current) + len(line) + 1 > size and current:
            out.append(current)
            current = ""
        current = f"{current}\n{line}" if current else line
    if current:
        out.append(current)
    return out
