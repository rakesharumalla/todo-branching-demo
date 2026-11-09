# Lakebase Git-Branching Demo — Design Spec

**Date:** 2026-09-10
**Author:** Rakesh Arumalla (Lakebase SA) + Isaac
**Status:** Approved (design), pending implementation

## Purpose

A simple, repeatable customer demo that showcases **Lakebase Autoscaling copy-on-write
database branching** mapped 1:1 onto a developer's git SDLC. When a developer creates a git
worktree/branch for a feature or fix, a git hook automatically provisions an isolated Lakebase
branch (copy-on-write from `production`) and points the local app at it — so local schema/data
changes never touch production. DDL changes are captured with Alembic. On merge to `main`,
GitHub Actions applies the migration to the production Lakebase branch and redeploys the app.

The demo must be **runnable many times against different customers** and **reset to a known
baseline in ~30s** between runs.

## Environment (fixed facts)

- **Databricks profile:** `DEFAULT` (host `https://<your-workspace>.cloud.databricks.com`)
- **Lakebase project (exists):** `projects/todo-branching-demo`
  - Branch: `production` → endpoint `primary` (host `<endpoint-host>`)
  - Database: `databricks-postgres` (pg name `databricks_postgres`), Postgres 17
- **GitHub repo:** `https://github.com/rakesh-arumalla_data/todo-branching-demo`
- **GitHub runners:** org `databricks-field-eng`, runner group
  `databricks-emu-protected-runner-group-small`, label `linux-ubuntu-latest-2core-8gb`
- **App schema (app/SP-owned):** `todo_app`

## Decisions (locked)

1. **App framework:** Streamlit (single-file UI, trivial per-worktree port, first-class on Databricks Apps).
2. **Demo topology:** git worktrees, one app per worktree on its own localhost port, all running at once.
3. **CI auth:** Databricks service principal M2M OAuth (client id/secret as GitHub secrets). No PATs.
4. **Deploy scope:** both — DAB-deployed app on `production`, plus local apps against per-branch Lakebase.
5. **`.env` contents:** branch *identity* only (`LAKEBASE_BRANCH_ID`, host, port, schema). The app
   resolves host and mints/refreshes the OAuth token live via the Databricks SDK. **No secret or
   token is written to any file.** This satisfies "point local at the branch DB" without stale tokens.
6. **Branch naming/lifecycle:** Lakebase branch = `{user}-{git-branch}` sanitized to RFC-1123,
   created copy-on-write from `production` with a ~6h TTL; explicit delete on cleanup.
7. **Schema ownership (revised after testing):** the **user** (`you@example.com`)
   owns the `todo_app` schema/tables on `production`. Discovered during build: Lakebase's
   `databricks_superuser` is **not** a true Postgres superuser (DML + GRANT only, **no DDL** on
   objects owned by another identity), and copy-on-write branches inherit the owner. If the app SP
   owned the schema, the user couldn't run migrations (ALTER) on feature branches. So: user owns
   (granted CREATE-on-database); forks inherit user ownership → local DDL works; the **app SP has
   DML grants only** and the app **serves only** (no startup migrations); migrations run locally
   (as the user) and via CI. One-time handover from the app-SP-created schema used
   `scripts/app_bootstrap.py` (`RESET_SCHEMA=1`) inside the deployed app (only the app SP could
   drop what it owned).
8. **Reusability:** pre-staged feature branches + a scripted `make reset-demo` restore baseline.

## Architecture

```
git main  ───────────────► Lakebase `production` ──► Databricks App (DAB-deployed)
   │
   ├─ worktree feature/priority ─► LB branch {user}-feature-priority ─► Streamlit :8502
   └─ worktree fix/due-dates     ─► LB branch {user}-fix-due-dates    ─► Streamlit :8503
        (copy-on-write from production; DDL isolated per branch)
```

### Components

| Area | Files | Role |
|---|---|---|
| App | `app.py`, `todo/config.py`, `todo/session.py`, `todo/models.py` | Streamlit todo CRUD + SQLAlchemy. Prominent env banner: git branch, Lakebase branch, host, row count. |
| Migrations | `alembic.ini`, `alembic/env.py`, `alembic/versions/*` | DDL as Alembic revisions. `env.py` creates schema + connects with live SDK OAuth token; targets branch via `LAKEBASE_BRANCH_ID`. |
| Git hook | `.githooks/post-checkout` → `scripts/lakebase-branch.sh` | On checkout/worktree-add: create LB branch, assign deterministic port, write `.env`. Non-fatal. |
| Scripts | `lakebase-branch.sh`, `lakebase-cleanup.sh`, `reset-demo.sh`, `setup-service-principal.sh` | Branch lifecycle + one-time SP/secrets setup + full reset. |
| Make | `Makefile` | `setup`, `seed`, `deploy`, `feature NAME=…`, `run`, `migrate`, `migrate-new`, `branch-list`, `cleanup`, `reset-demo`. |
| DAB | `databricks.yml`, `resources/todo_app.yml` | Deploy app to Databricks Apps on `production`; app runs `alembic upgrade head` at startup. |
| CI/CD | `.github/workflows/ci.yml`, `deploy-prod.yml` | PR: bundle validate + migrate on ephemeral TTL CI branch + tests. Merge to main: `alembic upgrade head` on production + `bundle deploy`. field-eng runner group + SP OAuth. |
| Config/docs | `.env.example`, `lakebase.config`, `.gitignore`, `pyproject.toml`, `README.md`, `DEMO.md` | Step-by-step; secrets only in gitignored `.env`. |

### Connection pattern (both reference repos, load-bearing)
- URL: `postgresql+psycopg://{user}:{token}@{host}:5432/databricks_postgres?sslmode=require&options=-csearch_path%3Dtodo_app`
- OAuth token as password via SDK `postgres.generate_database_credential(endpoint=...)`, cached with ~50m TTL.
- SQLAlchemy `do_connect` event rewrites `cparams["password"]` each connect so pools survive 1h token expiry.
- Local user = `w.current_user.me().user_name`; deployed = SP `client_id`.

## Reusability / reset model

- **Pre-staged feature branches** `demo/feature-priority`, `demo/fix-due-dates` hold ready-made
  code + one clean Alembic migration each (with real `downgrade()`). Demos create worktrees from these.
- **`v0-baseline` git tag** marks the clean `main` state.
- **`make reset-demo`** (confirmation-gated): delete non-production LB branches → `alembic downgrade`
  production to baseline revision → re-seed fixed rows → `git reset --hard v0-baseline` +
  `--force-with-lease` push → remove local worktrees. ~30s back to baseline.
- **`make cleanup`** (light): delete demo LB branches + worktrees only; leaves production and git alone.

## Demo features (worktrees)

- `feature/priority` — `ALTER TABLE todos ADD COLUMN priority` → High/Med/Low colored badges + sort. Clean up/down.
- `fix/due-dates` — `ALTER TABLE todos ADD COLUMN due_date` → overdue items highlighted red. Clean up/down.

Independent single-column changes → three windows, three schemas, one project (copy-on-write punchline).

## Build & test order (verify each before next)

1. Streamlit app runs locally against `production` branch (baseline app works). ← "app against Lakebase" gate
2. Alembic wired; initial migration creates `todo_app` schema + `todos` table on production; `make seed`.
3. Git hook + `lakebase-branch.sh`: `git worktree add` auto-creates LB branch + `.env` + port; app isolated.
4. Two worktrees side-by-side; DDL migration on one branch; prove production untouched.
5. DAB deploy app to Databricks Apps (production); confirm SP owns schema.
6. Service principal + GitHub secrets; CI on PR; prod-apply on merge to main — tested via real feature→PR→merge.
7. Pre-stage `demo/*` branches, `v0-baseline` tag, `reset-demo`; README + DEMO.md polished.

## Non-goals / YAGNI
- No React/FastAPI frontend (Streamlit only). No Data API. No synced tables. No auth beyond Databricks OAuth.
- No per-branch Postgres role creation (project owner is superuser; deployed app uses its SP).

## Risks / mitigations
- **Token expiry mid-demo** → live SDK refresh + `do_connect` rewrite (no token in files).
- **Schema permission error** → deploy app first so SP owns schema; document the fix in README.
- **Force-push on reset** → confirmation prompt + `--force-with-lease`; dedicated demo repo.
- **CLI/SDK versions** → CLI v1.14.1 present (≥ required); pin CLI in CI via `databricks/setup-cli`.

## Security
- No secrets in git. `.env` gitignored (and holds no token anyway). SP client secret only in GitHub
  Actions secrets + local `.databrickscfg`. `.gitignore` covers `.env`, `.venv`, `__pycache__`, worktrees.

---
This pull request and its description were written by Isaac.
