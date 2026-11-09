# Live Demo Script — Lakebase Branching ↔ Git Worktrees

~15 minutes. Goal: show that a developer's git workflow drives isolated, copy-on-write
Lakebase branches, and that merging to `main` + a one-command promote applies the schema change
to production.

**Before the call:** run `make reset-demo` (or verify baseline) so production has 5 seeded
todos, only the `production` branch exists, and `main` is at `v0-baseline`. Have the deployed
app URL open (`databricks apps get todo-branching-demo --profile DEFAULT` → app URL).

---

## 0. The premise (30s)

> "Git worktrees let you work on several branches at once, each in its own folder. Lakebase
> gives your **database** the same superpower: instant copy-on-write branches. We'll wire them
> together so every feature branch gets its own isolated database — and prove production never
> moves until we merge."

Show the deployed production app (a working todo list) and `make branch-list` (only `production`).

## 1. Start a feature — the DB branches itself (3 min)

```bash
make feature NAME=feature/priority
```
Narrate what just happened (the `post-checkout` hook printed it):
- created a **copy-on-write Lakebase branch** `<you>-feature-priority` from `production` (1 CU, scale-to-zero),
- wrote `.env` pointing this worktree at that branch, and picked a local port.

```bash
cd ../priority
cat .env                     # identifiers only — no secrets
```

## 2. Make a schema change, isolated to this branch (4 min)

Add a `priority` column. In the worktree, edit `todo/models.py` — add this line to the `Todo`
model (after `is_done`):
```python
    priority: Mapped[str] = mapped_column(String, nullable=False, server_default="medium")
```
Generate + fill the migration:
```bash
make migrate-new MSG="add priority"      # creates alembic/versions/000x_add_priority.py
```
In the new migration file, set the body to:
```python
def upgrade() -> None:
    op.add_column("todos",
        sa.Column("priority", sa.String(), nullable=False, server_default="medium"),
        schema="todo_app")

def downgrade() -> None:
    op.drop_column("todos", "priority", schema="todo_app")
```
Apply it to THIS branch and run:
```bash
make migrate                 # alembic upgrade head → adds `priority` to THIS branch only
make seed                    # fixed rows
make run                     # Streamlit on this branch's port
```
Open the branch app: **priority badges appear** (the app reflects the table and lights up the
new column automatically). Now open the **production** app side-by-side: **no priority column.**

> "Same app code, two databases. The feature branch has the new column and data; production is
> untouched. That clone was instant and costs almost nothing."

Optional wow — a **second feature running in parallel**: see section 2b for the "three windows,
three schemas" moment.

## 2b. Second feature: `fix/due-dates` (+ running branches in parallel)

Two ways to run this feature. Pick based on the story you want to tell.

### Mode A — parallel with priority (the "three windows" wow)

Branch `fix/due-dates` straight from the current baseline `main` (do this **before** merging
priority), so you end up with three independent databases at once: production (neither column),
priority (`priority`), due-dates (`due_date`).

```bash
# from the main repo (a fresh worktree off baseline main)
make feature NAME=fix/due-dates && cd ../due-dates
```

### Mode B — sequential, after priority is merged + promoted

If you've already merged priority into `main` and run `make promote`, then a new `fix/due-dates`
worktree forks from a production that already has `priority`, so this branch gets **both**
columns and its migration **chains after** priority's automatically (Alembic sets `down_revision`
to the current head — which is why we use `make migrate-new` / `--autogenerate`).

```bash
make feature NAME=fix/due-dates && cd ../due-dates   # forks from production-with-priority
```

### The code change (same for both modes)

Edit `todo/models.py` — this feature needs two extra imports plus one column. Update the import
lines to:
```python
from datetime import date, datetime                                   # add `date`
from sqlalchemy import Boolean, Date, DateTime, Integer, String, func  # add `Date`
```
and add to the `Todo` model (after `is_done`):
```python
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
```
Create the migration (autogenerate from the model, or `make migrate-new MSG="add due_date"` and
hand-write the body):
```python
def upgrade() -> None:
    op.add_column("todos", sa.Column("due_date", sa.Date(), nullable=True), schema="todo_app")

def downgrade() -> None:
    op.drop_column("todos", "due_date", schema="todo_app")
```
Apply, seed, and (optionally) set a couple of dates so "overdue" is visible:
```bash
make migrate && make seed
databricks psql --project todo-branching-demo -- \
  -c "update todo_app.todos set due_date = current_date - 2 where id = 3;"
make run
```
The app shows a **date picker** in the add form and a 📅 date with **red "overdue"** highlight —
automatic via table reflection, no `app.py` change.

### Running the worktrees in parallel

Each worktree's `.env` has its **own** `STREAMLIT_PORT` (the hook derives a distinct port per
branch), so nothing collides — just run each in its own terminal:

| Terminal | Directory | Command | Opens |
|---|---|---|---|
| 1 — production | `todo-branching-demo/` | `make run` | http://localhost:8501 |
| 2 — priority | `../priority/` | `make run` | http://localhost:85xx |
| 3 — due-dates | `../due-dates/` | `make run` | http://localhost:85yy |

`make run` blocks its terminal (Ctrl+C to stop) and prints the exact URL; you can also read the
port with `grep STREAMLIT_PORT .env`. Open all three tabs side-by-side:

- **production** → plain todos (no extra columns)
- **priority** → colored priority badges
- **due-dates** → due dates + overdue highlighting

Then `make branch-list` → **three branches, three schemas, one Lakebase project.** That's the
copy-on-write punchline: three isolated databases, each cloned instantly from production, none
affecting the others or prod.

> Tip: to run a window in the background instead of a dedicated terminal, use
> `nohup make run >/tmp/app-$(grep STREAMLIT_PORT .env | cut -d= -f2).log 2>&1 &`.

## 3. Ship it — merge + promote to production (5 min)

Commit the feature and merge to `main`:
```bash
cd ../priority
git add -A && git commit -m "feat: add priority to todos"
git push -u origin feature/priority        # open a PR, or merge directly:
cd ../todo-branching-demo
git checkout main && git merge feature/priority && git push
```

Now promote to production — **one command**, running the same migration you just tested, this
time against the production branch you own, then redeploying the app:
```bash
make promote        # = alembic upgrade head on production + databricks bundle deploy/run
```
Narrate: `make migrate-prod` applies the `priority` migration to the **production** Lakebase
branch; `make deploy` redeploys the Databricks App. Refresh the **production** app → **priority
is now live in production**, and the migration is recorded in git history.

> Why manual? GitHub-hosted runners are disabled for this repo and the self-hosted runner isn't
> wired up yet. The exact same commands run in CI once a runner is available (see README).

## 4. Reset for the next customer (1 min)

```bash
make reset-demo              # type RESET to confirm
```
- deletes all non-production Lakebase branches,
- downgrades production back to the baseline migration and re-seeds,
- resets `main` to `v0-baseline`,
- removes local worktrees.

`make branch-list` → only `production`. Ready to run again.

---

## Talking points / FAQ

- **How fast/cheap are branches?** Copy-on-write — no full copy; branches share storage with the
  parent and only diverge on writes. Endpoints run at 1 CU and scale to zero when idle.
- **Who owns what?** Your user owns the schema; the deployed app's service principal has
  read/write grants. Migrations are owned by developers (locally) and CI (on merge).
- **No secrets in git.** `.env` holds only identifiers; the app mints a short-lived OAuth token
  live via the Databricks SDK. Promotion authenticates with your local Databricks profile.
- **Rollback?** Alembic `downgrade` reverses DDL; `reset-demo` uses it to restore baseline.
