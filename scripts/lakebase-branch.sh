#!/usr/bin/env bash
#
# Provision (or reuse) a Lakebase branch for the current git branch and write .env.
# Called automatically by .githooks/post-checkout, or manually. Non-destructive.
#
# - Lakebase branch name = {user}-{git-branch}, copy-on-write from production, TTL-expiring.
# - New branches auto-provision a `primary` endpoint, so we don't create one.
# - .env holds branch IDENTITY only — the app mints the OAuth token live via the SDK.
set -euo pipefail

REPO="$(git rev-parse --show-toplevel)"
source "${REPO}/lakebase.config"
PROFILE="${DATABRICKS_PROFILE:-DEFAULT}"

GIT_BRANCH="$(git rev-parse --abbrev-ref HEAD)"
case "$GIT_BRANCH" in
  main|master|production|HEAD)
    echo "ℹ️  On '$GIT_BRANCH' — leaving .env pointed at production (no branch created)."
    exit 0
    ;;
esac

command -v databricks >/dev/null || { echo "⚠️  databricks CLI not found"; exit 1; }

USER_EMAIL="$(databricks current-user me --profile "$PROFILE" -o json \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["userName"])')"
USER_PREFIX="${USER_EMAIL%%@*}"   # local part only, e.g. rakesh.arumalla

LB_BRANCH="$(python3 -c "import sys; sys.path.insert(0,'${REPO}'); \
  from todo.naming import lakebase_branch_name as f; print(f('${USER_PREFIX}','${GIT_BRANCH}'))")"
PORT="$(python3 -c "import sys; sys.path.insert(0,'${REPO}'); \
  from todo.naming import port_for_branch as f; print(f('${GIT_BRANCH}'))")"

PROJECT="projects/${LAKEBASE_PROJECT_ID}"
BR="${PROJECT}/branches/${LB_BRANCH}"

if databricks postgres get-branch "$BR" --profile "$PROFILE" >/dev/null 2>&1; then
  echo "✅ Lakebase branch already exists: ${LB_BRANCH}"
else
  echo "🌱 Creating Lakebase branch ${LB_BRANCH} (copy-on-write from ${LAKEBASE_SOURCE_BRANCH})..."
  databricks postgres create-branch "$PROJECT" "$LB_BRANCH" \
    --json '{"spec":{"source_branch":"'"${PROJECT}/branches/${LAKEBASE_SOURCE_BRANCH}"'","ttl":"'"${LAKEBASE_BRANCH_TTL}"'"}}' \
    --profile "$PROFILE" >/dev/null
  echo "✅ Created ${LB_BRANCH}"
  # Configure the auto-created primary endpoint to a fixed 1 CU. Scale-to-zero
  # (idle suspension) is enabled by default on the endpoint.
  echo "⚙️  Setting endpoint to 1 CU (scale-to-zero enabled)..."
  databricks postgres update-endpoint "${BR}/endpoints/primary" \
    spec.autoscaling_limit_min_cu,spec.autoscaling_limit_max_cu \
    --json '{"spec":{"autoscaling_limit_min_cu":1,"autoscaling_limit_max_cu":1}}' \
    --profile "$PROFILE" >/dev/null 2>&1 \
    && echo "✅ Endpoint: 1 CU, scale-to-zero enabled" \
    || echo "⚠️  Could not update endpoint config (using project defaults)"
fi

cat > "${REPO}/.env" <<EOF
# Auto-written by lakebase-branch.sh for git branch '${GIT_BRANCH}'. Identity only — no secrets.
DATABRICKS_CONFIG_PROFILE=${PROFILE}
LAKEBASE_PROJECT_ID=${LAKEBASE_PROJECT_ID}
LAKEBASE_BRANCH_ID=${LB_BRANCH}
LAKEBASE_ENDPOINT_ID=primary
LAKEBASE_DATABASE=${LAKEBASE_DATABASE}
LAKEBASE_SCHEMA=${LAKEBASE_SCHEMA}
STREAMLIT_PORT=${PORT}
GIT_BRANCH=${GIT_BRANCH}
EOF

echo "📝 Wrote .env → Lakebase branch '${LB_BRANCH}', local port ${PORT}"
echo "   Next: make migrate && make seed && make run"
