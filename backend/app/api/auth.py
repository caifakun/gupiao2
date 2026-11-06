import secrets
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..core.config import get_settings
from ..core.security import COOKIE_NAME, DUMMY_HASH, csrf_token, login_limiter, require_csrf, token_hash, verify_password
from ..db.models import User, UserSession
from ..db.session import get_database
from .dependencies import require_user
from .schemas import LoginInput

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login")
def login(payload: LoginInput, request: Request, response: Response, database: Session = Depends(get_database)):
    login_limiter.check(request.client.host if request.client else "unknown")
    user = database.scalar(select(User).where(User.username == payload.username.lower()))
    valid = verify_password(payload.password, user.password_hash if user else DUMMY_HASH)
    if not user or not valid or not user.active:
        raise HTTPException(401, "用户名或密码错误")
    settings = get_settings()
    now = datetime.utcnow()
    token = secrets.token_urlsafe(32)
    database.execute(delete(UserSession).where(UserSession.expires_at <= now))
    previous = database.scalars(select(UserSession).where(UserSession.user_id == user.id).order_by(UserSession.created_at.desc()).offset(9)).all()
    for session in previous:
        database.delete(session)
    database.add(UserSession(token_hash=token_hash(token), user_id=user.id, created_at=now, expires_at=now + timedelta(hours=settings.session_hours)))
    database.commit()
    response.set_cookie(COOKIE_NAME, token, max_age=settings.session_hours * 3600, httponly=True, secure=settings.cookie_secure, samesite="strict", path="/api")
    return {"user": {"id": user.id, "username": user.username}, "csrf_token": csrf_token(token)}


@router.get("/me")
def current_session(request: Request, user: User = Depends(require_user)):
    return {"user": {"id": user.id, "username": user.username}, "csrf_token": csrf_token(request.cookies[COOKIE_NAME])}


@router.post("/logout", dependencies=[Depends(require_csrf)])
def logout(request: Request, response: Response, user: User = Depends(require_user), database: Session = Depends(get_database)):
    database.execute(delete(UserSession).where(UserSession.token_hash == token_hash(request.cookies[COOKIE_NAME]), UserSession.user_id == user.id))
    database.commit()
    response.delete_cookie(COOKIE_NAME, path="/api", secure=get_settings().cookie_secure, httponly=True, samesite="strict")
    return {"ok": True}
