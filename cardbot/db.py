"""Modelli e sessione del database (SQLite in locale, Postgres/Neon in produzione)."""

from __future__ import annotations


from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint, create_engine,
)
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, relationship, sessionmaker
from sqlalchemy.pool import StaticPool


def utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


DEFAULT_THRESHOLD_PCT = 10.0
DEFAULT_THRESHOLD_EUR = 1.0


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    wa_id: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    langs: Mapped[str | None] = mapped_column(String(64))  # ultime lingue usate, es. "it,en,ja"
    # Soglia di notifica predefinita: avvisa se la variazione supera ENTRAMBE (None = condizione disattivata).
    threshold_pct: Mapped[float | None] = mapped_column(Float, default=DEFAULT_THRESHOLD_PCT)
    threshold_eur: Mapped[float | None] = mapped_column(Float, default=DEFAULT_THRESHOLD_EUR)
    # Ultimo messaggio ricevuto: entro 24 ore si può rispondere con testo libero, dopo serve un template.
    last_inbound_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    trackings: Mapped[list[Tracking]] = relationship(back_populates="user")


class Tracking(Base):
    """Una carta seguita da un utente, in una variante, per alcune lingue."""

    __tablename__ = "trackings"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    card_id: Mapped[str] = mapped_column(String(64))          # id TCGdex, es. sv03.5-006
    catalog_lang: Mapped[str] = mapped_column(String(8))
    variant: Mapped[str] = mapped_column(String(16))
    label: Mapped[str] = mapped_column(String(200))
    langs: Mapped[str] = mapped_column(String(64))            # es. "it,en,ja"
    # Soglia della singola carta, usata solo se threshold_custom è True (altrimenti vale quella dell'utente).
    threshold_custom: Mapped[bool] = mapped_column(Boolean, default=False)
    threshold_pct: Mapped[float | None] = mapped_column(Float)
    threshold_eur: Mapped[float | None] = mapped_column(Float)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    user: Mapped[User] = relationship(back_populates="trackings")
    targets: Mapped[list[TrackingTarget]] = relationship(back_populates="tracking")


class TrackingTarget(Base):
    """Un prezzo da sorvegliare.

    source="cardmarket": un prodotto Cardmarket per un gruppo di lingue (es. ITA+ENG, oppure JAP), in euro.
    source="psa10": il prezzo PSA 10 di PokemonPriceTracker (external_id = ID TCGplayer), in dollari.
    """

    __tablename__ = "tracking_targets"

    id: Mapped[int] = mapped_column(primary_key=True)
    tracking_id: Mapped[int] = mapped_column(ForeignKey("trackings.id"), index=True)
    source: Mapped[str] = mapped_column(String(16), default="cardmarket", server_default="cardmarket")
    langs: Mapped[str] = mapped_column(String(64))
    card_id: Mapped[str] = mapped_column(String(64))           # carta da cui viene il prezzo (può essere l'equivalente JP)
    catalog_lang: Mapped[str] = mapped_column(String(8))
    id_product: Mapped[int | None] = mapped_column(Integer, index=True)  # Cardmarket
    external_id: Mapped[str | None] = mapped_column(String(64))           # PSA 10: ID TCGplayer
    currency: Mapped[str] = mapped_column(String(3), default="EUR", server_default="EUR")
    variant: Mapped[str] = mapped_column(String(16))
    shared_product: Mapped[bool] = mapped_column(Boolean, default=True)
    aggregated: Mapped[bool] = mapped_column(Boolean, default=False)
    # Valore di riferimento: l'ultimo notificato (all'inizio, quello mostrato quando hai attivato le notifiche).
    baseline: Mapped[float | None] = mapped_column(Float)
    baseline_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    active: Mapped[bool] = mapped_column(Boolean, default=True)

    tracking: Mapped[Tracking] = relationship(back_populates="targets")


class PriceSnapshot(Base):
    """Prezzo di una serie (prodotto + insieme di campi) in una data versione della fonte."""

    __tablename__ = "price_snapshots"
    __table_args__ = (UniqueConstraint("series", "source_version", name="uq_snapshot_series_version"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    series: Mapped[str] = mapped_column(String(64), index=True)   # es. "cm:733596:reverse:shared"
    source: Mapped[str] = mapped_column(String(32))
    source_version: Mapped[str] = mapped_column(String(64))       # createdAt del price guide
    source_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    low: Mapped[float | None] = mapped_column(Float)
    trend: Mapped[float | None] = mapped_column(Float)
    avg: Mapped[float | None] = mapped_column(Float)
    avg7: Mapped[float | None] = mapped_column(Float)
    avg30: Mapped[float | None] = mapped_column(Float)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Notification(Base):
    """Outbox delle notifiche. Una sola riga per (target, snapshot): la stessa variazione non si notifica due volte.

    Stati: pending -> sending -> sent | failed. Una riga rimasta in "sending" (crash durante l'invio) non viene
    reinviata automaticamente: meglio perdere un avviso che mandarlo due volte.
    """

    __tablename__ = "notifications"
    __table_args__ = (UniqueConstraint("target_id", "snapshot_id", name="uq_notification_target_snapshot"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    target_id: Mapped[int] = mapped_column(ForeignKey("tracking_targets.id"))
    snapshot_id: Mapped[int] = mapped_column(ForeignKey("price_snapshots.id"))
    old_value: Mapped[float] = mapped_column(Float)
    new_value: Mapped[float] = mapped_column(Float)
    text: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    wamid: Mapped[str | None] = mapped_column(String(128))
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class JobState(Base):
    """Stato persistente dei job (es. ETag e versione dell'ultimo price guide elaborato)."""

    __tablename__ = "job_state"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class InboundMessage(Base):
    """Id dei messaggi WhatsApp già ricevuti: Meta ritenta i webhook, così non li elaboriamo due volte."""

    __tablename__ = "inbound_messages"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    wa_id: Mapped[str] = mapped_column(String(32))
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ConversationState(Base):
    __tablename__ = "conversation_state"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    stage: Mapped[str] = mapped_column(String(32), default="idle")
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


def normalize_url(url: str) -> str:
    """Neon e altri provider danno 'postgresql://…' o 'postgres://…': per SQLAlchemy serve il driver psycopg."""
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix):]
    return url


def make_engine(url: str, create_tables: bool | None = None) -> Engine:
    """Con SQLite le tabelle si creano da sole (sviluppo e test); con Postgres le gestisce Alembic."""
    url = normalize_url(url)
    kwargs: dict[str, Any] = {"pool_pre_ping": True}
    is_sqlite = url.startswith("sqlite")
    if is_sqlite:
        kwargs["connect_args"] = {"check_same_thread": False}
        if url in ("sqlite://", "sqlite:///:memory:"):
            kwargs["poolclass"] = StaticPool  # un solo DB in memoria condiviso fra i thread
    else:
        kwargs["pool_size"], kwargs["max_overflow"] = 2, 2  # uso personale: poche connessioni (Neon free)
    engine = create_engine(url, **kwargs)
    if create_tables if create_tables is not None else is_sqlite:
        Base.metadata.create_all(engine)
    return engine


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(engine, expire_on_commit=False)


def get_or_create_user(session: Session, wa_id: str) -> tuple[User, bool]:
    """(utente, creato_ora): il secondo valore serve a dare il benvenuto al primo messaggio."""
    user = session.query(User).filter_by(wa_id=wa_id).one_or_none()
    if user is not None:
        return user, False
    user = User(wa_id=wa_id)
    session.add(user)
    session.flush()
    return user, True


def claim_inbound(session_factory: sessionmaker[Session], message_id: str, wa_id: str) -> bool:
    """Registra il messaggio. False se era già stato ricevuto (retry di Meta)."""
    with session_factory() as session:
        session.add(InboundMessage(id=message_id, wa_id=wa_id))
        try:
            session.commit()
        except IntegrityError:
            session.rollback()
            return False
    return True


def load_state(session: Session, user: User) -> ConversationState:
    state = session.get(ConversationState, user.id)
    if state is None:
        state = ConversationState(user_id=user.id, stage="idle", payload={})
        session.add(state)
        session.flush()
    return state


def save_state(state: ConversationState, stage: str, payload: dict[str, Any] | None = None) -> None:
    state.stage = stage
    state.payload = dict(payload or {})
