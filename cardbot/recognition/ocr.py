"""Lettura delle foto con Google Cloud Vision (riconoscimento del testo): gratis fino a 1.000 foto al mese.

Il servizio restituisce tutto il testo stampato sulla carta; qui ne estraiamo nome, codice set, numero e lingua,
poi la carta si cerca nel catalogo con lo stesso matcher della ricerca testuale.

Autenticazione:
- su Cloud Run: token del service account dal metadata server, nessuna chiave da configurare;
- in locale: GOOGLE_VISION_API_KEY (chiave API con Cloud Vision abilitata).
"""

from __future__ import annotations

import base64
import logging
import re
import time

import httpx

from cardbot.recognition.vision import VisionError, VisionResult

log = logging.getLogger(__name__)

ANNOTATE_URL = "https://vision.googleapis.com/v1/images:annotate"
METADATA_TOKEN_URL = ("http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token")

# Sigla della lingua stampata accanto al numero nelle carte recenti (es. "MEW EN 006/165").
LANG_TOKENS = {"EN": "en", "IT": "it", "DE": "de", "FR": "fr", "ES": "es", "PT": "pt"}
# Parole tipiche di ogni lingua (debolezza, resistenza, ritirata…), per le carte senza sigla.
LANG_WORDS = {
    "it": ("debolezza", "resistenza", "ritirata", "evoluzione", "si evolve", "fase", "allenatore", "strumento"),
    "de": ("schwäche", "resistenz", "rückzug", "phase", "entwickelt sich", "trainer"),
    "fr": ("faiblesse", "résistance", "retraite", "niveau", "évolue de", "dresseur"),
    "es": ("debilidad", "resistencia", "retirada", "fase", "evoluciona de", "entrenador"),
    "pt": ("fraqueza", "resistência", "recuo", "estágio", "evolui de", "treinador"),
    "en": ("weakness", "resistance", "retreat", "stage", "evolves from", "trainer", "basic"),
}
# Righe da saltare quando si cerca il nome (stadio, PS, intestazioni).
SKIP_LINE = re.compile(
    r"^(basic|base|basico|básico|stage\s*\d|fase\s*\d|phase\s*\d|niveau\s*\d|estágio\s*\d|stadio\s*\d|"
    r"evolves from|si evolve da|entwickelt sich aus|évolue de|evoluciona de|evolui de|"
    r"trainer|allenatore|pokémon|pokemon|tera|mega|break|v\s*union)\b",
    re.IGNORECASE,
)
HP_RE = re.compile(r"\b(?:HP|PS|PV|KP)\s*\d{2,3}\b|\b\d{2,3}\s*(?:HP|PS|PV|KP)\b", re.IGNORECASE)
NUMBER_RE = re.compile(r"(?<![\w/])([A-Z]{0,3}\d{1,3}[a-z]?)\s*/\s*([A-Z]{0,3}\d{1,3})(?![\w/])")
CODE_RE = re.compile(r"^(?:[A-Z]{2,4}|[A-Z]{1,3}\d{1,2}[a-zA-Z]?|\d{2}[A-Z])$")
RARITIES = {"C", "U", "R", "RR", "RRR", "SR", "SAR", "AR", "UR", "HR", "CHR", "CSR", "SSR", "PR", "TR", "MA", "BWR",
            "ACE", "MUR", "IR", "SIR"}
NOT_CODES = {"HP", "PS", "PV", "KP", "EX", "GX", "VMAX", "VSTAR", "LV", "TM", "TG", "GG", "SV", "SWSH", "SM", "XY",
             "BREAK", "SPEC", "STAGE", "BASIC", "BASE", "FASE", "GAME", "FREAK", "TCG"} | set(LANG_TOKENS) | RARITIES
JAPANESE = re.compile(r"[぀-ヿ一-鿿]")
KOREAN = re.compile(r"[가-힯]")


def parse_card_text(text: str) -> VisionResult:
    """Dal testo riconosciuto ai dati della carta (funzione pura, testabile senza servizi esterni)."""
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if not lines:
        return VisionResult(is_pokemon_card=False, language="other", confidence=0.0)

    # Numero di collezione: l'ultimo "x/y" del testo (in basso sulla carta).
    number = total = None
    number_line = None
    for i, line in enumerate(lines):
        for m in NUMBER_RE.finditer(line):
            number, total, number_line = m.group(1), m.group(2), i
    # Codice set e sigla della lingua: sulla stessa riga del numero o su quelle accanto.
    set_code = lang_token = None
    if number_line is not None:
        # Prima la riga del numero, poi quella sopra e quella sotto.
        order = [number_line] + [i for i in (number_line - 1, number_line + 1) if 0 <= i < len(lines)]
        for line in (lines[i] for i in order):
            for tok in re.split(r"[\s•·|]+", NUMBER_RE.sub(" ", line)):
                tok = tok.strip(".,:;()[]")
                if tok.upper() in LANG_TOKENS and lang_token is None and tok.isupper():
                    lang_token = LANG_TOKENS[tok.upper()]
                elif set_code is None and CODE_RE.match(tok) and tok.upper() not in NOT_CODES:
                    set_code = tok

    language = _language(text, lang_token)
    name = _name(lines)
    pokemonish = bool(HP_RE.search(text) or re.search(r"pok[ée]mon|ポケモン|포켓몬", text, re.IGNORECASE))
    is_card = bool(number) or (bool(name) and pokemonish)
    confidence = 0.85 if (number and set_code) else 0.7 if number else 0.4
    return VisionResult(
        is_pokemon_card=is_card, language=language, name=name, set_code=set_code, number=number,
        set_total=total, variant_hint="unknown", is_promo=bool(re.search(r"\bpromo\b", text, re.IGNORECASE)),
        confidence=confidence if is_card else 0.0,
    )


def _language(text: str, lang_token: str | None) -> str:
    if JAPANESE.search(text):
        return "ja"
    if KOREAN.search(text):
        return "ko"
    if lang_token:
        return lang_token
    low = text.lower()
    scores = {lang: sum(low.count(w) for w in words) for lang, words in LANG_WORDS.items()}
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else "en"


def _name(lines: list[str]) -> str | None:
    for line in lines[:8]:
        clean = HP_RE.sub(" ", line)
        clean = re.sub(r"\s+", " ", clean).strip(" .,-")
        if SKIP_LINE.match(clean) or NUMBER_RE.search(clean):
            continue
        letters = re.sub(r"[^A-Za-zÀ-ÿ぀-ヿ一-鿿가-힯]", "", clean)
        if len(letters) >= 3:
            return clean
    return None


class GoogleVisionReader:
    """Stessa interfaccia di CardVision (read_card), ma con l'OCR gratuito di Google Cloud Vision."""

    enabled = True

    def __init__(self, api_key: str = "", client: httpx.AsyncClient | None = None) -> None:
        self._api_key = api_key
        self._http = client or httpx.AsyncClient(timeout=30.0)
        self._token: tuple[float, str] | None = None

    async def _auth(self) -> tuple[dict[str, str], dict[str, str]]:
        if self._api_key:
            return {}, {"key": self._api_key}
        if self._token and self._token[0] > time.monotonic():
            return {"Authorization": f"Bearer {self._token[1]}"}, {}
        try:
            resp = await self._http.get(METADATA_TOKEN_URL, headers={"Metadata-Flavor": "Google"}, timeout=5.0)
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise VisionError("Lettura delle foto non configurata") from exc
        data = resp.json()
        self._token = (time.monotonic() + max(int(data.get("expires_in", 300)) - 60, 30), data["access_token"])
        return {"Authorization": f"Bearer {self._token[1]}"}, {}

    async def read_card(self, image: bytes, media_type: str = "image/jpeg") -> VisionResult:
        headers, params = await self._auth()
        body = {"requests": [{
            "image": {"content": base64.standard_b64encode(image).decode("ascii")},
            "features": [{"type": "TEXT_DETECTION"}],
            "imageContext": {"languageHints": ["en", "it", "ja"]},
        }]}
        try:
            resp = await self._http.post(ANNOTATE_URL, json=body, headers=headers, params=params)
        except httpx.HTTPError as exc:
            raise VisionError("Il servizio che legge le foto non risponde, riprova tra poco") from exc
        if resp.status_code >= 400:
            log.error("Google Vision errore %s: %s", resp.status_code, resp.text[:300])
            raise VisionError("Il servizio che legge le foto ha dato un errore, riprova tra poco")
        result = (resp.json().get("responses") or [{}])[0]
        if "error" in result:
            log.error("Google Vision errore: %s", result["error"])
            raise VisionError("Non sono riuscito a leggere questa foto")
        text = (result.get("fullTextAnnotation") or {}).get("text") or ""
        return parse_card_text(text)
