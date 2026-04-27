import os
import sys
import requests
import pytz
from datetime import datetime

# --- Config ---
TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
GNEWS_API_KEY = os.environ["GNEWS_API_KEY"]

GNEWS_TOP = "https://gnews.io/api/v4/top-headlines"
GNEWS_SEARCH = "https://gnews.io/api/v4/search"
TELEGRAM_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"

ITALY_TZ = pytz.timezone("Europe/Rome")
TARGET_TIMES = [(8, 0), (10, 30), (20, 30)]
TIME_WINDOW = 25

GIORNI_IT = ["Lunedi", "Martedi", "Mercoledi", "Giovedi", "Venerdi", "Sabato", "Domenica"]
MESI_IT = ["", "Gennaio", "Febbraio", "Marzo", "Aprile", "Maggio", "Giugno",
           "Luglio", "Agosto", "Settembre", "Ottobre", "Novembre", "Dicembre"]

AI_MODELS_QUERY = (
    "GPT OR Claude OR Gemini OR Llama OR Qwen OR Mistral OR "
    "Grok OR DeepSeek OR Phi OR Copilot OR \"nuovo modello\" OR \"modello AI\""
)


def is_scheduled_time() -> bool:
    now = datetime.now(ITALY_TZ)
    current_minutes = now.hour * 60 + now.minute
    for hour, minute in TARGET_TIMES:
        if abs(current_minutes - (hour * 60 + minute)) <= TIME_WINDOW:
            return True
    return False


def _fetch(url: str, params: dict) -> list[dict]:
    import time
    time.sleep(1)  # evita rate limiting tra chiamate consecutive
    resp = requests.get(url, params=params, timeout=15)
    if resp.status_code == 429:
        print(f"Rate limit GNews raggiunto ({url}), sezione saltata.")
        return []
    resp.raise_for_status()
    return resp.json().get("articles", [])


def get_top_headlines(topic: str, max_results: int = 4, lang: str = None) -> list[dict]:
    params = {
        "token": GNEWS_API_KEY,
        "topic": topic,
        "max": max_results,
    }
    if lang:
        params["lang"] = lang
    return _fetch(GNEWS_TOP, params)


def get_search_news(query: str, max_results: int = 4, lang: str = None) -> list[dict]:
    params = {
        "token": GNEWS_API_KEY,
        "q": query,
        "max": max_results,
        "sortby": "publishedAt",
    }
    if lang:
        params["lang"] = lang
    return _fetch(GNEWS_SEARCH, params)


def escape_md(text: str) -> str:
    special = r"_*[]()~`>#+-=|{}.!"
    return "".join(f"\\{c}" if c in special else c for c in text)


def format_section(emoji: str, titolo: str, articles: list[dict]) -> str:
    numeri = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣"]
    lines = [f"{emoji} *{titolo}*", ""]
    if not articles:
        lines.append("_Nessuna novita' al momento_")
    else:
        for i, article in enumerate(articles):
            title = article["title"]
            url = article["url"]
            source = article.get("source", {}).get("name", "")
            source_str = f" \\({escape_md(source)}\\)" if source else ""
            num = numeri[i] if i < len(numeri) else f"{i+1}\\."
            lines.append(f"{num} [{escape_md(title)}]({url}){source_str}")
    lines.append("")
    return "\n".join(lines)


def build_message() -> str:
    now = datetime.now(ITALY_TZ)
    giorno = GIORNI_IT[now.weekday()]
    data_str = f"{giorno} {now.day} {MESI_IT[now.month]} {now.year}"
    ora_str = now.strftime("%H:%M")

    world  = get_top_headlines(topic="world", max_results=4)
    tech   = get_top_headlines(topic="technology", max_results=4)
    models = get_search_news(query=AI_MODELS_QUERY, max_results=4)
    seriea = get_search_news(query="Serie A", max_results=4, lang="it")

    sep = "〰️〰️〰️〰️〰️〰️〰️〰️〰️\n\n"

    msg  = "🗞 *IL PUNTO DEL GIORNO*\n"
    msg += f"📅 {escape_md(data_str)} · 🕐 {escape_md(ora_str)}\n\n"
    msg += sep
    msg += format_section("🌍", "NOTIZIE DAL MONDO", world)
    msg += sep
    msg += format_section("🤖", "AI & TECNOLOGIA", tech)
    msg += sep
    msg += format_section("🧠", "NUOVI MODELLI AI / LLM", models)
    msg += sep
    msg += format_section("⚽", "SERIE A", seriea)
    msg += "〰️〰️〰️〰️〰️〰️〰️〰️〰️\n"
    msg += "📲 _Buona lettura\\!_"

    return msg


def send_message(text: str) -> None:
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "MarkdownV2",
        "disable_web_page_preview": True,
    }
    resp = requests.post(TELEGRAM_URL, json=payload, timeout=15)
    resp.raise_for_status()
    result = resp.json()
    if not result.get("ok"):
        raise RuntimeError(f"Telegram error: {result}")
    print("Messaggio inviato con successo.")


def main():
    force = "--force" in sys.argv

    if not force and not is_scheduled_time():
        now = datetime.now(ITALY_TZ)
        print(f"Fuori orario: ora italiana {now.strftime('%H:%M')}, nessun invio.")
        return

    print("Recupero notizie...")
    message = build_message()
    print("Invio messaggio Telegram...")
    send_message(message)


if __name__ == "__main__":
    main()
