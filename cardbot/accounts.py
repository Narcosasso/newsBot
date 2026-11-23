"""Account dell'app: il proprietario entra con APP_PIN, gli amici invitati con il loro PIN personale.

Il PIN degli amici è salvato solo come impronta PBKDF2 con sale casuale; per entrare basta il PIN (che deve essere
diverso per ogni persona, così l'app sa chi sei senza chiederti il nome).
"""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets

from sqlalchemy.orm import Session

from cardbot.db import Collection, Friendship, User

ITERATIONS = 120_000
PIN_RE = re.compile(r"^\d{6,12}$")


def hash_pin(pin: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", pin.encode(), bytes.fromhex(salt), ITERATIONS).hex()
    return f"pbkdf2${ITERATIONS}${salt}${digest}"


def check_pin(pin: str, stored: str | None) -> bool:
    try:
        _, iterations, salt, digest = (stored or "").split("$")
    except ValueError:
        return False
    got = hashlib.pbkdf2_hmac("sha256", pin.encode(), bytes.fromhex(salt), int(iterations)).hex()
    return hmac.compare_digest(got, digest)


def user_by_pin(session: Session, pin: str) -> User | None:
    for user in session.query(User).filter(User.pin_hash.isnot(None)).all():
        if check_pin(pin, user.pin_hash):
            return user
    return None


def owner_wa_id(settings) -> str:
    return settings.app_wa_id or next(iter(sorted(settings.allowed_wa_id_set)), "app")


def is_owner(user: User, settings) -> bool:
    return user.wa_id == owner_wa_id(settings)


def is_app_only(user: User) -> bool:
    """Amico invitato: niente WhatsApp."""
    return user.wa_id.startswith("app:")


def display_name(user: User, settings=None) -> str:
    if user.display_name:
        return user.display_name
    return "Proprietario" if settings is not None and is_owner(user, settings) else "Collezionista"


def are_friends(session: Session, a: int, b: int) -> bool:
    return session.query(Friendship).filter_by(user_id=a, friend_id=b).count() > 0


def befriend(session: Session, a: int, b: int) -> None:
    for x, y in ((a, b), (b, a)):
        if not are_friends(session, x, y):
            session.add(Friendship(user_id=x, friend_id=y))
    session.flush()


def wishlist_of(session: Session, user: User) -> Collection:
    """La lista desideri dell'utente (creata al primo uso)."""
    found = session.query(Collection).filter_by(user_id=user.id, kind="wishlist").first()
    if found:
        return found
    c = Collection(user_id=user.id, name="Lista desideri", kind="wishlist", visibility="friends")
    session.add(c)
    session.flush()
    return c
