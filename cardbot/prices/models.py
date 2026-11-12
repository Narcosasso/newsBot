"""Quotazioni di prezzo e lettura dei campi Cardmarket / TCGplayer per una variante."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

CM_FIELDS = ("low", "trend", "avg", "avg1", "avg7", "avg30")
TCGPLAYER_KEYS = {"normal": "normal", "holo": "holofoil", "reverse": "reverse-holofoil"}


@dataclass
class CardmarketQuote:
    id_product: int | None
    low: float | None
    trend: float | None
    avg: float | None
    avg1: float | None
    avg7: float | None
    avg30: float | None
    updated: datetime | None
    currency: str = "EUR"

    @property
    def has_data(self) -> bool:
        return any(v for v in (self.low, self.trend, self.avg, self.avg7, self.avg30))

    @property
    def change_30d_pct(self) -> float | None:
        """Andamento: trend attuale rispetto alla media degli ultimi 30 giorni."""
        if self.trend and self.avg30:
            return (self.trend - self.avg30) / self.avg30 * 100
        return None

    @property
    def change_7d_pct(self) -> float | None:
        if self.trend and self.avg7:
            return (self.trend - self.avg7) / self.avg7 * 100
        return None


@dataclass
class TCGplayerQuote:
    market: float | None
    low: float | None
    updated: datetime | None
    currency: str = "USD"


@dataclass
class LangQuote:
    """Prezzo per una o più lingue che condividono lo stesso prodotto."""

    langs: list[str]
    card_id: str | None
    card_label: str | None
    cardmarket: CardmarketQuote | None = None
    tcgplayer: TCGplayerQuote | None = None
    aggregated: bool = False       # True: prezzo Cardmarket unico per più lingue
    estimated_equivalent: bool = False
    notes: list[str] = field(default_factory=list)


def _f(value: Any) -> float | None:
    if value is None:
        return None
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    return v


def parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def cardmarket_quote(pricing: dict[str, Any] | None, variant: str, shared_product: bool) -> CardmarketQuote | None:
    """Legge i campi Cardmarket per la variante.

    Su Cardmarket i prezzi della reverse holo stanno nei campi "-holo" (anche quando la reverse ha un prodotto
    dedicato, es. le reverse "Cosmo"). Per le altre varianti valgono i campi base; i "-holo" solo se i base
    non hanno né trend né medie.
    """
    if not pricing:
        return None
    base = {k: _f(pricing.get(k)) for k in CM_FIELDS}
    holo = {k: _f(pricing.get(f"{k}-holo")) for k in CM_FIELDS}

    def has_core(d: dict[str, float | None]) -> bool:
        return any(d.get(k) for k in ("trend", "avg", "avg7", "avg30"))

    if variant == "reverse":
        chosen = holo if (has_core(holo) or shared_product) else base
    else:
        chosen = base if has_core(base) or not has_core(holo) else holo
    # Un trend a 0 significa "nessun dato", non un prezzo di 0 €.
    chosen = {k: (v if v else None) for k, v in chosen.items()}
    return CardmarketQuote(
        id_product=pricing.get("idProduct"),
        updated=parse_datetime(pricing.get("updated")),
        currency=pricing.get("unit") or "EUR",
        **chosen,
    )


def tcgplayer_quote(pricing: dict[str, Any] | None, variant: str) -> TCGplayerQuote | None:
    if not pricing:
        return None
    entry = pricing.get(TCGPLAYER_KEYS.get(variant, "normal"))
    if not isinstance(entry, dict):
        return None
    market, low = _f(entry.get("marketPrice")), _f(entry.get("lowPrice"))
    if not market and not low:
        return None
    return TCGplayerQuote(market=market, low=low, updated=parse_datetime(pricing.get("updated")),
                          currency=pricing.get("unit") or "USD")
