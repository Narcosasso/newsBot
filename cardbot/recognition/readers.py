"""Scelta del lettore delle foto in base alla configurazione (PHOTO_READER)."""

from __future__ import annotations

from cardbot.config import Settings
from cardbot.recognition.ocr import GoogleVisionReader
from cardbot.recognition.vision import CardVision, DisabledVision


def make_reader(settings: Settings) -> GoogleVisionReader | CardVision | DisabledVision:
    choice = (settings.photo_reader or "google").strip().lower()
    if choice == "off":
        return DisabledVision()
    if choice == "claude":
        if not settings.anthropic_api_key:
            return DisabledVision()
        return CardVision(settings.anthropic_api_key, settings.vision_model, settings.vision_effort)
    return GoogleVisionReader(api_key=settings.google_vision_api_key)
