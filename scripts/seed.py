"""Idempotently seed the todo_app.todos table with fixed demo rows.

Runs against whatever branch LAKEBASE_BRANCH_ID points at. Truncate-then-insert so the
demo starts from an identical state every time (used by reset-demo).
"""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from sqlalchemy import text

from todo.session import get_engine

SEED_TODOS = [
    ("Prepare Lakebase branching demo", True),
    ("Review copy-on-write architecture", True),
    ("Add priority feature", False),
    ("Fix due-date handling", False),
    ("Ship to production via GitHub Actions", False),
]


def main() -> None:
    engine = get_engine()
    with engine.begin() as conn:
        conn.execute(text("TRUNCATE TABLE todo_app.todos RESTART IDENTITY"))
        conn.execute(
            text("INSERT INTO todo_app.todos (title, is_done) VALUES (:title, :is_done)"),
            [{"title": t, "is_done": d} for t, d in SEED_TODOS],
        )
        count = conn.execute(text("SELECT count(*) FROM todo_app.todos")).scalar()
    print(f"Seeded {count} todos into todo_app.todos")


if __name__ == "__main__":
    main()
