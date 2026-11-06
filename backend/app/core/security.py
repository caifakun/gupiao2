import hashlib
import hmac
import re
import secrets
import threading
import time
from collections import deque

from fastapi import HTTPException, Request

from .config import get_settings

COOKIE_NAME = "gupiao_session"


def password_hash(password):
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=16384, r=8, p=1, dklen=32)
    return f"scrypt${salt.hex()}${digest.hex()}"


def verify_password(password, encoded):
    try:
        scheme, salt, expected = encoded.split("$")
        if scheme != "scrypt":
            return False
        actual = hashlib.scrypt(password.encode("utf-8"), salt=bytes.fromhex(salt), n=16384, r=8, p=1, dklen=32)
        return hmac.compare_digest(actual.hex(), expected)
    except (ValueError, TypeError):
        return False


def token_hash(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def csrf_token(token):
    secret = get_settings().app_secret.get_secret_value().encode("utf-8")
    return hmac.new(secret, b"csrf:" + token.encode("utf-8"), hashlib.sha256).hexdigest()


def require_csrf(request: Request):
    token = request.cookies.get(COOKIE_NAME, "")
    supplied = request.headers.get("X-CSRF-Token", "")
    if not token or len(token) > 128 or not re.fullmatch(r"[0-9a-f]{64}", supplied) or not hmac.compare_digest(supplied, csrf_token(token)):
        raise HTTPException(403, "请求校验失败，请重新加载页面")


class LoginLimiter:
    def __init__(self):
        self.lock = threading.Lock()
        self.attempts = {}

    def check(self, address):
        now = time.monotonic()
        with self.lock:
            expired = [key for key, values in self.attempts.items() if not values or values[-1] <= now - 300]
            for key in expired:
                del self.attempts[key]
            if address not in self.attempts and len(self.attempts) >= 4096:
                raise HTTPException(429, "登录请求过多，请稍后重试", headers={"Retry-After": "300"})
            entries = self.attempts.setdefault(address, deque())
            while entries and entries[0] <= now - 300:
                entries.popleft()
            if len(entries) >= 10:
                raise HTTPException(429, "登录尝试过多，请5分钟后重试", headers={"Retry-After": "300"})
            entries.append(now)


login_limiter = LoginLimiter()
DUMMY_HASH = password_hash(secrets.token_urlsafe(32))
