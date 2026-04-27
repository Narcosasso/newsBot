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
# Target times (hour, minute) in Italian time
TARGET_TIMES = [(8, 0), (10, 30), (20, 30)]
# Tolerance window in minutes (to avoid double-sends when both CET and CEST crons fire)
TIME_WINDOW = 25


def is_scheduled_time() -> bool:
    now = datetime.now(ITALY_TZ)
    current_minutes = now.hour * 60 + now.minute
    for hour, minute in TARGET_TIMES:
        target_minutes = hour * 60 + minute
        if abs(current_minutes - target_minutes) <= TIME_WINDOW:
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


def format_section(header: str, articles: list[dict]) -> str:
    lines = [header, ""]
    for i, article in enumerate(articles, 1):
        title = article["webTitle"]
        url = article["webUrl"]
        lines.append(f"{i}\\. [{escape_md(title)}]({url})")
    lines.append("")
    return "\n".join(lines)


def escape_md(text: str) -> str:
    """Escape MarkdownV2 special characters."""
    special = r"_*[]()~`>#+-=|{}.!"
    return "".join(f"\\{c}" if c in special else c for c in text)


def build_message() -> str:
    now = datetime.now(ITALY_TZ)
    date_str = now.strftime("%d/%m/%Y %H:%M")

    world = get_news(section="world", page_size=5)
    tech = get_news(section="technology", query="AI OR artificial intelligence OR tech", page_size=5)
    seriea = get_news(query='"Serie A"', page_size=5)

    msg = f"*Notizie del {escape_md(date_str)}*\n\n"
    msg += "\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\n\n"
    msg += format_section("*1\\. Notizie dal Mondo*", world)
    msg += "\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\n\n"
    msg += format_section("*2\\. AI & Tecnologia*", tech)
    msg += "\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\\-\n\n"
    msg += format_section("*3\\. Serie A*", seriea)

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
    print("Message sent successfully.")


def main():
    force = "--force" in sys.argv

    if not force and not is_scheduled_time():
        now = datetime.now(ITALY_TZ)
        print(f"Skipping: current Italian time {now.strftime('%H:%M')} is not within a scheduled window.")
        return

    print("Fetching news...")
    message = build_message()
    print("Sending Telegram message...")
    send_message(message)


if __name__ == "__main__":
    main()
