"""Estrazione dei dati stampati sulla carta da una foto, con Claude vision e output JSON vincolato."""

from __future__ import annotations

import base64
import json
import logging
from typing import Literal

import anthropic
from pydantic import BaseModel, Field, ValidationError

log = logging.getLogger(__name__)

CardLang = Literal["en", "it", "fr", "de", "es", "pt", "ja", "ko", "zh", "other"]
VariantHint = Literal["normal", "holo", "reverse", "unknown"]


class VisionResult(BaseModel):
    is_pokemon_card: bool
    language: CardLang
    name: str | None = None
    set_code: str | None = Field(None, description="Codice set stampato, es. MEW, PAL, SV2a")
    number: str | None = Field(None, description="Numero di collezione, es. 006, TG05, SVP 123")
    set_total: str | None = Field(None, description="Totale dopo la barra, es. 165")
    regulation_mark: str | None = None
    rarity: str | None = None
    variant_hint: VariantHint = "unknown"
    is_promo: bool = False
    stamp: str | None = None
    confidence: float = 0.0
    notes: str | None = None


def _nullable(t: str) -> dict:
    return {"type": [t, "null"]}


SCHEMA = {
    "type": "object",
    "properties": {
        "is_pokemon_card": {"type": "boolean"},
        "language": {"type": "string", "enum": list(CardLang.__args__)},
        "name": _nullable("string"),
        "set_code": _nullable("string"),
        "number": _nullable("string"),
        "set_total": _nullable("string"),
        "regulation_mark": _nullable("string"),
        "rarity": _nullable("string"),
        "variant_hint": {"type": "string", "enum": list(VariantHint.__args__)},
        "is_promo": {"type": "boolean"},
        "stamp": _nullable("string"),
        "confidence": {"type": "number"},
        "notes": _nullable("string"),
    },
    "required": [
        "is_pokemon_card", "language", "name", "set_code", "number", "set_total", "regulation_mark",
        "rarity", "variant_hint", "is_promo", "stamp", "confidence", "notes",
    ],
    "additionalProperties": False,
}

SYSTEM_PROMPT = """Sei un esperto di carte del Pokémon Trading Card Game di ogni lingua ed epoca.
Ricevi la foto di una carta e trascrivi i dati stampati, senza indovinare ciò che non si legge.

- name: il nome come stampato sulla carta, nella sua lingua (es. "リザードンex", "Charizard-ex", "Glurak-ex").
- language: la lingua del testo stampato (ja per giapponese, ko per coreano, zh per cinese).
- set_code: il codice set stampato in basso a sinistra (es. "MEW", "PAL", "SV2a", "SV4a", "S12a"),
  null se non leggibile. Non dedurlo dal nome dell'espansione.
- number e set_total: dal numero di collezione, es. "006/165" -> number "006", set_total "165";
  per le promo (es. "SVP 123", "SV-P 045") metti tutto il codice in number e set_total null.
- regulation_mark: la lettera nel riquadro (es. "G", "H"), se presente.
- variant_hint: "reverse" se il riflesso olografico è sul resto della carta e non sull'illustrazione,
  "holo" se è sull'illustrazione o la carta è full art / illustrazione speciale, "normal" se non c'è riflesso,
  "unknown" se dalla foto non si capisce.
- stamp: eventuale timbro (es. "Pokémon Center", "Staff", logo del set), altrimenti null.
- confidence: da 0 a 1, quanto sei sicuro di name, set_code e number insieme.
- Se la foto non mostra una carta Pokémon, is_pokemon_card false e tutto il resto null o "unknown"."""

FALLBACK_BETA = "server-side-fallback-2026-07-01"


class VisionError(RuntimeError):
    pass


class CardVision:
    def __init__(self, api_key: str, model: str = "claude-opus-5-5", effort: str = "medium",
                 client: anthropic.AsyncAnthropic | None = None) -> None:
        self._client = client or anthropic.AsyncAnthropic(api_key=api_key or None)
        self._model = model
        self._effort = effort

    async def read_card(self, image: bytes, media_type: str = "image/jpeg") -> VisionResult:
        data = base64.standard_b64encode(image).decode("ascii")
        try:
            response = await self._client.beta.messages.create(
                model=self._model,
                max_tokens=4000,
                betas=[FALLBACK_BETA],
                fallbacks="default",  # se il modello rifiuta, il server ritenta con un modello di riserva
                system=SYSTEM_PROMPT,
                output_config={"effort": self._effort, "format": {"type": "json_schema", "schema": SCHEMA}},
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": data}},
                        {"type": "text", "text": "Trascrivi i dati di questa carta."},
                    ],
                }],
            )
        except anthropic.APIConnectionError as exc:
            raise VisionError("Servizio di riconoscimento non raggiungibile") from exc
        except anthropic.RateLimitError as exc:
            raise VisionError("Troppe richieste al servizio di riconoscimento, riprova tra poco") from exc
        except anthropic.APIStatusError as exc:
            log.error("Errore API vision %s: %s", exc.status_code, exc.message)
            raise VisionError("Errore del servizio di riconoscimento") from exc
        return parse_response(response)


class DisabledVision:
    """Usata quando ANTHROPIC_API_KEY non è configurata: il bot funziona solo con la ricerca testuale."""

    async def read_card(self, image: bytes, media_type: str = "image/jpeg") -> VisionResult:
        raise VisionError("Il riconoscimento delle foto non è attivo. Scrivi codice set e numero stampati in "
                          "basso sulla carta, es. *MEW 006* o *SV2a 006/165*")


def make_vision(api_key: str, model: str, effort: str) -> CardVision | DisabledVision:
    return CardVision(api_key, model, effort) if api_key else DisabledVision()


def parse_response(response) -> VisionResult:
    if response.stop_reason == "refusal":
        raise VisionError("Il servizio di riconoscimento non ha elaborato questa immagine")
    if response.stop_reason == "max_tokens":
        raise VisionError("Risposta del riconoscimento incompleta")
    text = next((b.text for b in response.content if getattr(b, "type", None) == "text"), None)
    if not text:
        raise VisionError("Risposta del riconoscimento vuota")
    try:
        return VisionResult.model_validate(json.loads(text))
    except (json.JSONDecodeError, ValidationError) as exc:
        raise VisionError("Risposta del riconoscimento non valida") from exc
