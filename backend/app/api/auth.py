from datetime import datetime, timezone

from fastapi import APIRouter, Cookie, Depends, HTTPException, Response, status
from sqlalchemy import delete, select
from sqlalchemy.orm import Session as DbSession

from ..config import settings
from ..dependencies import get_current_user, get_db
from ..models import Session, User
from ..schemas import LoginRequest, PasswordChangeRequest, UserResponse
from ..security import (
    COOKIE_NAME,
    create_session,
    delete_session,
    hash_password,
    verify_password,
)


router = APIRouter(prefix="/api/auth", tags=["auth"])


def user_response(user: User) -> UserResponse:
    return UserResponse(
        id=user.id,
        username=user.username,
        must_change_password=user.must_change_password,
    )


@router.post("/login", response_model=UserResponse)
def login(payload: LoginRequest, response: Response, db: DbSession = Depends(get_db)):
    user = db.scalar(select(User).where(User.username == payload.username))
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="账号或密码错误")
    db.execute(delete(Session).where(Session.expires_at < datetime.now(timezone.utc)))
    token, expires_at = create_session(db, user)
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="strict",
        expires=expires_at,
        max_age=settings.session_hours * 3600,
        path="/",
    )
    return user_response(user)


@router.get("/me", response_model=UserResponse)
def me(user: User = Depends(get_current_user)):
    return user_response(user)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    response: Response,
    token: str | None = Cookie(default=None, alias=COOKIE_NAME),
    db: DbSession = Depends(get_db),
):
    delete_session(db, token)
    response.delete_cookie(
        COOKIE_NAME,
        path="/",
        secure=settings.cookie_secure,
        httponly=True,
        samesite="strict",
    )


@router.post("/change-password", response_model=UserResponse)
def change_password(
    payload: PasswordChangeRequest,
    user: User = Depends(get_current_user),
    db: DbSession = Depends(get_db),
):
    if not verify_password(payload.current_password, user.password_hash):
        raise HTTPException(status_code=400, detail="当前密码不正确")
    if payload.current_password == payload.new_password:
        raise HTTPException(status_code=400, detail="新密码不能与当前密码相同")
    user.password_hash = hash_password(payload.new_password)
    user.must_change_password = False
    db.add(user)
    db.commit()
    db.refresh(user)
    return user_response(user)
