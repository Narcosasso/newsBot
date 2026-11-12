"""Parsing delle lingue scritte dall'utente ("ita, eng, jap") in codici canonici."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# Codice canonico -> (etichetta breve, bandiera, alias accettati)
LANGS: dict[str, tuple[str, str, tuple[str, ...]]] = {
    "it": ("ITA", "🇮🇹", ("it", "ita", "italiano", "italiana", "italian")),
    "en": ("ENG", "🇬🇧", ("en", "eng", "inglese", "english", "ing", "uk", "us")),
    "ja": ("JAP", "🇯🇵", ("ja", "jp", "jap", "jpn", "giapponese", "japanese", "giap")),
    "ko": ("KOR", "🇰🇷", ("ko", "kr", "kor", "coreano", "coreana", "korean")),
    "de": ("DEU", "🇩🇪", ("de", "ger", "deu", "tedesco", "tedesca", "german")),
    "fr": ("FRA", "🇫🇷", ("fr", "fra", "fre", "francese", "french")),
    "es": ("SPA", "🇪🇸", ("es", "spa", "esp", "spagnolo", "spagnola", "spanish")),
    "pt": ("POR", "🇵🇹", ("pt", "por", "portoghese", "portuguese")),
    "zh": ("CIN", "🇨🇳", ("zh", "cn", "cin", "chi", "cinese", "chinese")),
}

_ALIAS = {alias: code for code, (_, _, aliases) in LANGS.items() for alias in aliases}

# Lingue stampate sulle carte "internazionali": su Cardmarket condividono lo stesso prodotto.
INTERNATIONAL = frozenset({"it", "en", "de", "fr", "es", "pt"})


@dataclass
class LangParseResult:
    langs: list[str] = field(default_factory=list)
    unknown: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return bool(self.langs) and not self.unknown


def parse_langs(text: str) -> LangParseResult:
    """Accetta separatori virgola, spazio, '/', ';', '+', 'e'. Mantiene l'ordine e rimuove i duplicati."""
    result = LangParseResult()
    tokens = [t for t in re.split(r"[\s,;/+|]+", text.strip().lower()) if t]
    for token in tokens:
        token = token.strip(".!?:()[]")
        if not token or token in {"e", "and", "&"}:
            continue
        code = _ALIAS.get(token)
        if code is None:
            result.unknown.append(token)
        elif code not in result.langs:
            result.langs.append(code)
    return result


def label(code: str) -> str:
    short, flag, _ = LANGS[code]
    return f"{flag} {short}"


def format_langs(codes: list[str]) -> str:
    return ", ".join(LANGS[c][0].lower() for c in codes)


def supported_help() -> str:
    return ", ".join(LANGS[c][0].lower() for c in LANGS)
