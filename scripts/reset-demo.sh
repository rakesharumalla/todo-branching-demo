#!/usr/bin/env bash
#
# Restore the demo to its baseline so it can be re-run for another customer.
#   1. Delete every non-production Lakebase branch (feature/fix/ci branches).
#   2. Downgrade the production schema back to the baseline migration (0001).
#   3. Re-seed production with the fixed demo rows.
#   4. Reset git main to the v0-baseline tag (discards any merged feature) and force-push.
#   5. Remove local feature worktrees.
#
# Confirmation-gated. Run from the main repo root.
set -euo pipefail

REPO="$(git rev-parse --show-toplevel)"
source "${REPO}/lakebase.config"
PROFILE="${DATABRICKS_PROFILE:-DEFAULT}"
PROJECT="projects/${LAKEBASE_PROJECT_ID}"
BASELINE_TAG="${BASELINE_TAG:-v0-baseline}"

echo "This will reset the demo to baseline:"
echo "  • delete all non-production Lakebase branches in ${LAKEBASE_PROJECT_ID}"
echo "  • downgrade production schema to migration 0001 + re-seed"
echo "  • git reset main to ${BASELINE_TAG} and force-push"
echo "  • remove local feature worktrees"
read -r -p "Type RESET to confirm: " confirm
[[ "$confirm" == "RESET" ]] || { echo "Aborted."; exit 1; }

echo "==> 1/5 Deleting non-production Lakebase branches..."
databricks postgres list-branches "$PROJECT" --profile "$PROFILE" -o json \
  | python3 -c "import json,sys; [print(b['name'].split('/')[-1]) for b in json.load(sys.stdin)]" \
  | while read -r br; do
      [[ "$br" == "production" ]] && continue
      echo "   - deleting $br"
      databricks postgres delete-branch "${PROJECT}/branches/${br}" --profile "$PROFILE" >/dev/null 2>&1 || true
    done

echo "==> 2/5 Downgrading production schema to baseline (0001)..."
( cd "$REPO" && LAKEBASE_BRANCH_ID=production DATABRICKS_CONFIG_PROFILE="$PROFILE" \
    uv run alembic downgrade 0001 )

echo "==> 3/5 Re-seeding production..."
( cd "$REPO" && LAKEBASE_BRANCH_ID=production DATABRICKS_CONFIG_PROFILE="$PROFILE" \
    uv run python scripts/seed.py )

echo "==> 4/5 Resetting git main to ${BASELINE_TAG}..."
( cd "$REPO" && git checkout main && git reset --hard "${BASELINE_TAG}" \
    && git push --force-with-lease origin main )

echo "==> 5/5 Removing local feature worktrees..."
( cd "$REPO" && git worktree list --porcelain | awk '/^worktree /{print $2}' \
    | while read -r wt; do
        [[ "$wt" == "$REPO" ]] && continue
        echo "   - removing worktree $wt"
        git worktree remove "$wt" --force 2>/dev/null || true
      done
  git worktree prune )

echo "✅ Demo reset to baseline. Ready for the next run."
