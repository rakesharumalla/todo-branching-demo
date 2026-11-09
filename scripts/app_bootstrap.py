"""One-time app-side admin bootstrap (runs as the app service principal inside the App).

Only the app SP can drop the schema it owns, and it can only connect from inside the
deployed App. Gated by RESET_SCHEMA=1 so it never drops on a normal restart. After the
handover to a user-owned schema, this is a no-op and can be removed from app.yaml.
"""
from __future__ import annotations

import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from sqlalchemy import text

from todo.session import get_engine


def main() -> None:
    if os.environ.get("RESET_SCHEMA") != "1":
        print("app_bootstrap: RESET_SCHEMA != 1, nothing to do")
        return
    with get_engine().begin() as c:
        who = c.execute(text("select current_user")).scalar()
        c.execute(text("DROP SCHEMA IF EXISTS todo_app CASCADE"))
        print(f"app_bootstrap: dropped schema todo_app as {who}")


if __name__ == "__main__":
    main()
