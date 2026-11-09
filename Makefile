# Lakebase Git-Branching Demo — developer commands.
# Local dev reads .env (written by the git hook). All Databricks calls use the DEFAULT profile.
.PHONY: help hooks feature run migrate migrate-new seed branch-list cleanup deploy setup reset-demo test migrate-prod promote

PROFILE ?= DEFAULT
PROJECT ?= todo-branching-demo
PORT = $(shell grep -E '^STREAMLIT_PORT=' .env 2>/dev/null | cut -d= -f2)

help:  ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-14s\033[0m %s\n",$$1,$$2}'

hooks:  ## Enable the git hooks (one-time, per clone)
	git config core.hooksPath .githooks
	@echo "✅ core.hooksPath = .githooks"

feature:  ## Create a worktree + Lakebase branch. Usage: make feature NAME=feature/priority
	@test -n "$(NAME)" || { echo "Usage: make feature NAME=feature/xyz"; exit 1; }
	git worktree add "../$(notdir $(NAME))" -b "$(NAME)"
	@echo "➡️  cd ../$(notdir $(NAME)) && make migrate && make seed && make run"

run:  ## Run the app locally on this branch's port (from .env)
	uv run streamlit run app.py --server.port $(PORT) --server.headless true

migrate:  ## Apply migrations to this branch (alembic upgrade head)
	uv run alembic upgrade head

migrate-new:  ## Create a new migration. Usage: make migrate-new MSG="add priority"
	@test -n "$(MSG)" || { echo 'Usage: make migrate-new MSG="add priority"'; exit 1; }
	uv run alembic revision -m "$(MSG)"

seed:  ## Seed this branch with fixed demo rows
	uv run python scripts/seed.py

branch-list:  ## List all Lakebase branches in the project
	databricks postgres list-branches projects/$(PROJECT) --profile $(PROFILE) -o json \
	  | python3 -c "import json,sys; [print(' -', b['name'].split('/')[-1]) for b in json.load(sys.stdin)]"

cleanup:  ## Delete this feature's Lakebase branch + worktree. Usage: make cleanup NAME=feature/priority
	@test -n "$(NAME)" || { echo "Usage: make cleanup NAME=feature/xyz"; exit 1; }
	bash scripts/lakebase-cleanup.sh "$(NAME)"
	-git worktree remove "../$(notdir $(NAME))" --force
	-git branch -D "$(NAME)"

test:  ## Run unit tests + lint
	uv run pytest -q && uv run ruff check .

deploy:  ## Deploy the app to Databricks Apps (production) via the bundle
	databricks bundle deploy -t prod --profile $(PROFILE)
	databricks bundle run -t prod todo_app --profile $(PROFILE)

migrate-prod:  ## Apply migrations to the PRODUCTION Lakebase branch (you own the schema)
	LAKEBASE_BRANCH_ID=production DATABRICKS_CONFIG_PROFILE=$(PROFILE) uv run alembic upgrade head
	LAKEBASE_BRANCH_ID=production DATABRICKS_CONFIG_PROFILE=$(PROFILE) uv run alembic current

promote: migrate-prod deploy  ## Manual promotion to production: migrate prod schema, then redeploy the app

setup:  ## One-time: enable hooks + install deps
	$(MAKE) hooks
	uv sync

reset-demo:  ## Restore baseline (drops demo branches, downgrades prod, resets git). Confirmation-gated.
	bash scripts/reset-demo.sh
