#!/usr/bin/env bash
# Bring up one isolated session env for a task. Safe to run from several
# parallel sessions at once: the worktree-add + port allocation are serialized
# with flock; the slow restore runs outside the lock so sessions overlap.
#
# Usage: wt-start.sh <slug>     # <slug> = branch name, e.g. kio-1234-cash-in-cogs
# Prints WORKTREE / BRANCH / URL / CONF / DB / PORT for the orchestrator.
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/wt-common.sh"

SLUG="${1:?usage: wt-start.sh <slug>}"
DB="$(db_name_for "$SLUG")"
WT_PATH="$WT_ROOT/$SLUG"
ENV_DIR="$WT_ENVROOT/$SLUG"
DATA_DIR="$ENV_DIR/data"
FARM="$DATA_DIR/addons/${ODOO_VERSION}"
CONF="$ENV_DIR/odoo.conf"

bash "$WT_SCRIPT_DIR/wt-bootstrap.sh"
ls "$BACKUP_DIR"/*.dump >/dev/null 2>&1 || {
    echo "ERROR: no prod seed dump in $BACKUP_DIR; ${BACKUP_HINT}, then retry" >&2; exit 1; }

mkdir -p "$ENV_DIR" "$DATA_DIR/sessions" "$DATA_DIR/filestore"

# --- critical section: worktree add + port allocation (serialized) ---
exec 9>"$LOCKFILE"
flock 9
git -C "$SRC_REPO" fetch -q origin "${CUSTOM_REPO_BRANCH}"
if git -C "$SRC_REPO" worktree list --porcelain | grep -qx "worktree $WT_PATH"; then
    :                                                                       # reuse
elif git -C "$SRC_REPO" show-ref --verify -q "refs/heads/$SLUG"; then
    git -C "$SRC_REPO" worktree add -q "$WT_PATH" "$SLUG"                    # branch exists
else
    git -C "$SRC_REPO" worktree add -q -b "$SLUG" "$WT_PATH" "origin/${CUSTOM_REPO_BRANCH}"
fi
if [ -f "$ENV_DIR/port" ]; then
    PORT="$(cat "$ENV_DIR/port")"
else
    USED="$( { cat "$WT_ENVROOT"/*/port 2>/dev/null; \
               ss -H -ltn 2>/dev/null | awk '{print $4}' | sed 's/.*://'; } | sort -u )"
    PORT=""
    for p in $(seq "$PORT_BASE" "$PORT_MAX"); do
        grep -qx "$p" <<<"$USED" || { PORT="$p"; break; }
    done
    [ -n "$PORT" ] || { echo "ERROR: no free port in [$PORT_BASE,$PORT_MAX]" >&2; exit 1; }
    echo "$PORT" > "$ENV_DIR/port"
fi
flock -u 9

# --- outside the lock (parallel): farm, conf, DB restore, filestore, service ---
# conf is written BEFORE the restore: wt-restore's `odoo neutralize` needs it
# (session data_dir/addons farm resolves the installed modules' neutralize.sql).
bash "$WT_SCRIPT_DIR/wt-link.sh" "$WT_PATH" "$FARM"

bash "$WT_SCRIPT_DIR/wt-config.sh" "$SLUG" "$PORT"

bash "$WT_SCRIPT_DIR/wt-restore.sh" "$SLUG"
mkdir -p "$DATA_DIR/filestore/$DB"
cp -an "$SEED_FILESTORE/." "$DATA_DIR/filestore/$DB/" 2>/dev/null || true

systemctl --user restart "odoo${SERVICE_SUFFIX}-wt@$SLUG.service"

echo "WORKTREE: $WT_PATH"
echo "BRANCH: $SLUG"
echo "URL: http://localhost:$PORT/web"
echo "CONF: $CONF"
echo "DB: $DB"
echo "PORT: $PORT"
