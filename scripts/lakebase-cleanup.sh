#!/usr/bin/env bash
#
# Delete the Lakebase branch mapped to a git branch. Usage:
#   bash scripts/lakebase-cleanup.sh <git-branch>
# Never deletes production.
set -euo pipefail

REPO="$(git rev-parse --show-toplevel)"
source "${REPO}/lakebase.config"
PROFILE="${DATABRICKS_PROFILE:-DEFAULT}"

GIT_BRANCH="${1:?usage: lakebase-cleanup.sh <git-branch>}"
USER_EMAIL="$(databricks current-user me --profile "$PROFILE" -o json \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["userName"])')"
USER_PREFIX="${USER_EMAIL%%@*}"
LB_BRANCH="$(python3 -c "import sys; sys.path.insert(0,'${REPO}'); \
  from todo.naming import lakebase_branch_name as f; print(f('${USER_PREFIX}','${GIT_BRANCH}'))")"

if [[ "$LB_BRANCH" == *"production"* ]]; then
  echo "❌ Refusing to delete production."; exit 1
fi

PROJECT="projects/${LAKEBASE_PROJECT_ID}"
BR="${PROJECT}/branches/${LB_BRANCH}"
if databricks postgres get-branch "$BR" --profile "$PROFILE" >/dev/null 2>&1; then
  echo "🗑  Deleting Lakebase branch ${LB_BRANCH}..."
  databricks postgres delete-branch "$BR" --profile "$PROFILE" >/dev/null 2>&1 || {
    # unprotect then retry
    databricks postgres update-branch "$BR" spec.is_protected \
      --json '{"spec":{"is_protected":false}}' --profile "$PROFILE" >/dev/null 2>&1 || true
    databricks postgres delete-branch "$BR" --profile "$PROFILE" >/dev/null
  }
  echo "✅ Deleted ${LB_BRANCH}"
else
  echo "ℹ️  Lakebase branch ${LB_BRANCH} not found (already gone)."
fi
