# Lakebase Git-Branching Demo — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A repeatable customer demo where each git worktree/branch is auto-mapped to an isolated copy-on-write Lakebase branch, DDL is captured with Alembic, and merge-to-main applies migrations to the production Lakebase branch via GitHub Actions.

**Architecture:** Streamlit todo app on SQLAlchemy+psycopg. A `post-checkout` git hook runs `lakebase-branch.sh` which creates a copy-on-write Lakebase branch from `production`, assigns a deterministic port, and writes `.env` (branch identity only — no secrets). The app resolves host and mints/refreshes a Databricks OAuth token live via the SDK. Deployed to Databricks Apps via a Databricks Asset Bundle; CI/CD via GitHub Actions on the field-eng runner group.

**Tech Stack:** Python 3.11, Streamlit, SQLAlchemy 2.x, psycopg 3, Alembic, Databricks SDK for Python, Databricks CLI v1.14.1, Databricks Asset Bundles, GitHub Actions, bash, make, `uv`.

**Spec:** `docs/superpowers/specs/2026-09-10-lakebase-branching-demo-design.md`

## Global Constraints

- Databricks profile: `DEFAULT`. Always pass `--profile DEFAULT` (each Bash call is a fresh shell).
- Lakebase project: `projects/todo-branching-demo`; source branch `production`; endpoint `primary`; pg database `databricks_postgres`.
- App schema: `todo_app`. Postgres `search_path` set to it via connection option.
- Connection URL: `postgresql+psycopg://{user}:{token}@{host}:5432/databricks_postgres?sslmode=require&connect_timeout=30&options=-csearch_path%3Dtodo_app`
- **No secrets in git.** `.env` is gitignored and holds no token. SP secret only in GitHub Actions secrets + local `.databrickscfg`.
- OAuth token = Postgres password, minted via SDK `postgres.generate_database_credential(name=<endpoint_path>)`, cached ~50 min, rewritten on each connect via SQLAlchemy `do_connect` event.
- Lakebase branch name = `{user_prefix}-{git_branch}` sanitized to RFC-1123 (lowercase, `[a-z0-9-]`, ≤63 chars).
- GitHub runners: `group: databricks-emu-protected-runner-group-small`, `labels: [linux-ubuntu-latest-2core-8gb]`, org `databricks-field-eng`. Pin CLI via `databricks/setup-cli`.
- Every commit message ends with: `Co-authored-by: Isaac <no-reply@databricks.com>`.

---

### Task 1: Project scaffold + Lakebase connection layer

**Files:**
- Create: `pyproject.toml`, `todo/__init__.py`, `todo/config.py`, `todo/session.py`, `todo/naming.py`
- Create: `tests/test_naming.py`
- Create: `.env.example`, `lakebase.config`

**Interfaces:**
- Produces: `todo.config.Settings` (pydantic-settings, env prefix `LAKEBASE_`) with fields
  `project_id`, `branch_id`, `endpoint_id="primary"`, `database="databricks_postgres"`,
  `schema="todo_app"`; methods `endpoint_path()`, `get_host()`, `get_user()`, `get_password()`, `database_url()`.
- Produces: `todo.session.get_engine()` → SQLAlchemy Engine with `do_connect` token refresh; `session_scope()` contextmanager.
- Produces: `todo.naming.lakebase_branch_name(user_prefix, git_branch)` and `todo.naming.port_for_branch(git_branch, base=8501)`.

- [ ] **Step 1: Write `pyproject.toml`** with deps: `streamlit`, `sqlalchemy>=2`, `psycopg[binary]>=3`, `alembic`, `databricks-sdk>=0.81`, `pydantic-settings`, `python-dotenv`; dev: `pytest`, `ruff`. Set `requires-python=">=3.11"`.

- [ ] **Step 2: Write the failing test** `tests/test_naming.py`:

```python
from todo.naming import lakebase_branch_name, port_for_branch

def test_branch_name_sanitizes_and_prefixes():
    assert lakebase_branch_name("rakesh.arumalla", "feature/priority") == "rakesh-arumalla-feature-priority"

def test_branch_name_truncates_to_63():
    name = lakebase_branch_name("rakesh", "x" * 100)
    assert len(name) <= 63 and name.startswith("rakesh-")

def test_port_is_deterministic_and_in_range():
    p1 = port_for_branch("feature/priority")
    p2 = port_for_branch("feature/priority")
    assert p1 == p2 and 8502 <= p1 <= 8599

def test_production_maps_to_base_port():
    assert port_for_branch("main", base=8501) == 8501
```

- [ ] **Step 3: Run test to verify it fails** — `uv run pytest tests/test_naming.py -v` → FAIL (module not found).

- [ ] **Step 4: Implement `todo/naming.py`:**

```python
import hashlib, re

def _slug(s: str) -> str:
    s = s.lower().replace(".", "-").replace("/", "-").replace("_", "-")
    s = re.sub(r"[^a-z0-9-]", "-", s)
    return re.sub(r"-+", "-", s).strip("-")

def lakebase_branch_name(user_prefix: str, git_branch: str) -> str:
    name = f"{_slug(user_prefix)}-{_slug(git_branch)}"
    return name[:63].strip("-")

def port_for_branch(git_branch: str, base: int = 8501) -> int:
    if git_branch in ("main", "master", "production"):
        return base
    h = int(hashlib.sha1(git_branch.encode()).hexdigest(), 16)
    return 8502 + (h % 98)  # 8502..8599
```

- [ ] **Step 5: Run test to verify it passes** — `uv run pytest tests/test_naming.py -v` → PASS.

- [ ] **Step 6: Implement `todo/config.py`** — `Settings(BaseSettings)` env prefix `LAKEBASE_`; `endpoint_path()` returns `projects/{project_id}/branches/{branch_id}/endpoints/{endpoint_id}`; `get_host()` via `WorkspaceClient().postgres.get_endpoint(name=endpoint_path()).status.hosts.host`; `get_user()` = `w.config.client_id or w.current_user.me().user_name`; `get_password()` via a module-level `_TokenManager` (cache key = endpoint_path, expiry now+50min, value = `w.postgres.generate_database_credential(name=endpoint_path()).token`); `database_url()` builds the URL from Global Constraints with `quote_plus` on user+token. `WorkspaceClient()` uses ambient auth (profile via `DATABRICKS_CONFIG_PROFILE` or default).

- [ ] **Step 7: Implement `todo/session.py`** — `get_engine()` = `create_engine(settings.database_url(), pool_pre_ping=True, pool_recycle=1800)`; register `@event.listens_for(engine, "do_connect")` that sets `cparams["password"] = settings.get_password()` each connect; `session_scope()` yields a `Session` with commit/rollback.

- [ ] **Step 8: Write `.env.example`** (identifiers only, no secrets):

```
DATABRICKS_CONFIG_PROFILE=DEFAULT
LAKEBASE_PROJECT_ID=todo-branching-demo
LAKEBASE_BRANCH_ID=production
LAKEBASE_ENDPOINT_ID=primary
LAKEBASE_DATABASE=databricks_postgres
LAKEBASE_SCHEMA=todo_app
STREAMLIT_PORT=8501
```
And `lakebase.config` (sourced by bash hook): `LAKEBASE_PROJECT_ID=todo-branching-demo`, `LAKEBASE_SOURCE_BRANCH=production`, `LAKEBASE_BRANCH_TTL=21600s`, `LAKEBASE_SCHEMA=todo_app`.

- [ ] **Step 9: Connectivity check** — create local `.env` from example, then:
  `DATABRICKS_CONFIG_PROFILE=DEFAULT uv run python -c "from todo.session import get_engine; from sqlalchemy import text; print(get_engine().connect().execute(text('select version()')).scalar())"`
  Expected: prints `PostgreSQL 17...`. **This is the "app connects to Lakebase" gate.**

- [ ] **Step 10: Commit** — `git add pyproject.toml todo tests .env.example lakebase.config && git commit` (message + Co-authored-by trailer).

---

### Task 2: Alembic + initial migration + seed (production baseline)

**Files:**
- Create: `alembic.ini`, `alembic/env.py`, `alembic/script.py.mako`, `alembic/versions/0001_initial.py`
- Create: `todo/models.py`, `scripts/seed.py`

**Interfaces:**
- Consumes: `todo.config.Settings`, `todo.session` from Task 1.
- Produces: `todo.models.Base`, `todo.models.Todo` (columns: `id` int PK, `title` text not null, `is_done` bool default false, `created_at` timestamptz default now()).
- Produces: schema `todo_app` + table `todos` on the target branch; `scripts/seed.py` idempotently loads 5 fixed rows.

- [ ] **Step 1: Implement `todo/models.py`** — SQLAlchemy 2.x declarative `Base`, `Todo` mapped class in schema `todo_app` (`__table_args__ = {"schema": "todo_app"}`).

- [ ] **Step 2: `alembic.ini`** — `script_location = alembic`, `prepend_sys_path = .`, placeholder `sqlalchemy.url = postgresql://placeholder` (overridden by env.py).

- [ ] **Step 3: Implement `alembic/env.py`** — import `Settings`, `models.Base`; `SCHEMA = settings.schema`; online mode: `engine = create_engine(settings.database_url(), poolclass=pool.NullPool)`; register the same `do_connect` token refresh; on connect `CREATE SCHEMA IF NOT EXISTS "todo_app"` + commit; `context.configure(connection=..., target_metadata=Base.metadata, version_table_schema=SCHEMA, include_schemas=True)`. Offline mode raises `RuntimeError` (needs live SDK auth). Branch targeted via `LAKEBASE_BRANCH_ID` env var.

- [ ] **Step 4: Write `alembic/versions/0001_initial.py`** — `upgrade()`: `op.execute('CREATE SCHEMA IF NOT EXISTS todo_app')` then `op.create_table("todos", ... schema="todo_app")`; `downgrade()`: `op.drop_table("todos", schema="todo_app")`.

- [ ] **Step 5: Apply to production branch** —
  `DATABRICKS_CONFIG_PROFILE=DEFAULT LAKEBASE_BRANCH_ID=production uv run alembic upgrade head`
  Expected: `Running upgrade -> 0001, initial`.

- [ ] **Step 6: Verify table exists** — via `databricks psql --project todo-branching-demo` or the connectivity one-liner:
  `... python -c "from todo.session import get_engine; from sqlalchemy import text; print(get_engine().connect().execute(text(\"select count(*) from todo_app.todos\")).scalar())"`
  Expected: `0`.

- [ ] **Step 7: Write `scripts/seed.py`** — truncate `todo_app.todos` and insert 5 fixed demo rows (mix of done/not-done). Idempotent (truncate then insert).

- [ ] **Step 8: Seed production + verify** —
  `DATABRICKS_CONFIG_PROFILE=DEFAULT LAKEBASE_BRANCH_ID=production uv run python scripts/seed.py`
  then re-run the count from Step 6 → Expected: `5`.

- [ ] **Step 9: Commit** — `git add alembic alembic.ini todo/models.py scripts/seed.py && git commit`.

---

### Task 3: Streamlit todo app with environment banner

**Files:**
- Create: `app.py`, `app.yaml` (Databricks Apps entrypoint — added here, used in Task 6)

**Interfaces:**
- Consumes: `todo.session.session_scope`, `todo.models.Todo`, `todo.config.Settings`, `todo.naming`.
- Produces: runnable Streamlit UI: add todo, toggle done, delete; top **env banner** showing git branch (from `GIT_BRANCH` env or `main`), Lakebase branch (`settings.branch_id`), host (`settings.get_host()`), and live row count.

- [ ] **Step 1: Implement `app.py`** — banner via `st.info(...)` colored per branch; a form to add a todo; a list with checkboxes to toggle `is_done` and a delete button; reads `STREAMLIT_PORT` only for display. Use `session_scope()` for all DB ops. Show `priority`/`due_date` columns *only if present* (introspect `Todo.__table__.columns`) so the same `app.py` renders on every branch.

- [ ] **Step 2: `app.yaml`** — `command: ["bash","-c","alembic upgrade head && streamlit run app.py --server.port 8000 --server.address 0.0.0.0"]`.

- [ ] **Step 3: Run locally against production** —
  `DATABRICKS_CONFIG_PROFILE=DEFAULT LAKEBASE_BRANCH_ID=production uv run streamlit run app.py --server.port 8501 --server.headless true` (run backgrounded).

- [ ] **Step 4: Verify UI** — use the `fe-specialized-agents:web-devloop-tester` agent (or curl `http://localhost:8501` and check HTTP 200 + Chrome DevTools MCP screenshot) to confirm the 5 seeded todos render and the banner shows `production`. Add a todo via UI, confirm count → 6, then delete it.

- [ ] **Step 5: Commit** — `git add app.py app.yaml && git commit`.

---

### Task 4: Git hook auto-branching + Makefile

**Files:**
- Create: `.githooks/post-checkout`, `scripts/lakebase-branch.sh`, `scripts/lakebase-cleanup.sh`, `Makefile`

**Interfaces:**
- Consumes: `lakebase.config`, `todo.naming` (script calls `python -c` for name/port).
- Produces: on `git checkout`/`git worktree add`, an isolated Lakebase branch + a `.env` in the worktree pointing at it + a derived `STREAMLIT_PORT`.

- [ ] **Step 1: Implement `scripts/lakebase-branch.sh`** (`set -euo pipefail`): source `lakebase.config`; `USER_EMAIL=$(databricks current-user me --profile DEFAULT -o json | python3 -c 'import json,sys;print(json.load(sys.stdin)["userName"])')`; `GIT_BRANCH=$(git rev-parse --abbrev-ref HEAD)`; skip if branch in `main/master`; compute `LB_BRANCH` and `PORT` via `python3 -c "from todo.naming import ..."`; idempotent create:
```bash
BR=projects/$LAKEBASE_PROJECT_ID/branches/$LB_BRANCH
if ! databricks postgres get-branch "$BR" --profile DEFAULT -o json >/dev/null 2>&1; then
  databricks postgres create-branch projects/$LAKEBASE_PROJECT_ID "$LB_BRANCH" \
    --json '{"spec":{"source_branch":"projects/'"$LAKEBASE_PROJECT_ID"'/branches/'"$LAKEBASE_SOURCE_BRANCH"'","ttl":"'"$LAKEBASE_BRANCH_TTL"'"}}' \
    --profile DEFAULT
  # reuse production `primary` endpoint name? No — create a RW endpoint on the new branch:
  databricks postgres create-endpoint "$BR" primary \
    --json '{"spec":{"endpoint_type":"ENDPOINT_TYPE_READ_WRITE","autoscaling_limit_min_cu":0.5,"autoscaling_limit_max_cu":2.0,"suspend_timeout_duration":"600s"}}' \
    --profile DEFAULT
fi
```
then write `.env` (identifiers only): `LAKEBASE_BRANCH_ID=$LB_BRANCH`, `STREAMLIT_PORT=$PORT`, plus the standard identifiers and `GIT_BRANCH=$GIT_BRANCH`. Non-fatal on error (warn).

- [ ] **Step 2: Implement `.githooks/post-checkout`** — args `$1 prev $2 new $3 flag`; `[[ "$3" == "1" ]] || exit 0`; run `bash "$(git rev-parse --show-toplevel)/scripts/lakebase-branch.sh"` inside `if ... else warn`; always `exit 0`.

- [ ] **Step 3: Implement `Makefile`** targets: `hooks` (`git config core.hooksPath .githooks`); `feature` (`git worktree add ../$(notdir $(NAME)) -b $(NAME)`); `run` (`uv run streamlit run app.py --server.port $$(grep STREAMLIT_PORT .env | cut -d= -f2)`); `migrate` (`uv run alembic upgrade head`); `migrate-new` (prompt msg → `alembic revision -m`); `branch-list` (`databricks postgres list-branches projects/todo-branching-demo --profile DEFAULT`); `cleanup` (calls `lakebase-cleanup.sh`); `seed`. All load `.env`.

- [ ] **Step 4: Implement `scripts/lakebase-cleanup.sh`** — delete a named LB branch (`delete-branch`) after unprotecting; and a mode to `git worktree remove`.

- [ ] **Step 5: Enable hooks + test worktree flow** —
  `make hooks` then `make feature NAME=feature/priority`.
  Expected: hook fires, `databricks postgres list-branches` shows `{user}-feature-priority` in READY state; the new worktree `../priority/.env` has `LAKEBASE_BRANCH_ID={user}-feature-priority` and a port in 8502–8599.

- [ ] **Step 6: Verify isolation** — in the worktree run `make migrate` (only 0001 so far → no-op), `make seed`, `make run`; confirm the app serves on its branch port. Add a todo in the worktree; confirm production (`:8501`) row count is unchanged.

- [ ] **Step 7: Commit** — `git add .githooks scripts Makefile && git commit` (on `main`, after removing the test worktree/branch via `make cleanup`).

---

### Task 5: Pre-stage the two demo feature branches

**Files:**
- Create (on branch `demo/feature-priority`): `alembic/versions/0002_add_priority.py`, edits to `todo/models.py`
- Create (on branch `demo/fix-due-dates`): `alembic/versions/0002_add_due_date.py`, edits to `todo/models.py`

**Interfaces:**
- Consumes: everything from Tasks 1–4.
- Produces: two long-lived git branches, each adding one column + migration, kept in the repo (not merged) for repeatable demos.

- [ ] **Step 1: Branch `demo/feature-priority`** — `git worktree add ../priority -b demo/feature-priority` (hook makes the LB branch). Add `priority` column to `Todo` (`String`, default `'medium'`); `uv run alembic revision -m "add priority"` and fill `upgrade()`/`downgrade()` (`op.add_column`/`op.drop_column` on `todo_app.todos`). `make migrate` against the branch; `make run`; verify priority badges render and production is unaffected. Commit + `git push -u origin demo/feature-priority`.

- [ ] **Step 2: Branch `demo/fix-due-dates`** — from `main`: `git worktree add ../duedates -b demo/fix-due-dates`. Add `due_date` column (`Date`, nullable); revision `add due_date`; migrate; run; verify overdue rows highlight red. Commit + push.

- [ ] **Step 3: Verify parallel isolation** — with production `:8501`, priority `:85xx`, and due-dates `:85yy` all running: `make branch-list` shows 3 branches; each app shows a different schema; `select column_name from information_schema.columns where table_name='todos'` differs per branch. **This is the copy-on-write punchline.**

- [ ] **Step 4: Clean local worktrees** (keep remote branches) — `make cleanup` on each; branches remain on origin for demo use.

---

### Task 6: Databricks Asset Bundle + deploy to Databricks Apps

**Files:**
- Create: `databricks.yml`, `resources/todo_app.yml`

**Interfaces:**
- Consumes: `app.yaml`, the app code, migrations.
- Produces: deployed Databricks App on the `production` Lakebase branch; app SP owns `todo_app` schema.

- [ ] **Step 1: `databricks.yml`** — `bundle.name: todo-branching-demo`; variables `lakebase_project_id=todo-branching-demo`, `lakebase_branch=production`, `lakebase_database_id=databricks-postgres`, `lakebase_schema=todo_app`, `owner_email`; `include: [resources/*.yml]`; `targets.prod` with `mode: production` and `workspace.host` = your workspace host; `default: true` on prod (single-target demo).

- [ ] **Step 2: `resources/todo_app.yml`** — `resources.apps.todo_app` with `source_code_path`, env vars (`LAKEBASE_PROJECT_ID`, `LAKEBASE_BRANCH_ID=${var.lakebase_branch}`, `LAKEBASE_SCHEMA`, `LAKEBASE_ENDPOINT_ID=primary`, `LAKEBASE_DATABASE=databricks_postgres`), and a `postgres` resource:
```yaml
resources:
  - name: postgres
    postgres:
      branch: projects/${var.lakebase_project_id}/branches/${var.lakebase_branch}
      database: projects/${var.lakebase_project_id}/branches/${var.lakebase_branch}/databases/${var.lakebase_database_id}
      permission: CAN_CONNECT_AND_CREATE
```

- [ ] **Step 3: Validate** — `databricks bundle validate -t prod --profile DEFAULT` → no errors.

- [ ] **Step 4: Deploy** — `databricks bundle deploy -t prod --profile DEFAULT`, then start the app (`databricks bundle run -t prod todo_app --profile DEFAULT`). App startup runs `alembic upgrade head` (schema already exists → no-op; SP becomes owner if fresh).

- [ ] **Step 5: Verify deployed app** — `databricks apps get todo-branching-demo-todo-app --profile DEFAULT` → running; open the app URL, confirm the todo list renders against production. Record `service_principal_client_id` for Task 7 grants if needed.

- [ ] **Step 6: Commit** — `git add databricks.yml resources && git commit`.

---

### Task 7: Service principal + GitHub Actions CI/CD

**Files:**
- Create: `scripts/setup-service-principal.sh`, `.github/workflows/ci.yml`, `.github/workflows/deploy-prod.yml`

**Interfaces:**
- Consumes: DAB from Task 6.
- Produces: an M2M SP with workspace access + `databricks_superuser` on the Lakebase project; GitHub secrets `DATABRICKS_CLIENT_ID`, `DATABRICKS_CLIENT_SECRET`, var `DATABRICKS_HOST`; CI validates + migrates on an ephemeral branch; merge-to-main applies migration to production + redeploys.

- [ ] **Step 1: `scripts/setup-service-principal.sh`** — create SP via `databricks service-principals create`; create an OAuth secret (`databricks service-principals ... ` / account `create-obo-token` or `databricks service-principals secrets create`); grant it project access; then set GitHub secrets/vars via `gh secret set` / `gh variable set` on `rakesh-arumalla_data/todo-branching-demo`. Print nothing sensitive to logs (mask). **Requires interactive `gh auth` — the script checks and instructs the user to run `! gh auth login` if needed.**

- [ ] **Step 2: `.github/workflows/ci.yml`** (on `pull_request` to `main`):
```yaml
runs-on:
  group: databricks-emu-protected-runner-group-small
  labels: [linux-ubuntu-latest-2core-8gb]
env:
  DATABRICKS_HOST: ${{ vars.DATABRICKS_HOST }}
  DATABRICKS_CLIENT_ID: ${{ secrets.DATABRICKS_CLIENT_ID }}
  DATABRICKS_CLIENT_SECRET: ${{ secrets.DATABRICKS_CLIENT_SECRET }}
```
steps: checkout → `databricks/setup-cli@v0.x` (pin) → `astral-sh/setup-uv` → `uv sync` → `uv run pytest` → `uv run ruff check` → `databricks bundle validate -t prod` → create ephemeral CI Lakebase branch `ci-pr-${{ github.event.number }}` (ttl 3600s) → `LAKEBASE_BRANCH_ID=ci-pr-... uv run alembic upgrade head` → delete the CI branch (in `if: always()`).

- [ ] **Step 3: `.github/workflows/deploy-prod.yml`** (on `push` to `main`): same runner + env; checkout → setup-cli → setup-uv → `uv sync` → `LAKEBASE_BRANCH_ID=production uv run alembic upgrade head` → `databricks bundle deploy -t prod` → `databricks bundle run -t prod todo_app`.

- [ ] **Step 4: Run setup + verify secrets** — `bash scripts/setup-service-principal.sh` (after `gh auth`); `gh secret list` shows the two secrets; `gh variable list` shows `DATABRICKS_HOST`.

- [ ] **Step 5: End-to-end CI test** — push `feature/priority` content as a real PR: open PR, confirm CI workflow runs green on the field-eng runner (ephemeral branch created + migrated + deleted). Do **not** merge yet.

- [ ] **Step 6: End-to-end prod-apply test** — merge the PR; confirm `deploy-prod` runs, `alembic upgrade head` adds `priority` to the **production** branch, and the deployed app redeploys with priority visible. Verify `information_schema.columns` on production now includes `priority`.

- [ ] **Step 7: Commit** — the workflows/scripts are committed as part of the PR branch used above.

---

### Task 8: Reset script, baseline tag, README + DEMO

**Files:**
- Create: `scripts/reset-demo.sh`, `README.md`, `DEMO.md`

**Interfaces:**
- Consumes: all prior tasks.
- Produces: `make reset-demo` restoring baseline; docs with step-by-step setup + demo script.

- [ ] **Step 1: `scripts/reset-demo.sh`** (confirmation-gated, `read -p "Type RESET to confirm"`): (a) list + delete all non-`production` Lakebase branches (unprotect first); (b) `LAKEBASE_BRANCH_ID=production uv run alembic downgrade 0001` (drops feature columns) — or downgrade to the baseline rev; (c) `LAKEBASE_BRANCH_ID=production uv run python scripts/seed.py`; (d) `git checkout main && git reset --hard v0-baseline && git push --force-with-lease origin main`; (e) `git worktree prune` + remove local worktrees. Add `reset-demo` Make target.

- [ ] **Step 2: Establish baseline tag** — after production is at `0001` + seeded and `main` holds Tasks 1–4,6,8 (not the feature migration): `git tag v0-baseline && git push origin v0-baseline`.

- [ ] **Step 3: Write `README.md`** — prerequisites (CLI, uv, gh, profile), one-time setup (`make hooks`, initial migrate+seed, `make deploy`, `bash scripts/setup-service-principal.sh`, tag), and the branching concept explained. No secrets.

- [ ] **Step 4: Write `DEMO.md`** — the exact live-demo script from the spec (baseline → `make feature` → migrate → run → parallel worktree → PR → merge → prod apply → `make reset-demo`), with copy-paste commands and "what to say" notes.

- [ ] **Step 5: Verify reset** — from a demo end-state (a feature merged to production), run `make reset-demo`; confirm production `todos` has no `priority`/`due_date` column, 5 seeded rows, only `production` branch remains, and `git log` on `main` matches `v0-baseline`.

- [ ] **Step 6: Commit** — `git add scripts/reset-demo.sh README.md DEMO.md Makefile && git commit`.

---

## Self-Review

- **Spec coverage:** app-against-Lakebase (T1/T3), Alembic DDL capture (T2/T5), git-hook auto-branch + `.env` update (T4), copy-on-write isolation (T4/T5), DAB deploy (T6), SP OAuth + GitHub Actions merge-to-prod (T7), reusability/reset + docs (T8). All spec sections mapped.
- **Placeholders:** none — each step has concrete commands/code or exact file responsibilities.
- **Type consistency:** `Settings`, `endpoint_path()`, `get_host/get_user/get_password/database_url()`, `get_engine()/session_scope()`, `lakebase_branch_name()/port_for_branch()` used consistently across tasks.

---
This pull request and its description were written by Isaac.
