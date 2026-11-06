import os
from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=os.environ.get("GUPIAO_ENV_FILE", str(PROJECT_ROOT / ".env")),
        env_file_encoding="utf-8", extra="ignore",
    )
    app_env: str = "development"
    app_mode: str = "database"
    app_secret: SecretStr = SecretStr("")
    public_origin: str = "http://127.0.0.1:5173"
    allowed_hosts: str = "127.0.0.1,localhost"
    cookie_secure: bool = True
    session_hours: int = Field(default=24, ge=1, le=168)
    db_host: str = "127.0.0.1"
    db_port: int = Field(default=3306, ge=1, le=65535)
    db_name: str = "gupiao"
    db_user: str = "gupiao_app"
    db_password: SecretStr = SecretStr("")
    db_pool_size: int = Field(default=5, ge=1, le=20)
    db_max_overflow: int = Field(default=5, ge=0, le=20)
    market_proxy: str = ""

    @model_validator(mode="after")
    def validate_security(self):
        from urllib.parse import urlsplit
        if self.app_mode not in {"local", "database"}:
            raise ValueError("APP_MODE仅允许local或database")
        if self.app_mode == "database" and len(self.app_secret.get_secret_value()) < 32:
            raise ValueError("APP_SECRET必须至少32个字符，请生成独立随机密钥")
        if self.app_mode == "database" and not self.db_password.get_secret_value():
            raise ValueError("DB_PASSWORD不能为空")
        origin = urlsplit(self.public_origin)
        if origin.scheme not in {"http", "https"} or not origin.netloc or origin.path or origin.query or origin.fragment or origin.username or origin.password:
            raise ValueError("PUBLIC_ORIGIN必须是不含路径的HTTP或HTTPS来源地址")
        if self.app_env not in {"development", "production"}:
            raise ValueError("APP_ENV仅允许development或production")
        if self.app_mode == "local" and (self.app_env != "development" or origin.hostname not in {"127.0.0.1", "localhost", "::1"}):
            raise ValueError("本机免登录模式仅允许development环境和回环地址")
        hosts = [host.strip() for host in self.allowed_hosts.split(",") if host.strip()]
        if not hosts or any("*" in host for host in hosts):
            raise ValueError("ALLOWED_HOSTS必须明确列出主机名，不允许通配符")
        if self.app_env == "production" and (origin.scheme != "https" or not self.cookie_secure):
            raise ValueError("生产环境必须启用HTTPS和安全Cookie")
        return self


@lru_cache
def get_settings():
    return Settings()
