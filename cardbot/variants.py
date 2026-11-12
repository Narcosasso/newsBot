"""Varianti di stampa (normale / holo / reverse) così come le espone TCGdex, anche nei cataloghi localizzati."""

from __future__ import annotations

from typing import Any

LABELS_IT = {"normal": "Normale", "holo": "Holo", "reverse": "Reverse holo"}

_ALIASES = {
    "normal": "normal", "normale": "normal", "holo": "holo", "olografica": "holo", "holofoil": "holo",
    "reverse": "reverse", "reverse holo": "reverse", "reverse olografica": "reverse",
}


def variant_type(raw: str) -> str | None:
    return _ALIASES.get(raw.strip().lower())


def variants_of(card: dict[str, Any]) -> list[str]:
    """Varianti "base" della carta, senza timbri o foil speciali (es. Poké Ball, Cosmo)."""
    out: list[str] = []
    for v in card.get("variants_detailed") or []:
        t = variant_type(v.get("type", ""))
        if t and t not in out and not v.get("stamp") and not v.get("foil"):
            out.append(t)
    if not out:
        flags = card.get("variants") or {}
        out = [k for k in ("normal", "holo", "reverse") if flags.get(k)]
    return out


def variant_entry(card: dict[str, Any], variant: str) -> dict[str, Any] | None:
    entries = [v for v in card.get("variants_detailed") or [] if variant_type(v.get("type", "")) == variant]
    plain = [v for v in entries if not v.get("stamp") and not v.get("foil")]
    return (plain or entries or [None])[0]


def choose_variant(available: list[str], hint: str) -> str | None:
    """Variante da usare senza chiedere, oppure None se va chiesta all'utente."""
    if not available:
        return "normal"
    if len(available) == 1:
        return available[0]
    if hint in available:
        return hint
    return None
