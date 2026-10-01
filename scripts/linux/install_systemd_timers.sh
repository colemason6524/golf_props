#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR=${PROJECT_DIR:-"$HOME/golf_props"}
UNIT_SOURCE_DIR="$PROJECT_DIR/scripts/linux/systemd"
UNIT_DIR=${XDG_CONFIG_HOME:-"$HOME/.config"}/systemd/user

for unit in sports-golf-forecast.service sports-golf-forecast.timer sports-golf-bovada.service sports-golf-bovada.timer; do
    if [[ ! -f "$UNIT_SOURCE_DIR/$unit" ]]; then
        printf 'Missing systemd unit source: %s\n' "$UNIT_SOURCE_DIR/$unit" >&2
        exit 1
    fi
done

mkdir -p "$UNIT_DIR"
install -m 0644 "$UNIT_SOURCE_DIR"/sports-golf-* "$UNIT_DIR/"
systemctl --user daemon-reload
systemctl --user enable --now sports-golf-forecast.timer sports-golf-bovada.timer
systemctl --user list-timers --all sports-golf-forecast.timer sports-golf-bovada.timer
