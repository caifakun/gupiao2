from functools import lru_cache

from sqlalchemy import create_engine
from sqlalchemy.engine import URL
from sqlalchemy.orm import sessionmaker

from ..core.config import get_settings


@lru_cache
def get_engine():
    settings = get_settings()
    if settings.app_mode == "local":
        raise RuntimeError("本机模式不允许访问数据库")
    address = URL.create(
        "mysql+pymysql", username=settings.db_user,
        password=settings.db_password.get_secret_value(),
        host=settings.db_host, port=settings.db_port, database=settings.db_name,
        query={"charset": "utf8mb4"},
    )
    return create_engine(
        address, pool_pre_ping=True, pool_recycle=1800,
        pool_size=settings.db_pool_size, max_overflow=settings.db_max_overflow,
        pool_timeout=10,
        connect_args={"connect_timeout": 5, "read_timeout": 15, "write_timeout": 15},
    )


def get_database():
    with sessionmaker(bind=get_engine(), expire_on_commit=False)() as database:
        try:
            yield database
        finally:
            database.rollback()
