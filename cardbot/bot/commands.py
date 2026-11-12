"""Comandi di gestione via chat (parsing puro, senza I/O).

  lista                       carte che segui
  stop <n> | stop tutte       smetti di seguire la carta n (o tutte)
  lingue <n> ita, jap         cambia le lingue della carta n
  soglia                      mostra la soglia attuale
  soglia 15% | 2€ | 15% 2€    soglia generale (0% o 0€ disattiva quella condizione)
  soglia <n> 20%              soglia solo per la carta n
  soglia <n> predefinita      la carta n torna alla soglia generale
  aiuto                       guida
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from cardbot.langs import parse_langs

LIST_WORDS = {"lista", "elenco", "carte", "tracciate", "seguite"}
HELP_WORDS = {"aiuto", "help", "?", "comandi", "start", "ciao"}
RESET_WORDS = {"predefinita", "default", "generale", "reset"}
ALL_WORDS = {"tutte", "tutto", "tutti", "all"}

_PCT = re.compile(r"^(\d+(?:[.,]\d+)?)\s*%$")
_EUR = re.compile(r"^(?:€\s*)?(\d+(?:[.,]\d+)?)\s*(?:€|eur|euro)$|^€\s*(\d+(?:[.,]\d+)?)$")


@dataclass
class Command:
    kind: str  # list | stop | langs | threshold_show | threshold | help | supported_langs | error
    index: int | None = None
    all: bool = False
    langs: list[str] = field(default_factory=list)
    pct: float | None = None
    eur: float | None = None
    set_pct: bool = False      # la percentuale è stata indicata (anche 0 = disattiva)
    set_eur: bool = False
    reset: bool = False
    error: str | None = None


def _num(value: str) -> float:
    return float(value.replace(",", "."))


def _merge_unit_tokens(tokens: list[str]) -> list[str]:
    """'15 %' -> '15%', '2 €' -> '2€', '2 euro' -> '2euro'."""
    out: list[str] = []
    for tok in tokens:
        if out and tok.lower() in {"%", "€", "eur", "euro"} and re.fullmatch(r"\d+(?:[.,]\d+)?", out[-1]):
            out[-1] += tok
        else:
            out.append(tok)
    return out


def parse_command(text: str) -> Command | None:
    """Il comando riconosciuto, oppure None se il testo non è un comando (es. una ricerca "MEW 006")."""
    tokens = _merge_unit_tokens(text.strip().split())
    if not tokens:
        return None
    head, rest = tokens[0].lower(), tokens[1:]

    if head in HELP_WORDS and not rest:
        return Command("help")
    if head in LIST_WORDS and not rest:
        return Command("list")

    if head == "stop":
        if not rest:
            return Command("error", error="Quale carta? Scrivi *stop* seguito dal numero, es. *stop 1* "
                                          "(numeri in *lista*), oppure *stop tutte*.")
        if rest[0].lower() in ALL_WORDS:
            return Command("stop", all=True)
        if rest[0].isdigit():
            return Command("stop", index=int(rest[0]))
        return None

    if head == "lingue":
        if not rest:
            return Command("supported_langs")
        index = int(rest[0]) if rest[0].isdigit() else None
        parsed = parse_langs(" ".join(rest[1:] if index is not None else rest))
        if not parsed.ok:
            unknown = f" Non conosco: {', '.join(parsed.unknown)}." if parsed.unknown else ""
            return Command("error", error=f"Lingue non valide.{unknown} Esempio: *lingue 1 ita, jap*.")
        return Command("langs", index=index, langs=parsed.langs)

    if head == "soglia":
        cmd = Command("threshold")
        args = rest
        if args and args[0].isdigit():
            cmd.index = int(args[0])
            args = args[1:]
        if not args:
            return Command("threshold_show") if cmd.index is None else Command(
                "error", error="Indica la soglia, es. *soglia 1 20%*, *soglia 1 2€* o *soglia 1 predefinita*.")
        for arg in args:
            low = arg.lower()
            if low in RESET_WORDS:
                cmd.reset = True
            elif m := _PCT.match(low):
                cmd.pct, cmd.set_pct = _num(m.group(1)), True
            elif m := _EUR.match(low):
                cmd.eur, cmd.set_eur = _num(m.group(1) or m.group(2)), True
            else:
                return Command("error", error="Soglia non valida. Esempi: *soglia 15%*, *soglia 2€*, "
                                              "*soglia 15% 2€*, *soglia 1 20%* (solo la carta 1).")
        if cmd.reset and cmd.index is None:
            return Command("error", error="Per la soglia generale indica un valore, es. *soglia 10% 1€*.")
        if (cmd.set_pct and cmd.pct > 1000) or (cmd.set_eur and cmd.eur > 100000):
            return Command("error", error="Valore di soglia troppo alto.")
        # 0 disattiva la condizione.
        if cmd.set_pct and cmd.pct == 0:
            cmd.pct = None
        if cmd.set_eur and cmd.eur == 0:
            cmd.eur = None
        return cmd

    return None
