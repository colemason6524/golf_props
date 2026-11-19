#!/usr/bin/env bash
# Golf round-score O/U operations task runner (scheduling only).
#
#   run_props_ou_task.sh grade                     # daily 08:00 ET: settle finals
#   run_props_ou_task.sh capture --lines F.csv \
#       --event rsm-classic-2026 --round 2 --book draftkings-browser-read
#
# Its own lock, its own log, its own env. A props_ou run must never queue
# behind — or hold — the forecast run.lock or the Bovada lock. Capture is
# never timer-fired: the lines file is supplied per round in a plan.
set -u

TASK=${1:?task name is required (capture|grade)}
shift
PROJECT_DIR=${PROJECT_DIR:-"$HOME/golf_props"}
PYTHON_EXE=${GOLF_PYTHON_EXE:-"$PROJECT_DIR/.venv/bin/python"}
LOG_DIR="$PROJECT_DIR/logs"
LOCK_FILE=${PROPS_OU_LOCK_FILE:-"$HOME/.local/state/golf_props/props_ou.lock"}

mkdir -p "$LOG_DIR" "$(dirname "$LOCK_FILE")"

export TZ=${TZ:-America/Detroit}
export PYTHONUNBUFFERED=1

if [[ ! -x "$PYTHON_EXE" ]]; then
    PYTHON_EXE=/usr/bin/python3
fi
if [[ ! -x "$PYTHON_EXE" ]]; then
    printf 'Project Python interpreter is unavailable: %s\n' "$PYTHON_EXE" >&2
    exit 1
fi

case "$TASK" in
    capture|grade) ;;
    *) printf 'Unknown task: %s\n' "$TASK" >&2; exit 2 ;;
esac

LOG_FILE="$LOG_DIR/props_ou_${TASK}.log"
TIMEOUT=20m
COMMAND=("$PYTHON_EXE" scripts/props_ou_ops.py "$TASK" "$@")

exec >>"$LOG_FILE" 2>&1
printf '%s  Starting %s %s\n' "$(date '+%Y-%m-%d %H:%M:%S %Z')" "$TASK" "$*"

cd "$PROJECT_DIR" || exit 1
exec 9>"$LOCK_FILE"
printf '%s  Waiting for the props_ou lock\n' "$(date '+%Y-%m-%d %H:%M:%S %Z')"
flock 9
printf '%s  Running: %s\n' "$(date '+%Y-%m-%d %H:%M:%S %Z')" "${COMMAND[*]}"

timeout --signal=TERM --kill-after=2m "$TIMEOUT" "${COMMAND[@]}"
EXIT_CODE=$?
printf '%s  Finished %s with exit code %s\n' \
    "$(date '+%Y-%m-%d %H:%M:%S %Z')" "$TASK" "$EXIT_CODE"
exit "$EXIT_CODE"
