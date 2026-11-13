"""Testi dei messaggi in italiano (formattazione WhatsApp: *grassetto*, _corsivo_).

Linee guida: frasi brevi e in tono amichevole, il dato importante in grassetto, le spiegazioni una sola volta in
fondo al messaggio.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from cardbot.langs import NAMES_IT, flag, full_name
from cardbot.prices.models import CardmarketQuote, LangQuote, TCGplayerQuote
from cardbot.variants import LABELS_IT


# --- numeri e date ----------------------------------------------------------------------------------

def money(value: float | None, currency: str = "EUR") -> str:
    if value is None:
        return "n.d."
    text = f"{value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    symbol = {"EUR": "€", "USD": "$"}.get(currency, currency)
    return f"{text} {symbol}"


def pct(value: float | None) -> str:
    """'+2,3%' / '−7,1%' (con il vero segno meno, più leggibile)."""
    if value is None:
        return "n.d."
    return f"{value:+.1f}%".replace(".", ",").replace("-", "−")


def trend_icon(value: float | None) -> str:
    if value is None or abs(value) < 0.5:
        return "➖"
    return "📈" if value > 0 else "📉"


def when(dt: datetime | None, tz: str = "Europe/Rome") -> str:
    if dt is None:
        return "data non disponibile"
    local = dt.astimezone(ZoneInfo(tz))
    return f"{local:%d/%m} alle {local:%H:%M}"


def card_title(label: str, variant: str) -> tuple[str, str]:
    """('Gengar ex', '30th Celebration 154/128 · Holo') da 'Gengar ex · 30th Celebration 154/128'."""
    name, _, rest = label.partition(" · ")
    detail = f"{rest} · {LABELS_IT.get(variant, variant)}" if rest else LABELS_IT.get(variant, variant)
    return name, detail


# --- prezzi -----------------------------------------------------------------------------------------

def _price_block(cm: CardmarketQuote) -> list[str]:
    cur = cm.currency
    main = cm.trend or cm.avg7 or cm.avg
    lines = [f"💶 *{money(main, cur)}* prezzo di mercato"]
    extra = []
    if cm.low:
        extra.append(f"da {money(cm.low, cur)}")
    if cm.avg:
        extra.append(f"media vendite {money(cm.avg, cur)}")
    if extra:
        lines.append("↳ " + " · ".join(extra))
    if cm.change_7d_pct is not None or cm.change_30d_pct is not None:
        lines.append(f"{trend_icon(cm.change_30d_pct)} rispetto alla media: {pct(cm.change_7d_pct)} (7 gg) · "
                     f"{pct(cm.change_30d_pct)} (30 gg)")
    return lines


TREND_WORDS = {"up": 1.0, "down": -1.0}


def graded_line(g) -> str:
    """Riga PSA 10 (GradedQuote di PokemonPriceTracker)."""
    if not g.has_sales:
        return "🏅 PSA 10: nessuna vendita registrata finora"
    parts = [f"🏅 PSA 10: *{money(g.price, g.currency)}*"]
    if g.median:
        parts.append(f"mediana {money(g.median, g.currency)}")
    parts.append(f"{g.sales} vendite")
    return " · ".join(parts) + f" {trend_icon(TREND_WORDS.get(g.trend or '', 0.0))}"


def _tcgplayer_line(tp: TCGplayerQuote) -> str:
    return f"🇺🇸 Negli USA (TCGplayer): {money(tp.market, tp.currency)} · da {money(tp.low, tp.currency)}"


def _lang_header(q: LangQuote) -> str:
    names = " · ".join(full_name(lang) for lang in q.langs)
    head = f"*{names}*"
    if q.card_label and (q.estimated_equivalent or q.langs == ["ja"]):
        _, _, detail = q.card_label.partition(" · ")
        if detail:
            head += f" · {detail}"
    return head


def format_quotes(title: str, variant: str, quotes: list[LangQuote], tz: str = "Europe/Rome",
                  warnings: list[str] | None = None) -> str:
    name, detail = card_title(title, variant)
    lines = [f"🃏 *{name}*", detail, ""]
    for w in warnings or []:
        lines += [f"⚠️ {w}", ""]

    notes: list[str] = []
    updated: list[datetime] = []
    for q in quotes:
        lines.append(_lang_header(q))
        if q.cardmarket and q.cardmarket.has_data:
            lines += _price_block(q.cardmarket)
            if q.cardmarket.updated:
                updated.append(q.cardmarket.updated)
        elif q.card_id:
            lines.append("Nessun prezzo su Cardmarket per questa versione.")
        if q.tcgplayer:
            lines.append(_tcgplayer_line(q.tcgplayer))
        if q.graded is not None:
            lines.append(graded_line(q.graded))
            if not any(n.startswith("ℹ️ PSA 10") for n in notes):
                notes.append("ℹ️ PSA 10: vendite eBay e Fanatics negli USA, in dollari (della stampa inglese per "
                             "le lingue internazionali).")
        for note in q.notes:
            lines.append(note)
        lines.append("")
        if q.aggregated:
            notes.append("ℹ️ Cardmarket non distingue italiano, inglese, tedesco, francese, spagnolo e "
                         "portoghese: il prezzo è lo stesso per tutte.")
        if q.estimated_equivalent:
            notes.append(f"ℹ️ La versione {', '.join(NAMES_IT[c].lower() for c in q.langs)} è abbinata in "
                         "automatico (stessa illustrazione): verifica che sia quella giusta.")

    lines += notes
    if updated:
        lines.append(f"📅 Prezzi Cardmarket aggiornati il {when(max(updated), tz)}")
    return "\n".join(lines).strip()


# --- carte seguite ----------------------------------------------------------------------------------

def format_tracking_list(trackings, user) -> str:
    from cardbot.alerts.rules import effective_threshold
    from cardbot.alerts.tracking import target_tag

    lines = [f"📋 *Le carte che segui* ({len(trackings)})", ""]
    for i, t in enumerate(trackings, 1):
        name, detail = card_title(t.label, t.variant)
        lines.append(f"*{i}. {name}*")
        lines.append(detail)
        prices = [f"{target_tag(target)} {money(target.baseline, target.currency or 'EUR')}"
                  for target in t.targets if target.active]
        if prices:
            lines.append(" · ".join(prices))
        th = effective_threshold(user, t)
        lines.append(f"🔔 avviso a ±{th.describe()}" + (" (solo questa carta)" if t.threshold_custom else ""))
        lines.append("")
    lines.append("_Modifica con: *stop 1* · *lingue 1 ita jap* · *soglia 1 20%* · *novità*_")
    return "\n".join(lines)


# --- guida ------------------------------------------------------------------------------------------

def help_text(photos_enabled: bool = True, threshold: str = "10% e 1,00 €", graded: bool = False) -> str:
    search = [
        "🔎 *Cerca una carta*",
        "Scrivi codice e numero stampati in basso sulla carta:",
        "• *MEW 006* · *30C 154* · *SV2a 006/165*",
        "• aggiungi le lingue: *30C 154 ita jap*",
        "• oppure il nome: *Gengar ex 154/128*",
    ]
    if photos_enabled:
        search.append("• oppure mandami una 📸 *foto* della carta")
    cards = [
        "",
        "📋 *Le tue carte*",
        "• *lista* · le carte che segui",
        "• *novità* · come si sono mossi i prezzi",
        "• *stop 2* · non seguire più la carta 2",
        "• *lingue 2 ita jap* · cambia le lingue",
    ]
    if graded:
        cards.append("• *psa 2* · segui anche il prezzo PSA 10 della carta 2")
    return "\n".join(search + cards + [
        f"• *soglia 15%* · quando avvisarti (ora: ±{threshold})",
        "",
        "⚙️ *Altro*",
        "• *comandi* · questo elenco",
        "• *annulla* · ricomincia da capo",
    ])


def welcome_text(photos_enabled: bool = True, threshold: str = "10% e 1,00 €", graded: bool = False) -> str:
    return ("👋 *Ciao! Sono Cardbot.*\n"
            "Ti dico quanto valgono le tue carte Pokémon, lingua per lingua, e ti avviso quando il prezzo "
            "cambia.\n\n" + help_text(photos_enabled, threshold, graded))
