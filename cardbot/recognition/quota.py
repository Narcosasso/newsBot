"""Tetto mensile alle letture delle foto con Google Cloud Vision.

Google regala 1.000 letture al mese; oltre si pagano. Lo scanner dal vivo può farne molte in poco tempo, quindi
contiamo ogni lettura (app e bot WhatsApp insieme) e ci fermiamo a VISION_MONTHLY_LIMIT (950 di default).
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session, sessionmaker

from cardbot.db import JobState
from cardbot.recognition.vision import VisionError

ROME = ZoneInfo("Europe/Rome")


def _key(now: datetime | None = None) -> str:
    # Google azzera la quota il primo del mese (ora del Pacifico): Roma va bene, con il margine delle 50 letture.
    return "vision_usage:" + (now or datetime.now(ROME)).strftime("%Y-%m")


def usage(session: Session) -> int:
    row = session.get(JobState, _key())
    return int((row.value or {}).get("count", 0)) if row else 0


class QuotaReader:
    """Avvolge il lettore delle foto: conta le letture e blocca quando si raggiunge il tetto mensile."""

    def __init__(self, inner, sessions: sessionmaker[Session], limit: int) -> None:
        self._inner = inner
        self._sessions = sessions
        self.limit = limit

    @property
    def enabled(self) -> bool:
        return getattr(self._inner, "enabled", True)

    def used(self) -> int:
        with self._sessions() as session:
            return usage(session)

    async def read_card(self, image: bytes, media_type: str = "image/jpeg"):
        with self._sessions() as session:
            if usage(session) >= self.limit:
                raise VisionError(f"Raggiunte le {self.limit} letture di foto di questo mese (gratis fino a "
                                  "1.000): riprendono il primo del mese. Intanto scrivi codice e numero della carta.")
            key = _key()
            row = session.get(JobState, key) or JobState(key=key, value={"count": 0})
            row.value = {"count": int((row.value or {}).get("count", 0)) + 1}
            session.merge(row)
            session.commit()
        return await self._inner.read_card(image, media_type)


def user_key(user_id: int) -> str:
    return f"{_key()}:u{user_id}"


def user_usage(session: Session, user_id: int) -> int:
    row = session.get(JobState, user_key(user_id))
    return int((row.value or {}).get("count", 0)) if row else 0


def bump_user(session: Session, user_id: int) -> None:
    key = user_key(user_id)
    row = session.get(JobState, key) or JobState(key=key, value={"count": 0})
    row.value = {"count": int((row.value or {}).get("count", 0)) + 1}
    session.merge(row)
    session.commit()
