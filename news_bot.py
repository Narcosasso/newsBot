import os
import sys
import requests
import pytz
from datetime import datetime

# --- Config ---
TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
GUARDIAN_API_KEY = os.environ["GUARDIAN_API_KEY"]

GUARDIAN_URL = "https://content.guardianapis.com/search"
TELEGRAM_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"

ITALY_TZ = pytz.timezone("Europe/Rome")
TARGET_TIMES = [(8, 0), (10, 30), (20, 30)]
TIME_WINDOW = 25

GIORNI_IT = ["Lunedi", "Martedi", "Mercoledi", "Giovedi", "Venerdi", "Sabato", "Domenica"]
MESI_IT = ["", "Gennaio", "Febbraio", "Marzo", "Aprile", "Maggio", "Giugno",
           "Luglio", "Agosto", "Settembre", "Ottobre", "Novembre", "Dicembre"]


def is_scheduled_time() -> bool:
    now = datetime.now(ITALY_TZ)
    current_minutes = now.hour * 60 + now.minute
    for hour, minute in TARGET_TIMES:
        if abs(current_minutes - (hour * 60 + minute)) <= TIME_WINDOW:
            return True
    return False


def get_news(section: str = None, query: str = None, page_size: int = 5) -> list[dict]:
    params = {
        "api-key": GUARDIAN_API_KEY,
        "page-size": page_size,
        "order-by": "newest",
        "show-fields": "trailText",
        "lang": "en",
    }
    if section:
        params["section"] = section
    if query:
        params["q"] = query

    resp = requests.get(GUARDIAN_URL, params=params, timeout=15)
    resp.raise_for_status()
    return resp.json()["response"]["results"]


def escape_md(text: str) -> str:
    special = r"_*[]()~`>#+-=|{}.!"
    return "".join(f"\\{c}" if c in special else c for c in text)


def format_section(emoji: str, titolo: str, articles: list[dict]) -> str:
    numeri = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣"]
    lines = [f"{emoji} *{titolo}*", ""]
    for i, article in enumerate(articles):
        title = article["webTitle"]
        url = article["webUrl"]
        num = numeri[i] if i < len(numeri) else f"{i+1}\\."
        lines.append(f"{num} [{escape_md(title)}]({url})")
    lines.append("")
    return "\n".join(lines)


def build_message() -> str:
    now = datetime.now(ITALY_TZ)
    giorno = GIORNI_IT[now.weekday()]
    data_str = f"{giorno} {now.day} {MESI_IT[now.month]} {now.year}"
    ora_str = now.strftime("%H:%M")

    world = get_news(section="world", page_size=5)
    tech = get_news(section="technology", query="AI OR artificial intelligence OR tech", page_size=5)
    seriea = get_news(query='"Serie A"', page_size=5)

    sep = "〰️〰️〰️〰️〰️〰️〰️〰️〰️\n\n"

    msg  = f"🗞 *IL PUNTO DEL GIORNO*\n"
    msg += f"📅 {escape_md(data_str)} · 🕐 {escape_md(ora_str)}\n\n"
    msg += sep
    msg += format_section("🌍", "NOTIZIE DAL MONDO", world)
    msg += sep
    msg += format_section("🤖", "AI & TECNOLOGIA", tech)
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
