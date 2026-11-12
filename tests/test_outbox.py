"""Job giornaliero e outbox: idempotenza, finestra di 24 ore, errori di invio."""

from datetime import timedelta

import pytest

from cardbot.alerts.outbox import digest_text, send_pending, template_params
from cardbot.alerts.sources import PriceData
from cardbot.db import Notification, PriceSnapshot, Tracking, TrackingTarget, User, make_engine, \
    make_session_factory, utcnow
from cardbot.jobs.poll import run_poll

WA = "393330000000"


def entry(pid: int, trend: float, **extra) -> dict:
    return {"idProduct": pid, "avg": trend, "low": trend * 0.6, "trend": trend, "avg1": trend,
            "avg7": trend, "avg30": trend, **extra}


class FakeGuide:
    name = "cardmarket_price_guide"

    def __init__(self):
        self.data: PriceData | None = None
        self.calls: list[str | None] = []

    def publish(self, version: str, *entries: dict) -> None:
        self.data = PriceData(source=self.name, version=version, etag=f'"{version}"',
                              entries={e["idProduct"]: e for e in entries})

    async def fetch(self, etag=None):
        self.calls.append(etag)
        if self.data and etag == self.data.etag:
            return None  # 304 Not Modified
        return self.data


class FakeSender:
    def __init__(self, fail: bool = False):
        self.fail = fail
        self.texts: list[str] = []
        self.templates: list[list[str]] = []

    async def send_text(self, to, text):
        if self.fail:
            raise RuntimeError("WhatsApp 500")
        self.texts.append(text)
        return f"wamid.{len(self.texts)}"

    async def send_template(self, to, name, lang, params):
        if self.fail:
            raise RuntimeError("WhatsApp 500")
        self.templates.append(params)
        return f"wamid.t{len(self.templates)}"


@pytest.fixture
def db():
    sessions = make_session_factory(make_engine("sqlite://"))
    with sessions() as s:
        user = User(wa_id=WA, last_inbound_at=utcnow())
        s.add(user)
        s.flush()
        tr = Tracking(user_id=user.id, card_id="sv03.5-006", catalog_lang="en", variant="holo",
                      label="Charizard ex · 151 006/165", langs="it,ja")
        s.add(tr)
        s.flush()
        tr.targets.append(TrackingTarget(langs="it", card_id="sv03.5-006", catalog_lang="en", id_product=733601,
                                         variant="holo", shared_product=False, aggregated=True, baseline=8.0,
                                         baseline_at=utcnow()))
        tr.targets.append(TrackingTarget(langs="ja", card_id="SV2a-006", catalog_lang="ja", id_product=719448,
                                         variant="holo", shared_product=False, baseline=3.0, baseline_at=utcnow()))
        s.commit()
    return sessions


async def poll(db, guide, sender, **kw):
    return await run_poll(db, guide, sender, "price_alert", "it", **kw)


def count(db, model, **filters):
    with db() as s:
        return s.query(model).filter_by(**filters).count()


async def test_change_above_threshold_notifies_once(db):
    guide, sender = FakeGuide(), FakeSender()
    guide.publish("2026-11-12T02:51", entry(733601, 9.5), entry(719448, 3.1))  # ITA +18,75%; JAP +3%
    report = await poll(db, guide, sender)
    assert len(report.evaluation.notifications) == 1 and "ITA" in report.evaluation.notifications[0]
    assert len(sender.texts) == 1 and "8,00 € → 9,50 €" in sender.texts[0]

    # Stesso file: la seconda richiesta è condizionale (304) e non succede nulla.
    report = await poll(db, guide, sender)
    assert report.status == "invariato (304)" and guide.calls[-1] == '"2026-11-12T02:51"'
    # Anche forzando la rielaborazione della stessa versione: nessun doppione.
    report = await poll(db, guide, sender, force=True)
    assert report.evaluation.notifications == []
    assert len(sender.texts) == 1 and count(db, Notification) == 1 and count(db, PriceSnapshot) == 2


async def test_baseline_moves_to_notified_value(db):
    guide, sender = FakeGuide(), FakeSender()
    guide.publish("v1", entry(733601, 9.5), entry(719448, 3.0))
    await poll(db, guide, sender)
    guide.publish("v2", entry(733601, 9.9), entry(719448, 3.0))   # +4% rispetto a 9,50: niente
    await poll(db, guide, sender)
    guide.publish("v3", entry(733601, 11.0), entry(719448, 3.0))  # +15,8% rispetto a 9,50
    await poll(db, guide, sender)
    assert len(sender.texts) == 2 and "9,50 € → 11,00 €" in sender.texts[1]
    with db() as s:
        assert s.query(TrackingTarget).filter_by(langs="it").one().baseline == 11.0


async def test_digest_groups_changes_of_the_same_user(db):
    guide, sender = FakeGuide(), FakeSender()
    guide.publish("v1", entry(733601, 12.0), entry(719448, 5.0))
    await poll(db, guide, sender)
    assert len(sender.texts) == 1
    assert "ITA" in sender.texts[0] and "JAP" in sender.texts[0] and "Variazioni" in sender.texts[0]


async def test_outside_24h_window_uses_template(db):
    with db() as s:
        s.query(User).one().last_inbound_at = utcnow() - timedelta(hours=30)
        s.commit()
    guide, sender = FakeGuide(), FakeSender()
    guide.publish("v1", entry(733601, 12.0), entry(719448, 3.0))
    report = await poll(db, guide, sender)
    assert sender.texts == [] and len(sender.templates) == 1 and report.sending.used_template == 1
    count_param, summary = sender.templates[0]
    assert count_param == "1" and "\n" not in summary and "8,00 € → 12,00 €" in summary


async def test_failed_send_is_retried_next_run(db):
    guide = FakeGuide()
    guide.publish("v1", entry(733601, 12.0), entry(719448, 3.0))
    report = await poll(db, guide, FakeSender(fail=True))
    assert report.sending.failed == 1 and count(db, Notification, status="failed") == 1
    ok = FakeSender()
    await poll(db, guide, ok)  # file invariato (304), ma l'invio fallito viene ritentato
    assert len(ok.texts) == 1 and count(db, Notification, status="sent") == 1


async def test_rows_left_in_sending_are_never_resent(db):
    """Crash durante l'invio: meglio perdere l'avviso che mandarlo due volte."""
    guide = FakeGuide()
    guide.publish("v1", entry(733601, 12.0), entry(719448, 3.0))
    await poll(db, guide, None)  # nessun sender: la notifica resta pending
    with db() as s:
        s.query(Notification).one().status = "sending"
        s.commit()
    sender = FakeSender()
    await send_pending(db, sender, "price_alert", "it")
    assert sender.texts == [] and sender.templates == []


async def test_dry_run_saves_nothing(db):
    guide, sender = FakeGuide(), FakeSender()
    guide.publish("v1", entry(733601, 12.0), entry(719448, 3.0))
    report = await poll(db, guide, sender, dry_run=True)
    assert len(report.evaluation.notifications) == 1 and "dry-run" in report.status
    assert sender.texts == [] and count(db, Notification) == 0 and count(db, PriceSnapshot) == 0
    with db() as s:
        assert s.query(TrackingTarget).filter_by(langs="it").one().baseline == 8.0


async def test_inactive_tracking_is_ignored(db):
    with db() as s:
        s.query(Tracking).one().active = False
        s.commit()
    guide, sender = FakeGuide(), FakeSender()
    guide.publish("v1", entry(733601, 50.0), entry(719448, 50.0))
    report = await poll(db, guide, sender)
    assert report.evaluation.targets == 0 and sender.texts == []


async def test_reverse_uses_holo_fields_of_shared_product(db):
    with db() as s:
        t = s.query(TrackingTarget).filter_by(langs="it").one()
        t.variant, t.shared_product, t.baseline = "reverse", True, 0.36
        s.commit()
    guide, sender = FakeGuide(), FakeSender()
    # La normale sale moltissimo, la reverse (campi -holo) no: nessuna notifica per ITA.
    guide.publish("v1", entry(733601, 30.0, **{"trend-holo": 0.4, "avg-holo": 0.4, "avg7-holo": 0.4}),
                  entry(719448, 3.0))
    report = await poll(db, guide, sender)
    assert report.evaluation.notifications == []


async def test_product_missing_from_source_is_reported(db):
    guide, sender = FakeGuide(), FakeSender()
    guide.publish("v1", entry(733601, 8.0))
    report = await poll(db, guide, sender)
    assert report.evaluation.missing_products == [719448]


def test_template_params_are_single_line_and_bounded():
    lines = [f"Carta {i} — 🇮🇹 ITA: 1,00 € → 2,00 € 📈 +100,0%" for i in range(60)]
    count_param, summary = template_params(lines)
    assert count_param == "60" and "\n" not in summary and len(summary) < 1000 and "e altre" in summary


def test_digest_text_single_and_multiple():
    assert "Variazione di prezzo" in digest_text(["a"])
    assert "Variazioni di prezzo" in digest_text(["a", "b"])
