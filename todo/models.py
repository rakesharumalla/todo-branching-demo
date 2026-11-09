"""SQLAlchemy models for the todo app (schema `todo_app`).

The base schema is intentionally minimal — the demo *adds* columns (priority, due_date)
on feature branches via Alembic migrations to show copy-on-write DDL isolation.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

SCHEMA = "todo_app"


class Base(DeclarativeBase):
    pass


class Todo(Base):
    __tablename__ = "todos"
    __table_args__ = {"schema": SCHEMA}  # noqa: RUF012 (SQLAlchemy idiom)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String, nullable=False)
    is_done: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
