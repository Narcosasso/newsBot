"""Fixture comuni: catalogo TCGdex finto basato su risposte reali salvate in tests/fixtures/tcgdex."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

FIXTURES = Path(__file__).parent / "fixtures" / "tcgdex"


def load(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class FakeCatalog:
    """Stessa interfaccia di TCGdexCatalog; i file sono nominati come il path API (es. en_cards_sv03.5-006.json)."""

    def __init__(self, searches: dict[tuple[str, frozenset], str] | None = None) -> None:
        self.searches = searches or {}
        self.calls: list[str] = []

    def _file(self, path: str) -> Any:
        self.calls.append(path)
        f = FIXTURES / (path.replace("/", "_") + ".json")
        return json.loads(f.read_text(encoding="utf-8")) if f.exists() else None

    async def list_sets(self, lang: str) -> list[dict[str, Any]]:
        return self._file(f"{lang}/sets") or []

    async def get_set(self, lang: str, set_id: str) -> dict[str, Any] | None:
        return self._file(f"{lang}/sets/{set_id}")

    async def get_card(self, lang: str, card_id: str) -> dict[str, Any] | None:
        return self._file(f"{lang}/cards/{card_id}")

    async def search_sets(self, lang: str, filters: dict[str, str]) -> list[dict[str, Any]]:
        """Simula il filtro esatto abbreviation.official=eq:XXX sui dettagli dei set presenti nelle fixture."""
        self.calls.append(f"search_sets {lang} {sorted(filters.items())}")
        wanted = filters.get("abbreviation.official", "").removeprefix("eq:")
        out = []
        for f in sorted(FIXTURES.glob(f"{lang}_sets_*.json")):
            s = json.loads(f.read_text(encoding="utf-8"))
            if (s.get("abbreviation") or {}).get("official") == wanted:
                out.append({k: s[k] for k in ("id", "name", "cardCount") if k in s})
        return out

    async def search_cards(self, lang: str, filters: dict[str, str]) -> list[dict[str, Any]]:
        self.calls.append(f"search {lang} {sorted(filters.items())}")
        name = self.searches.get((lang, frozenset(filters.items())))
        return load(name) if name else []


CHARIZARD_FILTERS = frozenset({"dexId": "eq:6", "illustrator": "PLANETA Mochizuki", "hp": "eq:330"}.items())


@pytest.fixture
def catalog() -> FakeCatalog:
    return FakeCatalog(searches={
        ("ja", CHARIZARD_FILTERS): "search_ja_charizard.json",
        ("en", CHARIZARD_FILTERS): "search_en_charizard.json",
        ("en", frozenset({"name": "Charizard ex"}.items())): "search_en_name_charizard_ex.json",
    })
