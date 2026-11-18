"""Tetto mensile alle letture delle foto (Google Vision gratis fino a 1.000 al mese)."""

import pytest

from cardbot.db import make_engine, make_session_factory
from cardbot.recognition.quota import QuotaReader
from cardbot.recognition.vision import VisionError


class Inner:
    enabled = True

    def __init__(self):
        self.calls = 0

    async def read_card(self, image, media_type="image/jpeg"):
        self.calls += 1
        return "letta"


async def test_counts_and_stops_at_the_monthly_limit():
    sessions = make_session_factory(make_engine("sqlite://"))
    inner = Inner()
    reader = QuotaReader(inner, sessions, limit=2)
    assert await reader.read_card(b"x") == "letta" and await reader.read_card(b"x") == "letta"
    assert reader.used() == 2
    with pytest.raises(VisionError, match="2 letture"):
        await reader.read_card(b"x")
    assert inner.calls == 2 and reader.enabled
