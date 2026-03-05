#!/bin/bash
# WRIT-FM Listener Response Daemon — turns listener messages into on-air segments
# Polls for unread messages every 30 seconds. When found, generates a short
# spoken response and drops it into the talk segment queue.
#
# Typical turnaround: ~2-3 minutes from message to audio in the queue.
# The streamer picks up new segments between its current playback items.

RADIO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
MESSAGES_FILE="$HOME/.writ/messages.json"
POLL_INTERVAL=30  # seconds between checks

# Allow Claude CLI to run inside tmux (may be blocked by parent Claude Code session)
unset CLAUDECODE

ts() { date +%H:%M; }

echo "[listener-daemon $(ts)] Starting. Polling every ${POLL_INTERVAL}s"

while true; do
    # Quick check: any unread messages?
    if [ -f "$MESSAGES_FILE" ]; then
        UNREAD=$(python3 -c "
import json, sys
try:
    msgs = json.load(open('$MESSAGES_FILE'))
    unread = [m for m in msgs if not m.get('read', False) and len(m.get('message','').strip()) >= 2]
    print(len(unread))
except: print(0)
" 2>/dev/null)
    else
        UNREAD=0
    fi

    if [ "$UNREAD" -gt 0 ] 2>/dev/null; then
        echo "[listener-daemon $(ts)] $UNREAD unread message(s) — generating response..."
        cd "$RADIO_DIR"
        uv run python mac/content_generator/listener_response_generator.py
        echo "[listener-daemon $(ts)] Done."
    fi

    sleep $POLL_INTERVAL
done
