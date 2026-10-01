#!/usr/bin/env bash
set -euo pipefail

TASK=${1:?task name is required}
PROJECT_DIR=${PROJECT_DIR:-"$HOME/golf_props"}
TIMEZONE=${GOLF_PROPS_TIMEZONE:-America/New_York}
SCHEDULER_LOG="$PROJECT_DIR/logs/tmux_scheduler.log"

mkdir -p "$PROJECT_DIR/logs"

while true; do
    NOW=$(date +%s)
    HOUR=$((10#$(TZ="$TIMEZONE" date +%H)))
    MINUTE=$((10#$(TZ="$TIMEZONE" date +%M)))
    if (( HOUR % 2 == 0 && MINUTE < 17 )); then
        TARGET_SPEC=$(printf 'today %02d:17' "$HOUR")
    elif (( HOUR >= 22 )); then
        TARGET_SPEC='tomorrow 00:17'
    else
        TARGET_SPEC=$(printf 'today %02d:17' "$((HOUR / 2 * 2 + 2))")
    fi
    TARGET=$(TZ="$TIMEZONE" date --date="$TARGET_SPEC" +%s)

    printf '%s  %s next run: %s\n' \
        "$(TZ="$TIMEZONE" date '+%Y-%m-%d %H:%M:%S %Z')" \
        "$TASK" \
        "$(TZ="$TIMEZONE" date --date="@$TARGET" '+%Y-%m-%d %H:%M:%S %Z')" \
        >>"$SCHEDULER_LOG"
    sleep "$((TARGET - NOW))"
    "$PROJECT_DIR/scripts/linux/run_linux_task.sh" "$TASK"
done
