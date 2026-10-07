#!/usr/bin/env bash
set -euo pipefail

TASK=${1:?task name is required}
PROJECT_DIR=${PROJECT_DIR:-"$HOME/golf_props"}
ENV_FILE=${GOLF_PROPS_ENV_FILE:-"$HOME/.config/golf_props/env"}
PYTHON_EXE=${GOLF_PROPS_PYTHON_EXE:-"$PROJECT_DIR/.venv/bin/python"}
LOG_DIR="$PROJECT_DIR/logs"
LOCK_FILE=${GOLF_PROPS_LOCK_FILE:-"$HOME/.local/state/golf_props/run.lock"}

mkdir -p "$LOG_DIR" "$(dirname "$LOCK_FILE")"

if [[ -f "$ENV_FILE" ]]; then
    set -a
    # shellcheck disable=SC1090
    source "$ENV_FILE"
    set +a
fi

export TZ=${TZ:-America/New_York}
export PYTHONUNBUFFERED=1
export OPENBLAS_NUM_THREADS=${OPENBLAS_NUM_THREADS:-1}
export OMP_NUM_THREADS=${OMP_NUM_THREADS:-1}
export MKL_NUM_THREADS=${MKL_NUM_THREADS:-1}

if [[ ! -x "$PYTHON_EXE" ]]; then
    printf 'Project Python interpreter is unavailable: %s\n' "$PYTHON_EXE" >&2
    exit 1
fi

case "$TASK" in
    weekly-forecast)
        LOG_FILE="$LOG_DIR/weekly_forecast.log"
        TIMEOUT=30m
        COMMAND=("$PYTHON_EXE" -m golf_props.cli weekly-forecast)
        ;;
    bovada-collect)
        LOG_FILE="$LOG_DIR/bovada_collect.log"
        TIMEOUT=15m
        COMMAND=("$PYTHON_EXE" -m golf_props.cli collect-bovada-golf-odds)
        ;;
    *)
        printf 'Unknown task: %s\n' "$TASK" >&2
        exit 2
        ;;
esac

exec >>"$LOG_FILE" 2>&1
printf '%s  Starting %s\n' "$(date '+%Y-%m-%d %H:%M:%S %Z')" "$TASK"

cd "$PROJECT_DIR"
exec 9>"$LOCK_FILE"
printf '%s  Waiting for the shared task lock\n' "$(date '+%Y-%m-%d %H:%M:%S %Z')"
flock 9
printf '%s  Running: %s\n' "$(date '+%Y-%m-%d %H:%M:%S %Z')" "${COMMAND[*]}"

set +e
timeout --signal=TERM --kill-after=2m "$TIMEOUT" "${COMMAND[@]}"
EXIT_CODE=$?
set -e
printf '%s  Finished %s with exit code %s\n' \
    "$(date '+%Y-%m-%d %H:%M:%S %Z')" "$TASK" "$EXIT_CODE"
exit "$EXIT_CODE"
