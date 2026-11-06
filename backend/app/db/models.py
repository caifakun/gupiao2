from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, ForeignKeyConstraint, Integer, String, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime)


class UserSession(Base):
    __tablename__ = "user_sessions"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime)
    expires_at: Mapped[datetime] = mapped_column(DateTime, index=True)


class WorkspaceMeta(Base):
    __tablename__ = "workspace_meta"
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    revision: Mapped[int] = mapped_column(BigInteger, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime)


class WatchlistGroup(Base):
    __tablename__ = "watchlist_groups"
    __table_args__ = (UniqueConstraint("user_id", "name", name="uq_group_name"),)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    name: Mapped[str] = mapped_column(String(20))
    position: Mapped[int] = mapped_column(Integer)


class WatchlistStock(Base):
    __tablename__ = "watchlist_stocks"
    __table_args__ = (
        ForeignKeyConstraint(["user_id", "group_id"], ["watchlist_groups.user_id", "watchlist_groups.id"], ondelete="CASCADE"),
    )
    user_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    market: Mapped[str] = mapped_column(String(2), primary_key=True)
    code: Mapped[str] = mapped_column(String(6), primary_key=True)
    name: Mapped[str] = mapped_column(String(40))
    group_id: Mapped[str] = mapped_column(String(80))
    position: Mapped[int] = mapped_column(Integer)


class UserSettings(Base):
    __tablename__ = "user_settings"
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    view: Mapped[str] = mapped_column(String(8), default="list")
    layout: Mapped[int] = mapped_column(Integer, default=6)
