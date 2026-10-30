from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.core.database import Base


class AccountNote(Base):
    __tablename__ = "account_notes"
    __table_args__ = (UniqueConstraint("user_id", "account_key", "note_id", name="uq_account_note_owner"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    account_key: Mapped[str] = mapped_column(String(160), index=True)
    note_id: Mapped[str] = mapped_column(String(128))
    title: Mapped[str] = mapped_column(String(512), default="")
    cover_url: Mapped[str] = mapped_column(Text, default="")
    note_url: Mapped[str] = mapped_column(Text, default="")
    media_type: Mapped[str] = mapped_column(String(16), default="image")
    platform_status: Mapped[str] = mapped_column(String(256), default="")
    platform_status_code: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    published_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    views: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    likes: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    collects: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    comments: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    shares: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    source: Mapped[str] = mapped_column(String(16))
    in_latest_sync: Mapped[bool] = mapped_column(Boolean, default=True)
    synced_at: Mapped[datetime] = mapped_column(DateTime)


class AccountNoteSync(Base):
    __tablename__ = "account_note_syncs"
    __table_args__ = (UniqueConstraint("user_id", "account_key", name="uq_account_note_sync_owner"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    account_key: Mapped[str] = mapped_column(String(160), index=True)
    status: Mapped[str] = mapped_column(String(16), default="never")
    source: Mapped[str] = mapped_column(String(16), default="")
    message: Mapped[str] = mapped_column(String(512), default="")
    last_attempt_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    synced_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
