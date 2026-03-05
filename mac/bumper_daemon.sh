#!/bin/bash
# WRIT-FM Bumper Daemon — continuously stock AI music bumpers
# Keeps each show at MIN_BUMPERS pre-generated tracks.
# Runs as a launchd agent; safe to kill and restart anytime.

RADIO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
MIN_BUMPERS=10
SLEEP_STOCKED=300    # 5min between checks when all shows are full
SLEEP_NO_SERVER=60   # 1min retry when music-gen.server is offline

ts() { date +%H:%M; }

echo "[bumper-daemon $(ts)] Starting. Target: ${MIN_BUMPERS} bumpers/show"

while true; do
    if ! curl -sf http://localhost:4009/health >/dev/null 2>&1; then
        echo "[bumper-daemon $(ts)] music-gen.server offline — retry in ${SLEEP_NO_SERVER}s"
        sleep $SLEEP_NO_SERVER
        continue
    fi

    cd "$RADIO_DIR"
    echo "[bumper-daemon $(ts)] Generating..."
    uv run python mac/content_generator/music_bumper_generator.py --all --min $MIN_BUMPERS

    echo "[bumper-daemon $(ts)] Done. Sleeping ${SLEEP_STOCKED}s..."
    sleep $SLEEP_STOCKED
done
