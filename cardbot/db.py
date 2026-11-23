"""Modelli e sessione del database (SQLite in locale, Postgres/Neon in produzione)."""

from __future__ import annotations


from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import (
    JSON, Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint, create_engine,
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
    # App PokeVault: amici invitati (wa_id fittizio "app:…", niente WhatsApp), con nome e PIN propri.
    display_name: Mapped[str | None] = mapped_column(String(60))
    pin_hash: Mapped[str | None] = mapped_column(String(200))
    invited_by: Mapped[int | None] = mapped_column(Integer)

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


class AppSession(Base):
    """Accesso all'app PokeVault da un dispositivo: si crea con il PIN e resta valido finché non lo revochi."""

    __tablename__ = "app_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)  # sha256 del token del cookie
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    user_agent: Mapped[str | None] = mapped_column(String(300))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class RecentView(Base):
    """Carte aperte di recente nell'app (per la sezione "Visti di recente")."""

    __tablename__ = "recent_views"
    __table_args__ = (UniqueConstraint("user_id", "catalog_lang", "card_id", name="uq_recent_user_card"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    card_id: Mapped[str] = mapped_column(String(64))
    catalog_lang: Mapped[str] = mapped_column(String(8))
    name: Mapped[str] = mapped_column(String(200))
    image: Mapped[str | None] = mapped_column(String(300))
    set_name: Mapped[str | None] = mapped_column(String(200))
    viewed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Collection(Base):
    """Una collezione di carte possedute (es. "le mie carte", "raccoglitore 151")."""

    __tablename__ = "collections"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(100))
    # "collection" (carte possedute) oppure "wishlist" (carte desiderate: non contano come possedute)
    kind: Mapped[str] = mapped_column(String(16), default="collection", server_default="collection")
    # Cosa vedono gli amici: "friends" (visibile) o "private"; i valori in euro solo se show_values.
    visibility: Mapped[str] = mapped_column(String(16), default="friends", server_default="friends")
    show_values: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    items: Mapped[list[CollectionItem]] = relationship(back_populates="collection", cascade="all, delete-orphan")


class CollectionItem(Base):
    """Una carta posseduta: stessa carta, variante e lingua di stampa = una riga con la quantità."""

    __tablename__ = "collection_items"
    __table_args__ = (UniqueConstraint("collection_id", "catalog_lang", "card_id", "variant", "lang",
                                       name="uq_item_card_variant_lang"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    collection_id: Mapped[int] = mapped_column(ForeignKey("collections.id"), index=True)
    card_id: Mapped[str] = mapped_column(String(64), index=True)
    catalog_lang: Mapped[str] = mapped_column(String(8))
    variant: Mapped[str] = mapped_column(String(16))              # normal / holo / reverse
    variant_label: Mapped[str | None] = mapped_column(String(64))  # es. "Anniversary Stamp" dall'import
    lang: Mapped[str] = mapped_column(String(8))                  # lingua di stampa della carta posseduta
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    # Copia dei dati della carta, per mostrare la collezione senza interrogare il catalogo.
    name: Mapped[str] = mapped_column(String(200))
    set_id: Mapped[str | None] = mapped_column(String(64))
    set_name: Mapped[str | None] = mapped_column(String(200))
    number_label: Mapped[str | None] = mapped_column(String(32))
    image: Mapped[str | None] = mapped_column(String(300))
    rarity: Mapped[str | None] = mapped_column(String(64))
    # Prezzo: prodotto Cardmarket e ultimo valore unitario noto (trend), aggiornato ogni notte dal job.
    id_product: Mapped[int | None] = mapped_column(Integer, index=True)
    shared_product: Mapped[bool] = mapped_column(Boolean, default=True)
    unit_price: Mapped[float | None] = mapped_column(Float)
    price_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    needs_review: Mapped[bool] = mapped_column(Boolean, default=False)  # abbinata all'import per nome: da controllare
    dex_ids: Mapped[str | None] = mapped_column(String(32))  # numeri Pokédex ("94" o "94,95"); "" = non è un Pokémon
    # Lista desideri: avviso quando il prezzo scende sotto questa cifra (una volta, finché non risale).
    target_price: Mapped[float | None] = mapped_column(Float)
    target_notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source: Mapped[str | None] = mapped_column(String(32))            # "app", "mydex"
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    collection: Mapped[Collection] = relationship(back_populates="items")


class PriceHistory(Base):
    """Prezzo giornaliero di un prodotto Cardmarket (per lo storico e l'analisi), una riga per giorno e campo."""

    __tablename__ = "price_history"
    __table_args__ = (UniqueConstraint("id_product", "fields", "day", name="uq_history_product_fields_day"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    id_product: Mapped[int] = mapped_column(Integer, index=True)
    fields: Mapped[str] = mapped_column(String(8))   # "base" o "holo" (campi "-holo" del price guide)
    day: Mapped[date] = mapped_column(Date)
    low: Mapped[float | None] = mapped_column(Float)
    trend: Mapped[float | None] = mapped_column(Float)
    avg: Mapped[float | None] = mapped_column(Float)
    avg1: Mapped[float | None] = mapped_column(Float)
    avg7: Mapped[float | None] = mapped_column(Float)
    avg30: Mapped[float | None] = mapped_column(Float)


class CollectionValue(Base):
    """Valore totale di una collezione giorno per giorno (grafico dell'andamento)."""

    __tablename__ = "collection_values"
    __table_args__ = (UniqueConstraint("collection_id", "day", name="uq_collection_value_day"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    collection_id: Mapped[int] = mapped_column(ForeignKey("collections.id", ondelete="CASCADE"), index=True)
    day: Mapped[date] = mapped_column(Date)
    value: Mapped[float] = mapped_column(Float)
    cards: Mapped[int] = mapped_column(Integer)


class ProductInfo(Base):
    """Prodotto Cardmarket (carta singola): espansione, "metacarta" (stessa carta in altre stampe) e data di uscita.

    Dall'elenco prodotti pubblico di Cardmarket; serve all'analisi (andamento del set, ristampe, età del set).
    """

    __tablename__ = "product_info"

    id_product: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    id_expansion: Mapped[int | None] = mapped_column(Integer, index=True)
    id_metacard: Mapped[int | None] = mapped_column(Integer, index=True)
    date_added: Mapped[date | None] = mapped_column(Date)
    name: Mapped[str | None] = mapped_column(String(200))


class SetStats(Base):
    """Andamento giornaliero di un'espansione Cardmarket, calcolato dal price guide su tutte le sue carte."""

    __tablename__ = "set_stats"
    __table_args__ = (UniqueConstraint("id_expansion", "day", name="uq_set_stats_day"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    id_expansion: Mapped[int] = mapped_column(Integer, index=True)
    day: Mapped[date] = mapped_column(Date)
    cards: Mapped[int] = mapped_column(Integer)                # carte con un prezzo di almeno 0,50 €
    total_trend: Mapped[float] = mapped_column(Float)          # somma dei prezzi di mercato (indice del set)
    median_change_7d: Mapped[float | None] = mapped_column(Float)   # frazione, es. -0.04 = -4%
    median_change_30d: Mapped[float | None] = mapped_column(Float)
    share_up_30d: Mapped[float | None] = mapped_column(Float)       # quota di carte sopra la media 30 gg


class PushSubscription(Base):
    """Iscrizione alle notifiche push dell'app (Web Push) di un dispositivo."""

    __tablename__ = "push_subscriptions"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    endpoint: Mapped[str] = mapped_column(String(600), unique=True)
    p256dh: Mapped[str] = mapped_column(String(200))
    auth: Mapped[str] = mapped_column(String(100))
    user_agent: Mapped[str | None] = mapped_column(String(300))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_ok_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failures: Mapped[int] = mapped_column(Integer, default=0)


class Invite(Base):
    """Invito a PokeVault: un link usa e getta, valido 7 giorni."""

    __tablename__ = "invites"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Friendship(Base):
    """Amicizia (una riga per direzione): permette di vedere le collezioni visibili e proporre scambi."""

    __tablename__ = "friendships"
    __table_args__ = (UniqueConstraint("user_id", "friend_id", name="uq_friendship"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    friend_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Trade(Base):
    """Proposta di scambio tra due amici.

    proposed -> accepted -> completed (entrambi confermano di aver ricevuto le carte; le carte si spostano da sole)
    proposed -> rejected | cancelled | countered (sostituita da una controproposta, parent_id)
    completed -> undone (annullato: le carte tornano dove erano)
    """

    __tablename__ = "trades"

    id: Mapped[int] = mapped_column(primary_key=True)
    proposer_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    recipient_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    parent_id: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16), default="proposed")
    message: Mapped[str | None] = mapped_column(String(500))
    proposer_confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    recipient_confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    moves: Mapped[list | None] = mapped_column(JSON)  # spostamenti fatti al completamento (per annullare)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    items: Mapped[list[TradeItem]] = relationship(back_populates="trade", cascade="all, delete-orphan")


class TradeItem(Base):
    """Una carta dello scambio: da chi parte, quante copie, e prezzo al momento della proposta."""

    __tablename__ = "trade_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    trade_id: Mapped[int] = mapped_column(ForeignKey("trades.id"), index=True)
    from_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    source_item_id: Mapped[int | None] = mapped_column(Integer)
    card_id: Mapped[str] = mapped_column(String(64))
    catalog_lang: Mapped[str] = mapped_column(String(8))
    variant: Mapped[str] = mapped_column(String(16))
    lang: Mapped[str] = mapped_column(String(8))
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    name: Mapped[str] = mapped_column(String(200))
    set_name: Mapped[str | None] = mapped_column(String(200))
    number_label: Mapped[str | None] = mapped_column(String(32))
    image: Mapped[str | None] = mapped_column(String(300))
    unit_price: Mapped[float | None] = mapped_column(Float)

    trade: Mapped[Trade] = relationship(back_populates="items")


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
