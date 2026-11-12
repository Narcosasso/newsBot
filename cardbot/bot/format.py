"""Testi dei messaggi in italiano (formattazione WhatsApp: *grassetto*, _corsivo_)."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from cardbot.langs import label
from cardbot.prices.models import CardmarketQuote, LangQuote, TCGplayerQuote
from cardbot.variants import LABELS_IT


def money(value: float | None, currency: str = "EUR") -> str:
    if value is None:
        return "n.d."
    text = f"{value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    symbol = {"EUR": "€", "USD": "$"}.get(currency, currency)
    return f"{text} {symbol}"


def pct(value: float | None) -> str:
    if value is None:
        return "n.d."
    arrow = "📈" if value > 0.5 else "📉" if value < -0.5 else "➖"
    return f"{arrow} {value:+.1f}%".replace(".", ",")


def when(dt: datetime | None, tz: str = "Europe/Rome") -> str:
    if dt is None:
        return "data n.d."
    return dt.astimezone(ZoneInfo(tz)).strftime("%d/%m/%Y %H:%M")


def _cardmarket_lines(cm: CardmarketQuote, tz: str) -> list[str]:
    cur = cm.currency
    return [
        f"• Low {money(cm.low, cur)} · Trend {money(cm.trend, cur)} · Media vendite {money(cm.avg, cur)}",
        f"• Media 7gg {money(cm.avg7, cur)} · 30gg {money(cm.avg30, cur)}",
        f"• Andamento: vs 7gg {pct(cm.change_7d_pct)} · vs 30gg {pct(cm.change_30d_pct)}",
        f"_Cardmarket, agg. {when(cm.updated, tz)}_",
    ]


def _tcgplayer_line(tp: TCGplayerQuote, tz: str) -> str:
    return (f"• 🇺🇸 TCGplayer (mercato USA): market {money(tp.market, tp.currency)} · "
            f"low {money(tp.low, tp.currency)} _(agg. {when(tp.updated, tz)})_")


def format_quotes(title: str, variant: str, quotes: list[LangQuote], tz: str = "Europe/Rome",
                  warnings: list[str] | None = None) -> str:
    lines = [f"🃏 *{title}* · {LABELS_IT.get(variant, variant)}", ""]
    for w in warnings or []:
        lines.append(f"⚠️ {w}")
    for q in quotes:
        head = "*" + " · ".join(label(lang) for lang in q.langs) + "*"
        if q.card_label and q.estimated_equivalent:
            head += f" — {q.card_label} _(equivalente stimato)_"
        elif q.card_label and q.langs == ["ja"]:
            head += f" — {q.card_label}"
        lines.append(head)
        if q.aggregated:
            lines.append("_Cardmarket vende ITA, ENG, DEU, FRA, SPA e POR come un unico prodotto: "
                         "il prezzo è aggregato su queste lingue._")
        if q.cardmarket and q.cardmarket.has_data:
            lines.extend(_cardmarket_lines(q.cardmarket, tz))
        elif q.card_id:
            lines.append("• Nessun prezzo Cardmarket disponibile per questa variante.")
        if q.tcgplayer:
            lines.append(_tcgplayer_line(q.tcgplayer, tz))
        for note in q.notes:
            lines.append(f"• {note}")
        lines.append("")
    lines.append("_Fonte: Cardmarket e TCGplayer tramite TCGdex (dati gratuiti, aggiornati una volta al giorno)._")
    return "\n".join(lines).strip()


HELP = """*Come cercare una carta*
• 📸 Invia la *foto* della carta. Nella didascalia puoi già scrivere le lingue, es. _ita, eng, jap_
• ⌨️ Oppure scrivi *codice set e numero* stampati in basso sulla carta (gratis, nessuna foto):
   _MEW 006_ · _PAL 123/193_ · _SV2a 006/165_ (giapponese)
   Puoi aggiungere nome, lingue e variante: _Charizard ex MEW 006 reverse ita jap_

*Comandi*
• *lingue* – lingue supportate
• *annulla* – interrompe la ricerca in corso
• *aiuto* – questo messaggio

_Tracking e notifiche arrivano nella prossima fase._"""
