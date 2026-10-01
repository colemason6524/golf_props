#!/usr/bin/env bash
set -euo pipefail

TASK=${1:?task name is required}
RUN_TIME=${2:?HH:MM run time is required}
RUN_DAYS=${3:?comma-separated ISO weekdays are required}
PROJECT_DIR=${PROJECT_DIR:-"$HOME/golf_props"}
TIMEZONE=${GOLF_PROPS_TIMEZONE:-America/New_York}
SCHEDULER_LOG="$PROJECT_DIR/logs/tmux_scheduler.log"

mkdir -p "$PROJECT_DIR/logs"

while true; do
    NOW=$(date +%s)
    for OFFSET in {0..7}; do
        TARGET=$(TZ="$TIMEZONE" date --date="today + $OFFSET days $RUN_TIME" +%s)
        DAY=$(TZ="$TIMEZONE" date --date="@$TARGET" +%u)
        if (( TARGET > NOW )) && [[ ",$RUN_DAYS," == *",$DAY,"* ]]; then
            break
        fi
    done

    printf '%s  %s next run: %s\n' \
        "$(TZ="$TIMEZONE" date '+%Y-%m-%d %H:%M:%S %Z')" \
        "$TASK" \
        "$(TZ="$TIMEZONE" date --date="@$TARGET" '+%Y-%m-%d %H:%M:%S %Z')" \
        >>"$SCHEDULER_LOG"
    sleep "$((TARGET - NOW))"
    "$PROJECT_DIR/scripts/linux/run_linux_task.sh" "$TASK"
done
