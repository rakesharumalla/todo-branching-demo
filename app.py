"""Lakebase branching demo — Streamlit todo app.

The same app.py runs on every git worktree / Lakebase branch. It reflects the `todos`
table at runtime, so optional columns added by feature-branch migrations (priority,
due_date) light up automatically — no per-branch UI code. A banner shows exactly which
git branch and Lakebase branch this window is talking to.
"""
from __future__ import annotations

import os
import subprocess
from datetime import date

import streamlit as st
from sqlalchemy import MetaData, Table, delete, insert, select, update

from todo.config import get_settings
from todo.session import get_engine

PRIORITY_COLORS = {"high": "#e74c3c", "medium": "#f39c12", "low": "#2ecc71"}


def git_branch() -> str:
    if os.environ.get("GIT_BRANCH"):
        return os.environ["GIT_BRANCH"]
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"], text=True
        ).strip()
    except Exception:  # noqa: BLE001
        return "main"


def reflect_todos() -> Table:
    md = MetaData()
    return Table("todos", md, autoload_with=get_engine(), schema="todo_app")


def render_banner(settings, todos: Table) -> None:
    gb = git_branch()
    is_prod = settings.branch_id in ("production", "main")
    from sqlalchemy import func

    with get_engine().connect() as c:
        n = c.execute(select(func.count()).select_from(todos)).scalar()
    color = "#2ecc71" if is_prod else "#3498db"
    st.markdown(
        f"""
        <div style="padding:12px 16px;border-radius:8px;background:{color}22;
             border-left:6px solid {color};margin-bottom:12px;font-size:0.95em">
        <b>git branch:</b> <code>{gb}</code>&nbsp;&nbsp;|&nbsp;&nbsp;
        <b>Lakebase branch:</b> <code>{settings.branch_id}</code>&nbsp;&nbsp;|&nbsp;&nbsp;
        <b>rows:</b> {n}&nbsp;&nbsp;|&nbsp;&nbsp;
        <b>schema:</b> <code>{settings.schema_name}</code><br/>
        <span style="font-size:0.85em;color:#666">host: {settings.get_host()}</span>
        </div>
        """,
        unsafe_allow_html=True,
    )


def main() -> None:
    settings = get_settings()
    st.set_page_config(page_title=f"Todos — {settings.branch_id}", page_icon="✅")
    st.title("✅ Lakebase Branching Todo")

    todos = reflect_todos()
    cols = set(todos.c.keys())
    has_priority = "priority" in cols
    has_due_date = "due_date" in cols

    render_banner(settings, todos)

    # --- add form ---
    with st.form("add", clear_on_submit=True):
        title = st.text_input("New todo")
        extra = {}
        c1, c2 = st.columns(2)
        if has_priority:
            extra["priority"] = c1.selectbox("Priority", ["high", "medium", "low"], index=1)
        if has_due_date:
            d = c2.date_input("Due date", value=None)
            extra["due_date"] = d if d else None
        if st.form_submit_button("Add") and title.strip():
            with get_engine().begin() as conn:
                conn.execute(insert(todos).values(title=title.strip(), is_done=False, **extra))
            st.rerun()

    # --- list ---
    order = [todos.c.is_done]
    if has_priority:
        # high -> low ordering
        pass
    with get_engine().connect() as conn:
        rows = conn.execute(select(todos).order_by(*order, todos.c.id)).mappings().all()

    if not rows:
        st.info("No todos yet — add one above.")

    for r in rows:
        line = st.columns([0.08, 0.62, 0.2, 0.1])
        done = line[0].checkbox("done", value=r["is_done"], key=f"d{r['id']}",
                                label_visibility="collapsed")
        label = f"~~{r['title']}~~" if r["is_done"] else r["title"]
        badges = ""
        if has_priority and r.get("priority"):
            p = r["priority"]
            badges += (
                f"<span style='background:{PRIORITY_COLORS.get(p, '#999')};color:white;"
                f"padding:1px 8px;border-radius:10px;font-size:0.75em'>{p}</span> "
            )
        if has_due_date and r.get("due_date"):
            overdue = r["due_date"] < date.today() and not r["is_done"]  # noqa: DTZ011
            col = "#e74c3c" if overdue else "#666"
            tag = " ⚠ overdue" if overdue else ""
            badges += (
                f"<span style='color:{col};font-size:0.8em'>📅 {r['due_date']}{tag}</span>"
            )
        line[1].markdown(f"{label}", unsafe_allow_html=True)
        line[2].markdown(badges, unsafe_allow_html=True)
        if done != r["is_done"]:
            with get_engine().begin() as conn:
                conn.execute(update(todos).where(todos.c.id == r["id"]).values(is_done=done))
            st.rerun()
        if line[3].button("🗑", key=f"x{r['id']}"):
            with get_engine().begin() as conn:
                conn.execute(delete(todos).where(todos.c.id == r["id"]))
            st.rerun()


if __name__ == "__main__":
    main()
