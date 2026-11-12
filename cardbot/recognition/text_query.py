"""Ricerca senza foto: interpreta testi come "MEW 006", "SV2a 006/165 jap", "Charizard ex MEW 6 reverse".

Regole (in ordine di priorità per ogni parola):
- "006/165" o "TG05/TG30": numero e totale del set
- solo cifre ("006", "6"): numero (cifre+lettere come "30C" sono un codice set)
- lingua ("ita", "jap", …): lingue per cui mostrare i prezzi
- variante ("reverse", "holo", "normale")
- lettere+cifre ("SV2a", "S12a", "sv03.5", "TG05"): codice set se non c'è ancora, altrimenti numero
- tutto maiuscolo di 2-5 lettere ("MEW", "PAL", "SVP"): codice set
- il resto: nome della carta
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from cardbot.langs import parse_langs

VARIANT_WORDS = {"reverse": "reverse", "rev": "reverse", "holo": "holo", "olografica": "holo",
                 "normale": "normal", "normal": "normal"}
_SLASH = re.compile(r"^([A-Za-z]{0,3}\d{1,3}[A-Za-z]?)/([A-Za-z]{0,3}\d{1,3})$")
# Solo cifre: "30C" è un codice set (30th Celebration), non il numero 30 con una lettera.
_DIGITS = re.compile(r"^\d{1,3}$")
_MIXED = re.compile(r"^(?=.*\d)(?=.*[A-Za-z])[A-Za-z0-9.\-]{2,8}$")
_UPPER = re.compile(r"^[A-Z]{2,5}$")


@dataclass
class TextQuery:
    name: str | None = None
    set_code: str | None = None
    number: str | None = None
    set_total: str | None = None
    langs: list[str] = field(default_factory=list)
    variant: str | None = None

    @property
    def is_specific(self) -> bool:
        """Abbastanza informazioni per interrompere una conversazione in corso e iniziare una nuova ricerca."""
        return bool(self.number and (self.set_code or self.name))


def parse_query(text: str) -> TextQuery | None:
    q = TextQuery()
    name_words: list[str] = []
    for raw in re.split(r"[\s,;]+", text.strip()):
        tok = raw.strip(".!?()[]#")
        if not tok:
            continue
        low = tok.lower()
        if m := _SLASH.match(tok):
            q.number, q.set_total = m.group(1), re.sub(r"^[A-Za-z]+", "", m.group(2))
        elif _DIGITS.match(tok) and not q.number:
            q.number = tok
        elif low in VARIANT_WORDS:
            q.variant = VARIANT_WORDS[low]
        elif (lang := parse_langs(low)).ok:
            q.langs += [x for x in lang.langs if x not in q.langs]
        elif _MIXED.match(tok):
            if q.set_code is None:
                q.set_code = tok
            elif not q.number:
                q.number = tok
            else:
                name_words.append(tok)
        elif _UPPER.match(tok) and q.set_code is None:
            q.set_code = tok
        else:
            name_words.append(tok)
    q.name = " ".join(name_words) or None
    if not q.number and not q.name:
        return None
    return q
