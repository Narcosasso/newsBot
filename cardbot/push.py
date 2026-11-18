"""Notifiche push dell'app PokeVault (Web Push con chiavi VAPID).

Su iPhone funzionano con l'app aggiunta alla schermata Home (iOS 16.4 o successivo), dopo che hai toccato
"Attiva notifiche" nell'app. Le chiavi VAPID (che firmano le notifiche) si creano da sole al primo uso e restano
nel database; in alternativa si possono fissare con VAPID_PUBLIC_KEY / VAPID_PRIVATE_KEY.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass

from cryptography.hazmat.primitives import serialization
from py_vapid import Vapid02, b64urlencode
from pywebpush import WebPushException, webpush
from sqlalchemy.orm import Session, sessionmaker

from cardbot.db import JobState, PushSubscription, utcnow

log = logging.getLogger(__name__)
STATE_KEY = "vapid"
DEFAULT_SUBJECT = "mailto:pokevault@example.com"


@dataclass
class VapidKeys:
    public_key: str   # da dare al browser (applicationServerKey)
    private_key: str  # base64url del valore privato P-256


def generate_keys() -> VapidKeys:
    v = Vapid02()
    v.generate_keys()
    raw = v.private_key.private_numbers().private_value.to_bytes(32, "big")
    pub = v.public_key.public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    return VapidKeys(public_key=b64urlencode(pub), private_key=b64urlencode(raw))


def load_keys(session: Session, public_key: str = "", private_key: str = "") -> VapidKeys:
    """Chiavi dalla configurazione, altrimenti dal database (create e salvate la prima volta)."""
    if public_key and private_key:
        return VapidKeys(public_key, private_key)
    state = session.get(JobState, STATE_KEY)
    if state is not None and (state.value or {}).get("private_key"):
        return VapidKeys(state.value["public_key"], state.value["private_key"])
    keys = generate_keys()
    session.merge(JobState(key=STATE_KEY, value={"public_key": keys.public_key, "private_key": keys.private_key}))
    session.commit()
    return keys


class PushSender:
    def __init__(self, sessions: sessionmaker[Session], subject: str = DEFAULT_SUBJECT,
                 public_key: str = "", private_key: str = "") -> None:
        self._sessions = sessions
        self._subject = subject or DEFAULT_SUBJECT
        self._configured = (public_key, private_key)

    def keys(self) -> VapidKeys:
        with self._sessions() as session:
            return load_keys(session, *self._configured)

    def has_subscriptions(self, user_id: int) -> bool:
        with self._sessions() as session:
            return session.query(PushSubscription).filter_by(user_id=user_id).count() > 0

    async def send_to_user(self, user_id: int, title: str, body: str, url: str = "/#/collection",
                           tag: str = "prezzi") -> int:
        """Invia a tutti i dispositivi dell'utente. Restituisce quanti l'hanno ricevuta."""
        keys = self.keys()
        vapid = Vapid02.from_raw(keys.private_key.encode())
        payload = json.dumps({"title": title, "body": body, "url": url, "tag": tag})
        delivered = 0
        with self._sessions() as session:
            subs = session.query(PushSubscription).filter_by(user_id=user_id).all()
            for sub in subs:
                info = {"endpoint": sub.endpoint, "keys": {"p256dh": sub.p256dh, "auth": sub.auth}}
                try:
                    await asyncio.to_thread(webpush, info, payload, vapid_private_key=vapid,
                                            vapid_claims={"sub": self._subject}, ttl=24 * 3600, timeout=15)
                except WebPushException as exc:
                    status = getattr(exc.response, "status_code", None)
                    if status in (404, 410):  # iscrizione scaduta o revocata: si elimina
                        session.delete(sub)
                    else:
                        sub.failures += 1
                        log.warning("Push non consegnata (%s): %s", status, exc)
                    continue
                except Exception as exc:  # rete: si riprova al prossimo giro
                    sub.failures += 1
                    log.warning("Push non consegnata: %s", exc)
                    continue
                sub.last_ok_at, sub.failures = utcnow(), 0
                delivered += 1
            session.commit()
        return delivered
