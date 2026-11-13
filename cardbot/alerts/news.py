"""Comando "novità": come si sono mossi i prezzi delle carte seguite, anche sotto la soglia di notifica.

Usa gli snapshot salvati dal controllo giornaliero (stessa fonte delle notifiche), quindi non fa richieste esterne.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy.orm import Session

from cardbot.alerts.outbox import series_key
from cardbot.alerts.tracking import target_tag
from cardbot.alerts.rules import Threshold, metric
from cardbot.bot.format import card_title, money, pct, trend_icon, when
from cardbot.db import PriceSnapshot, Tracking, User

NOTEWORTHY_PCT = 1.0  # sotto l'1% una variazione non è una "novità"


def _change(new: float | None, old: float | None) -> float | None:
    if new is None or not old:
        return None
    return (new - old) / old * 100


@dataclass
class _Row:
    line: str
    detail: str | None
    move: float  # la variazione più ampia, con il suo segno (per ordinare e scegliere la freccia)


def _target_row(session: Session, target, tz: str) -> _Row | None:
    key = series_key(target)
    snaps = (session.query(PriceSnapshot).filter_by(series=key)
             .order_by(PriceSnapshot.fetched_at.desc(), PriceSnapshot.id.desc()).limit(2).all())
    if not snaps:
        return None
    latest = snaps[0]
    current = metric(latest)
    if current is None:
        return None
    prev = metric(snaps[1]) if len(snaps) > 1 else None
    week_ago = (session.query(PriceSnapshot).filter(PriceSnapshot.series == key,
                                                    PriceSnapshot.fetched_at <= latest.fetched_at - timedelta(days=6, hours=12))
                .order_by(PriceSnapshot.fetched_at.desc()).first())
    d_prev = _change(current, prev)
    d_week = _change(current, metric(week_ago)) if week_ago else None
    d_ref = _change(current, target.baseline)

    cur = target.currency or "EUR"
    parts = []
    if d_prev is not None:
        parts.append(f"ieri {pct(d_prev)}")
    if d_week is not None:
        parts.append(f"7 gg {pct(d_week)}")
    line = f"{target_tag(target)} *{money(current, cur)}*" + (f"  {' · '.join(parts)}" if parts else "")
    detail = None
    if d_ref is not None and target.baseline_at is not None and abs(d_ref) >= 0.05:
        detail = f"↳ dal tuo riferimento ({money(target.baseline, cur)} del {when(target.baseline_at, tz)[:5]}): {pct(d_ref)}"
    move = max((x for x in (d_prev, d_week, d_ref) if x is not None), key=abs, default=0.0)
    return _Row(line=line, detail=detail, move=move)


def build_news(session: Session, user: User, tz: str = "Europe/Rome") -> str:
    trackings = (session.query(Tracking).filter_by(user_id=user.id, active=True).order_by(Tracking.id).all())
    if not trackings:
        return ("Non segui ancora nessuna carta 🙂\nCercane una (es. *30C 154*) e rispondi *Sì* quando ti chiedo "
                "delle notifiche.")

    cards = []
    missing = []
    last_check = None
    for t in trackings:
        rows = [r for target in t.targets if target.active and (r := _target_row(session, target, tz))]
        name, detail = card_title(t.label, t.variant)
        if not rows:
            missing.append(name)
            continue
        move = max((r.move for r in rows), key=abs)
        cards.append((move, name, detail, rows))
        for target in t.targets:
            snap = (session.query(PriceSnapshot).filter_by(series=series_key(target))
                    .order_by(PriceSnapshot.fetched_at.desc()).first())
            if snap and (last_check is None or snap.fetched_at > last_check):
                last_check = snap.fetched_at

    if not cards:
        return ("📰 Non ho ancora controllato i prezzi delle tue carte.\n"
                "Il controllo automatico è ogni mattina alle 4: domani trovi qui le prime novità.")

    moved = sum(1 for c in cards if abs(c[0]) >= NOTEWORTHY_PCT)
    lines = ["📰 *Novità sulle tue carte*", f"_Ultimo controllo: {when(last_check, tz)}_", ""]
    lines.append(f"{moved} {'carta si è mossa' if moved == 1 else 'carte si sono mosse'} di almeno l'1%."
                 if moved else "Prezzi stabili: nessuna carta si è mossa di almeno l'1%.")
    lines.append("")
    for move, name, detail, rows in sorted(cards, key=lambda c: abs(c[0]), reverse=True):
        lines.append(f"{trend_icon(move)} *{name}*")
        lines.append(detail)
        for r in rows:
            lines.append(r.line)
            if r.detail:
                lines.append(r.detail)
        lines.append("")
    if missing:
        lines.append(f"⏳ Ancora da controllare: {', '.join(missing)}.")
    th = Threshold(pct=user.threshold_pct, eur=user.threshold_eur)
    lines.append(f"🔔 Ti avviso da solo quando il prezzo si allontana dal riferimento di almeno ±{th.describe()}.")
    return "\n".join(lines).strip()
