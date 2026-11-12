"""Modelli e sessione del database (SQLite in locale, Postgres/Neon in produzione)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, String, create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker
from sqlalchemy.pool import StaticPool


def utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    wa_id: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    langs: Mapped[str | None] = mapped_column(String(64))  # ultime lingue usate, es. "it,en,ja"
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


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


def make_engine(url: str) -> Engine:
    kwargs: dict[str, Any] = {"pool_pre_ping": True}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
        if url in ("sqlite://", "sqlite:///:memory:"):
            kwargs["poolclass"] = StaticPool  # un solo DB in memoria condiviso fra i thread
    engine = create_engine(url, **kwargs)
    Base.metadata.create_all(engine)
    return engine


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(engine, expire_on_commit=False)


def get_or_create_user(session: Session, wa_id: str) -> User:
    user = session.query(User).filter_by(wa_id=wa_id).one_or_none()
    if user is None:
        user = User(wa_id=wa_id)
        session.add(user)
        session.flush()
    return user


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
