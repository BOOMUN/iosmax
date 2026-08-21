from fastapi import Cookie, Depends, HTTPException, status
from sqlalchemy.orm import Session as DbSession

from .database import SessionLocal
from .models import User
from .security import COOKIE_NAME, user_from_session


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_current_user(
    token: str | None = Cookie(default=None, alias=COOKIE_NAME),
    db: DbSession = Depends(get_db),
) -> User:
    user = user_from_session(db, token)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="请先登录")
    return user

