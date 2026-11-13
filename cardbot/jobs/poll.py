"""Job giornaliero: aggiorna i prezzi delle carte tracciate e invia le notifiche.

  python -m cardbot.jobs.poll             # esecuzione normale
  python -m cardbot.jobs.poll --dry-run   # mostra cosa notificherebbe, senza salvare né inviare
  python -m cardbot.jobs.poll --force     # rielabora anche se la fonte non è cambiata (resta idempotente)

Va schedulato una volta al giorno dopo l'aggiornamento del price guide (es. alle 04:00 ora italiana). Eseguirlo più
spesso non fa danni: con l'ETag invariato il server risponde 304 e il job si limita a ritentare gli invii falliti.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
from dataclasses import dataclass

from sqlalchemy.orm import Session, sessionmaker

from cardbot.alerts.outbox import EvaluationReport, SendReport, Sender, evaluate_targets, send_pending
from cardbot.alerts.sources import CardmarketPriceGuide, PriceData, TCGdexPrices
from cardbot.alerts.tracking import PSA10
from cardbot.db import JobState, Tracking, TrackingTarget

log = logging.getLogger("cardbot.poll")
STATE_KEY = "price_guide"


@dataclass
class PollReport:
    status: str
    evaluation: EvaluationReport | None = None
    sending: SendReport | None = None

    def summary(self) -> str:
        lines = [f"Esito: {self.status}"]
        if self.evaluation:
            e = self.evaluation
            lines.append(f"Fonte {e.source} versione {e.version}: {e.targets} prezzi sorvegliati "
                         f"(di cui {e.graded_checked} PSA 10), {e.snapshots_created} snapshot nuovi, "
                         f"{len(e.notifications)} notifiche")
            lines += [f"  • {n}" for n in e.notifications]
            if e.missing_products:
                lines.append(f"  prodotti assenti dalla fonte: {sorted(set(e.missing_products))}")
        if self.sending:
            s = self.sending
            lines.append(f"Invio: {s.messages} messaggi ({s.notifications_sent} notifiche, "
                         f"{s.used_template} con template), {s.failed} fallite")
        return "\n".join(lines)


async def _load_data(session: Session, guide: CardmarketPriceGuide, fallback: TCGdexPrices | None,
                     force: bool) -> tuple[PriceData | None, str]:
    state = session.get(JobState, STATE_KEY) or JobState(key=STATE_KEY, value={})
    etag = None if force else (state.value or {}).get("etag")
    try:
        data = await guide.fetch(etag=etag)
    except Exception as exc:
        log.warning("Price guide non disponibile (%s): uso TCGdex", exc)
        if fallback is None:
            raise
        targets = (session.query(TrackingTarget).join(Tracking)
                   .filter(Tracking.active.is_(True), TrackingTarget.active.is_(True),
                           TrackingTarget.source != PSA10).all())
        return await fallback.fetch_for([(t.catalog_lang, t.card_id, t.variant) for t in targets]), "fallback"
    if data is None:
        return None, "invariato (304)"
    if not force and (state.value or {}).get("version") == data.version:
        return None, "versione già elaborata"
    return data, "nuova versione"


async def _load_graded(session: Session, graded) -> dict | None:
    """Prezzi PSA 10 delle carte seguite: una richiesta (2 crediti) per carta distinta."""
    if graded is None or not graded.enabled:
        return None
    targets = (session.query(TrackingTarget).join(Tracking)
               .filter(Tracking.active.is_(True), TrackingTarget.active.is_(True),
                       TrackingTarget.source == PSA10).all())
    out: dict = {}
    for t in targets:
        if t.external_id in out:
            continue
        language = "japanese" if t.catalog_lang == "ja" else "english"
        try:
            out[t.external_id] = await graded.by_id(t.external_id, language)
        except Exception as exc:
            log.warning("PSA 10 non disponibile per %s: %s", t.external_id, exc)
    return out


async def run_poll(sessions: sessionmaker[Session], guide: CardmarketPriceGuide, sender: Sender | None,
                   template: str, template_lang: str, fallback: TCGdexPrices | None = None,
                   dry_run: bool = False, force: bool = False, graded=None) -> PollReport:
    with sessions() as session:
        data, status = await _load_data(session, guide, fallback, force)
        graded_quotes = await _load_graded(session, graded)
        evaluation = None
        if data is not None or graded_quotes:
            evaluation = evaluate_targets(session, data, graded_quotes)
            if dry_run:
                session.rollback()
                return PollReport(status=f"{status} (dry-run: nulla salvato né inviato)", evaluation=evaluation)
            if data is not None and data.source == guide.name:
                state = session.get(JobState, STATE_KEY) or JobState(key=STATE_KEY)
                state.value = {"version": data.version, "etag": data.etag}
                session.merge(state)
            session.commit()
        elif dry_run:
            return PollReport(status=f"{status} (dry-run)")
    sending = None
    if sender is not None and not dry_run:
        sending = await send_pending(sessions, sender, template, template_lang)
    return PollReport(status=status, evaluation=evaluation, sending=sending)


def main(argv: list[str] | None = None) -> int:
    from cardbot.catalog.tcgdex import TCGdexCatalog
    from cardbot.config import get_settings
    from cardbot.db import make_engine, make_session_factory
    from cardbot.whatsapp.client import WhatsAppClient
    from cardbot.prices.graded import GradedPrices

    parser = argparse.ArgumentParser(prog="cardbot.jobs.poll")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    s = get_settings()
    sessions = make_session_factory(make_engine(s.database_url))
    sender = None
    if s.whatsapp_token and s.whatsapp_phone_number_id:
        sender = WhatsAppClient(s.whatsapp_token, s.whatsapp_phone_number_id, s.whatsapp_api_version)
    elif not args.dry_run:
        log.warning("WHATSAPP_TOKEN/WHATSAPP_PHONE_NUMBER_ID mancanti: le notifiche restano in coda")

    report = asyncio.run(run_poll(
        sessions, CardmarketPriceGuide(s.cardmarket_price_guide_url), sender,
        s.whatsapp_alert_template, s.whatsapp_template_lang,
        fallback=TCGdexPrices(TCGdexCatalog(s.tcgdex_base_url, s.tcgdex_max_rps)),
        dry_run=args.dry_run, force=args.force,
        graded=GradedPrices(s.pokemonpricetracker_api_key) if s.pokemonpricetracker_api_key else None,
    ))
    print(report.summary())
    return 1 if report.sending and report.sending.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
