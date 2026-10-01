#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR=${PROJECT_DIR:-"$HOME/golf_props"}
SESSION=${GOLF_PROPS_TMUX_SESSION:-golf-scheduler}

if tmux has-session -t "$SESSION" 2>/dev/null; then
    exit 0
fi

tmux new-session -d -s "$SESSION" -n weekly-forecast \
    "$PROJECT_DIR/scripts/linux/run_every_two_hours_tmux_task.sh weekly-forecast"
tmux new-window -d -t "$SESSION" -n bovada-collect \
    "$PROJECT_DIR/scripts/linux/run_selected_days_tmux_task.sh bovada-collect 08:56 1,3,4"
