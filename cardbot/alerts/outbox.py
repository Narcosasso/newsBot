"""Valutazione delle variazioni e outbox delle notifiche.

Idempotenza:
- uno snapshot per (serie, versione della fonte): rielaborare lo stesso file non crea dati nuovi;
- una notifica per (target, snapshot), garantita da un vincolo UNIQUE nel database;
- il valore di riferimento passa al nuovo prezzo nella stessa transazione in cui nasce la notifica;
- invio "al massimo una volta": la riga passa a "sending" (e viene salvata) PRIMA della chiamata a WhatsApp. Se il
  processo muore durante l'invio la riga resta "sending" e non viene ritentata. Le righe "failed" (errore esplicito
  di WhatsApp, quindi messaggio non consegnato) vengono ritentate al giro successivo.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Protocol

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from cardbot.alerts.rules import Change, effective_threshold, evaluate, metric
from cardbot.alerts.sources import PriceData
from cardbot.alerts.tracking import PSA10, target_tag
from cardbot.bot.format import money, pct, trend_icon
from cardbot.db import Notification, PriceSnapshot, Tracking, TrackingTarget, User, utcnow
from cardbot.prices.models import cardmarket_quote
from cardbot.variants import LABELS_IT

log = logging.getLogger(__name__)

SERVICE_WINDOW = timedelta(hours=24)
MAX_TEMPLATE_PARAM = 900
MAX_FAILED_ATTEMPTS_AGE = timedelta(days=3)


def series_key(target: TrackingTarget) -> str:
    if target.source == PSA10:
        return f"ppt:psa10:{target.external_id}"
    return f"cm:{target.id_product}:{target.variant}:{'s' if target.shared_product else 'd'}"



def change_line(tracking: Tracking, target: TrackingTarget, change: Change) -> str:
    """Una riga sola (i parametri dei template WhatsApp non ammettono a capo)."""
    name, _, rest = tracking.label.partition(" · ")
    detail = f"{rest}, {LABELS_IT.get(tracking.variant, tracking.variant)}" if rest else \
        LABELS_IT.get(tracking.variant, tracking.variant)
    cur = target.currency or "EUR"
    return (f"{trend_icon(change.pct)} {name} ({detail}) {target_tag(target)} {money(change.old, cur)} → "
            f"{money(change.new, cur)} ({pct(change.pct)})")


@dataclass
class EvaluationReport:
    source: str
    version: str
    targets: int = 0
    snapshots_created: int = 0
    notifications: list[str] = field(default_factory=list)
    missing_products: list = field(default_factory=list)
    graded_checked: int = 0


def _graded_snapshot(session: Session, graded: dict, target: TrackingTarget, report: EvaluationReport,
                     cache: dict[str, PriceSnapshot]) -> PriceSnapshot | None:
    key = series_key(target)
    if key in cache:
        return cache[key]
    q = graded.get(target.external_id)
    if q is None or not q.has_sales:
        report.missing_products.append(f"PSA 10 {target.external_id}")
        return None
    snap = session.query(PriceSnapshot).filter_by(series=key, source_version=q.version).one_or_none()
    if snap is None:
        snap = PriceSnapshot(series=key, source="pokemonpricetracker", source_version=q.version,
                             source_updated_at=q.updated, trend=q.price, avg=q.median)
        session.add(snap)
        session.flush()
        report.snapshots_created += 1
    cache[key] = snap
    return snap


def _snapshot(session: Session, data: PriceData, target: TrackingTarget, report: EvaluationReport,
              cache: dict[str, PriceSnapshot]) -> PriceSnapshot | None:
    key = series_key(target)
    if key in cache:
        return cache[key]
    entry = data.entries.get(target.id_product)
    if entry is None:
        report.missing_products.append(target.id_product)
        return None
    snap = session.query(PriceSnapshot).filter_by(series=key, source_version=data.version).one_or_none()
    if snap is None:
        q = cardmarket_quote(entry, target.variant, target.shared_product)
        snap = PriceSnapshot(series=key, source=data.source, source_version=data.version,
                             source_updated_at=q.updated, low=q.low, trend=q.trend, avg=q.avg,
                             avg7=q.avg7, avg30=q.avg30)
        session.add(snap)
        session.flush()
        report.snapshots_created += 1
    cache[key] = snap
    return snap


def evaluate_targets(session: Session, data: PriceData | None, graded: dict | None = None) -> EvaluationReport:
    """Salva gli snapshot e crea le notifiche dovute. Non fa commit: lo decide il chiamante.

    data: price guide Cardmarket (None se invariato); graded: {id TCGplayer: GradedQuote} per le PSA 10.
    """
    report = EvaluationReport(source=data.source if data else "-", version=data.version if data else "-")
    cache: dict[str, PriceSnapshot] = {}
    targets = (session.query(TrackingTarget).join(Tracking)
               .filter(Tracking.active.is_(True), TrackingTarget.active.is_(True)).all())
    for target in targets:
        if target.source == PSA10:
            if graded is None:
                continue
            report.targets += 1
            report.graded_checked += 1
            snap = _graded_snapshot(session, graded, target, report, cache)
        else:
            if data is None:
                continue
            report.targets += 1
            snap = _snapshot(session, data, target, report, cache)
        if snap is None:
            continue
        current = metric(snap)  # stesso criterio usato per il valore di riferimento
        tracking, user = target.tracking, target.tracking.user
        if target.baseline is None:
            target.baseline, target.baseline_at = current, utcnow()
            continue
        change = evaluate(target.baseline, current, effective_threshold(user, tracking))
        if change is None:
            continue
        text = change_line(tracking, target, change)
        try:
            with session.begin_nested():
                session.add(Notification(user_id=user.id, target_id=target.id, snapshot_id=snap.id,
                                         old_value=change.old, new_value=change.new, text=text))
        except IntegrityError:
            continue  # notifica già creata per questa variazione
        target.baseline, target.baseline_at = change.new, utcnow()
        report.notifications.append(text)
    return report


class Sender(Protocol):
    async def send_text(self, to: str, text: str) -> str | None: ...

    async def send_template(self, to: str, name: str, lang: str, params: list[str]) -> str | None: ...


@dataclass
class SendReport:
    messages: int = 0
    notifications_sent: int = 0
    failed: int = 0
    used_template: int = 0


def digest_text(lines: list[str]) -> str:
    head = "🔔 *Prezzi cambiati!*" if len(lines) > 1 else "🔔 *Prezzo cambiato!*"
    body = []
    for line in lines:
        body += [line, ""]
    return "\n".join([head, ""] + body + ["Scrivi *novità* per i dettagli o *lista* per le tue carte."])


def template_params(lines: list[str]) -> list[str]:
    """Parametri del template: niente a capo (non ammessi da WhatsApp) e lunghezza limitata."""
    summary, used = "", 0
    for line in lines:
        piece = line if not summary else f"; {line}"
        if len(summary) + len(piece) > MAX_TEMPLATE_PARAM:
            break
        summary += piece
        used += 1
    if used < len(lines):
        summary += f"; e altre {len(lines) - used}"
    return [str(len(lines)), summary.replace("\n", " ")]


async def send_pending(sessions: sessionmaker[Session], sender: Sender, template: str, template_lang: str,
                       now: datetime | None = None) -> SendReport:
    now = now or utcnow()
    report = SendReport()
    with sessions() as session:
        rows = (session.query(Notification)
                .filter(Notification.status.in_(["pending", "failed"]),
                        Notification.created_at >= now - MAX_FAILED_ATTEMPTS_AGE)
                .order_by(Notification.user_id, Notification.id).all())
        by_user: dict[int, list[Notification]] = {}
        for n in rows:
            by_user.setdefault(n.user_id, []).append(n)
        for user_id, notes in by_user.items():
            user = session.get(User, user_id)
            for n in notes:
                n.status = "sending"
            session.commit()  # rivendicate: da qui in poi non verranno mai reinviate in automatico
            lines = [n.text for n in notes]
            in_window = user.last_inbound_at is not None and _aware(user.last_inbound_at) > now - SERVICE_WINDOW
            try:
                if in_window:
                    wamid = await sender.send_text(user.wa_id, digest_text(lines))
                else:
                    wamid = await sender.send_template(user.wa_id, template, template_lang, template_params(lines))
                    report.used_template += 1
            except Exception as exc:  # errore esplicito: il messaggio non è partito
                log.error("Invio notifiche fallito per l'utente %s: %s", user_id, exc)
                for n in notes:
                    n.status, n.error = "failed", str(exc)[:500]
                report.failed += len(notes)
            else:
                for n in notes:
                    n.status, n.wamid, n.sent_at, n.error = "sent", wamid, now, None
                report.messages += 1
                report.notifications_sent += len(notes)
            session.commit()
    return report


def _aware(dt: datetime) -> datetime:
    from datetime import UTC
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)
