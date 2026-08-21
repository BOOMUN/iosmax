from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cryptography.fernet import Fernet
from pwdlib import PasswordHash
from sqlalchemy import delete, select
from sqlalchemy.orm import Session as DbSession

from .config import settings
from .models import Session, User


password_hash = PasswordHash.recommended()
COOKIE_NAME = "iosmax_session"


def _load_fernet() -> Fernet:
    key_path = settings.data_dir / "secret.key"
    if key_path.exists():
        key = key_path.read_bytes().strip()
    else:
        key = Fernet.generate_key()
        key_path.write_bytes(key)
    return Fernet(key)


fernet = _load_fernet()


def hash_password(password: str) -> str:
    return password_hash.hash(password)


def verify_password(password: str, encoded: str) -> bool:
    return password_hash.verify(password, encoded)


def encrypt_secret(value: str) -> str:
    return fernet.encrypt(value.encode()).decode()


def decrypt_secret(value: str | None) -> str | None:
    if not value:
        return None
    return fernet.decrypt(value.encode()).decode()


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_session(db: DbSession, user: User) -> tuple[str, datetime]:
    token = secrets.token_urlsafe(48)
    expires_at = datetime.now(timezone.utc) + timedelta(hours=settings.session_hours)
    db.add(Session(token_hash=token_digest(token), user_id=user.id, expires_at=expires_at))
    db.commit()
    return token, expires_at


def delete_session(db: DbSession, token: str | None) -> None:
    if not token:
        return
    db.execute(delete(Session).where(Session.token_hash == token_digest(token)))
    db.commit()


def user_from_session(db: DbSession, token: str | None) -> User | None:
    if not token:
        return None
    now = datetime.now(timezone.utc)
    record = db.scalar(select(Session).where(Session.token_hash == token_digest(token)))
    if record is None:
        return None
    expires_at = record.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at <= now:
        db.delete(record)
        db.commit()
        return None
    return db.get(User, record.user_id)


def seed_admin(db: DbSession) -> None:
    if db.scalar(select(User.id).limit(1)) is not None:
        return
    db.add(
        User(
            username=settings.admin_username,
            password_hash=hash_password(settings.admin_password),
            must_change_password=True,
        )
    )
    db.commit()

