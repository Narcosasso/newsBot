"""Regole di notifica (logica pura, senza I/O).

Si confronta il prezzo nuovo con il **valore di riferimento** (l'ultimo notificato, oppure quello mostrato quando
hai attivato le notifiche), non con la lettura del giorno prima: così tanti piccoli movimenti nella stessa
direzione, ognuno sotto soglia, prima o poi fanno scattare l'avviso invece di sfuggire per sempre.

L'avviso parte solo se la variazione supera TUTTE le soglie attive (default: almeno 10% e almeno 1 €), così le
carte da pochi centesimi non mandano notifiche per variazioni irrilevanti.
"""

from __future__ import annotations

from dataclasses import dataclass

from cardbot.prices.models import CardmarketQuote


@dataclass(frozen=True)
class Threshold:
    pct: float | None = 10.0   # variazione minima in %, None = non considerata
    eur: float | None = 1.0    # variazione minima in euro, None = non considerata

    def describe(self) -> str:
        parts = []
        if self.pct is not None:
            parts.append(f"{self.pct:g}%".replace(".", ","))
        if self.eur is not None:
            parts.append(f"{self.eur:.2f} €".replace(".", ","))
        return " e ".join(parts) if parts else "qualsiasi variazione"


@dataclass(frozen=True)
class Change:
    old: float
    new: float

    @property
    def delta(self) -> float:
        return self.new - self.old

    @property
    def pct(self) -> float | None:
        return self.delta / self.old * 100 if self.old else None


def effective_threshold(user, tracking) -> Threshold:
    """La soglia della singola carta, se impostata, vince su quella generale dell'utente."""
    if tracking.threshold_custom:
        return Threshold(pct=tracking.threshold_pct, eur=tracking.threshold_eur)
    return Threshold(pct=user.threshold_pct, eur=user.threshold_eur)


def metric(quote: CardmarketQuote | None) -> float | None:
    """Il valore sorvegliato: il trend Cardmarket; se manca, la media a 7 giorni, poi la media vendite."""
    if quote is None:
        return None
    for value in (quote.trend, quote.avg7, quote.avg):
        if value:
            return round(value, 2)
    return None


def evaluate(baseline: float | None, current: float | None, threshold: Threshold) -> Change | None:
    """La variazione da notificare, oppure None."""
    if baseline is None or current is None or baseline <= 0:
        return None
    change = Change(old=baseline, new=current)
    if change.delta == 0:
        return None
    if threshold.pct is not None and abs(change.pct or 0) < threshold.pct:
        return None
    if threshold.eur is not None and abs(change.delta) < threshold.eur:
        return None
    return change
