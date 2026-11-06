from datetime import datetime

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.security import COOKIE_NAME, token_hash
from ..db.models import User, UserSession
from ..db.session import get_database


def require_user(request: Request, database: Session = Depends(get_database)):
    token = request.cookies.get(COOKIE_NAME, "")
    if not token or len(token) > 128:
        raise HTTPException(401, "请先登录")
    user = database.scalar(
        select(User).join(UserSession, UserSession.user_id == User.id).where(
            UserSession.token_hash == token_hash(token),
            UserSession.expires_at > datetime.utcnow(),
            User.active.is_(True),
        )
    )
    if user is None:
        raise HTTPException(401, "登录已过期，请重新登录")
    return user
