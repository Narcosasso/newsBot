"""Configurazione letta da variabili d'ambiente (vedi .env.example)."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- WhatsApp Cloud API ---
    whatsapp_token: str = ""
    whatsapp_phone_number_id: str = ""
    whatsapp_app_secret: str = ""
    whatsapp_verify_token: str = ""
    whatsapp_api_version: str = "v25.0"
    # Numeri autorizzati (formato wa_id, es. 393331234567), separati da virgola. Vuoto = nessun filtro.
    allowed_wa_ids: str = ""
    # Template "utility" approvato per le notifiche oltre la finestra di 24 ore (vedi README).
    whatsapp_alert_template: str = "price_alert"
    whatsapp_template_lang: str = "it"

    # --- Lettura delle foto ---
    # google: Google Cloud Vision, gratis fino a 1.000 foto/mese (su Cloud Run nessuna chiave da configurare)
    # claude: Claude vision (serve ANTHROPIC_API_KEY) · off: foto disattivate, solo ricerca testuale
    photo_reader: str = "google"
    google_vision_api_key: str = ""  # solo per provare in locale; su Cloud Run si usa il service account
    anthropic_api_key: str = ""
    # --- Prezzi PSA 10 (PokemonPriceTracker, piano gratuito: 100 crediti/giorno). Vuoto = niente PSA 10 ---
    pokemonpricetracker_api_key: str = ""
    vision_model: str = "claude-opus-5-5"
    vision_effort: str = "medium"

    # --- Dati ---
    database_url: str = "sqlite:///./cardbot.db"
    tcgdex_base_url: str = "https://api.tcgdex.net/v2"
    tcgdex_max_rps: float = 5.0
    cardmarket_price_guide_url: str = (
        "https://downloads.s3.cardmarket.com/productCatalog/priceGuide/price_guide_6.json"
    )

    # --- Bot ---
    default_langs: str = "ita,eng"
    timezone: str = "Europe/Rome"

    @property
    def allowed_wa_id_set(self) -> set[str]:
        return {x.strip().lstrip("+") for x in self.allowed_wa_ids.split(",") if x.strip()}


@lru_cache
def get_settings() -> Settings:
    return Settings()
