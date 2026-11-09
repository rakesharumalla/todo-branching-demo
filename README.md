# Lakebase Git-Branching Demo

A Databricks Apps + **Lakebase Autoscaling** demo that maps a developer's git workflow onto
Lakebase's **copy-on-write database branching**. When you create a git worktree/branch for a
feature or fix, a git hook automatically provisions an isolated Lakebase branch (a copy-on-write
clone of `production`), points your local app at it, and runs on its own port — so your schema
and data changes never touch production. Schema changes are captured with **Alembic**, and on
merge to `main`, **GitHub Actions** applies the migration to the production Lakebase branch and
redeploys the app.

> The natural parallel: **git worktrees : your code :: Lakebase branches : your data.**

---

## What it demonstrates

- Each git branch/worktree → its own copy-on-write Lakebase branch (instant, cheap, 1 CU, scale-to-zero).
- A running Streamlit app per branch, on its own `localhost` port, each hitting its own Lakebase branch.
- DDL changes captured as Alembic migrations, applied per-branch in isolation.
- Merge to `main` → GitHub Actions migrates **production** and redeploys the Databricks App.
- One-command **reset** back to baseline so you can re-run the demo for the next customer.

## Architecture

```
git main  ─────────────────► Lakebase `production` ──► Databricks App (deployed via DAB)
   │
   ├─ worktree feature/priority ─► LB branch <you>-feature-priority ─► Streamlit :85xx
   └─ worktree fix/due-dates     ─► LB branch <you>-fix-due-dates    ─► Streamlit :85yy
        (copy-on-write from production; DDL isolated per branch)
```

**Ownership model (important):** your **user** owns the `todo_app` schema/tables on production.
Copy-on-write branches inherit that ownership, so you can run migrations (DDL) on feature branches
locally. The deployed app's service principal has **read/write (DML) grants only** and the app
**serves only** — migrations are applied by you (locally) and by CI (on merge). This is because
Lakebase's `databricks_superuser` role can DML/GRANT but cannot DDL objects owned by another
identity, and only the object owner (or a true superuser) can `ALTER`/`DROP`.

## Repository layout

| Path | Purpose |
|---|---|
| `app.py` | Streamlit todo app; reflects the table so `priority`/`due_date` light up when present |
| `todo/` | `config.py` (Lakebase settings + live OAuth token), `session.py` (engine + token refresh), `models.py`, `naming.py` |
| `alembic/` | `env.py` (targets the branch in `LAKEBASE_BRANCH_ID`) + `versions/` migrations |
| `scripts/` | `lakebase-branch.sh` (git-hook branch provisioner), `lakebase-cleanup.sh`, `seed.py`, `reset-demo.sh`, `app_bootstrap.py` |
| `.githooks/post-checkout` | Fires on checkout/worktree-add → provisions the branch + writes `.env` |
| `databricks.yml`, `resources/todo_app.yml`, `app.yaml` | Databricks Asset Bundle + Apps config |
| `Makefile` | Developer commands (`make help`) |

## Prerequisites

- Databricks CLI ≥ 1.14.1, authenticated: `databricks auth login --profile DEFAULT`
- [`uv`](https://docs.astral.sh/uv/), `gh` (GitHub CLI), and `git`
- A Lakebase Autoscaling project named `todo-branching-demo` (already provisioned here)

## One-time setup

```bash
# 1. Install deps + enable the git hook
make setup                      # uv sync + git config core.hooksPath .githooks

# 2. Point local .env at production (identifiers only — no secrets)
cp .env.example .env

# 3. Create the baseline schema + seed data on production (you own the objects)
LAKEBASE_BRANCH_ID=production uv run alembic upgrade head
LAKEBASE_BRANCH_ID=production uv run python scripts/seed.py

# 4. Deploy the app to Databricks Apps (production)
make deploy

# 5. Tag the clean baseline (used by reset-demo)
git tag v0-baseline && git push origin v0-baseline
```

## Everyday developer workflow

```bash
# Start a feature: creates a git worktree AND (via the hook) a copy-on-write Lakebase branch
make feature NAME=feature/priority
cd ../priority

# Make a schema change, capture it as a migration, apply it to THIS branch only
make migrate-new MSG="add priority"     # edit the generated migration + todo/models.py
make migrate                            # alembic upgrade head on your branch
make seed                               # optional: reset this branch's rows
make run                                # Streamlit on this branch's port (from .env)

# Production is untouched. Compare side-by-side by running the app on main too.
make branch-list                        # see all Lakebase branches

# Tear down when done
make cleanup NAME=feature/priority      # deletes the Lakebase branch + worktree
```

## Ship it — promote to production (manual)

GitHub-hosted runners are disabled for this repo and the IaC self-hosted runner isn't yet
accessible, so promotion to production is a **manual step you run** after merging (the same
migrations you tested on your branch, now applied to production — which you own):

```bash
# 1. Merge your feature branch into main (PR or fast-forward)
git checkout main && git merge feature/priority && git push

# 2. Apply the migration to the PRODUCTION Lakebase branch + redeploy the app
make promote        # = make migrate-prod (alembic upgrade head on production) + make deploy
```

`make migrate-prod` runs `alembic upgrade head` against the production branch (you own the
schema, so the DDL applies), and `make deploy` redeploys/restarts the Databricks App with the
new code. Refresh the app URL to see the change live.

> **Re-enabling automated CI/CD later:** once this repo has an accessible self-hosted runner,
> the GitHub Actions workflows (`ci.yml` for PRs, `deploy-prod.yml` for merges) can be restored
> from git history — set `runs-on:` to your working runner label. The commands they run are
> exactly `make migrate-prod` + `make deploy` (plus an ephemeral-branch check on PRs).

## Reset the demo (between customers)

```bash
make reset-demo     # deletes demo branches, downgrades prod to baseline, re-seeds,
                    # resets git main to v0-baseline, removes worktrees (confirmation-gated)
```

## Security

- **No secrets in git.** `.env` is gitignored and contains only identifiers (branch, port,
  schema). The app resolves the host and mints a short-lived Databricks OAuth token live via the
  SDK — no token is ever written to a file.
- Manual promotion authenticates with your local Databricks profile (`DEFAULT`) — no
  token stored anywhere in the repo.
- The pre-commit secret scanner blocks accidental credential commits.

See `docs/superpowers/specs/` for the design spec and `DEMO.md` for the live demo script.
