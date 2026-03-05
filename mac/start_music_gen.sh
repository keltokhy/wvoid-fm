#!/bin/bash
# Start music-gen.server, bumper daemon, and listener daemon in dedicated tmux panes.
# Safe to run multiple times — kills existing instances first.
#
# Usage:
#   ./mac/start_music_gen.sh              # start all
#   ./mac/start_music_gen.sh server       # server only
#   ./mac/start_music_gen.sh daemon       # bumper daemon only
#   ./mac/start_music_gen.sh listener     # listener daemon only

set -euo pipefail

MUSIC_GEN_DIR="${MUSIC_GEN_DIR:-$(cd "$(dirname "$0")/../../music-gen.server" 2>/dev/null && pwd || echo "")}"
if [ -z "$MUSIC_GEN_DIR" ] || [ ! -d "$MUSIC_GEN_DIR" ]; then
    echo "Warning: music-gen.server not found. Set MUSIC_GEN_DIR or clone it alongside this repo."
    echo "  Expected: $(cd "$(dirname "$0")/../.." && pwd)/music-gen.server"
fi
RADIO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
SESSION="writ"

# Ensure writ tmux session exists
if ! tmux has-session -t "$SESSION" 2>/dev/null; then
    tmux new-session -d -s "$SESSION"
    echo "Created tmux session: $SESSION"
fi

start_server() {
    # Kill any existing music-gen server
    pkill -f "kortexa-music-gen" 2>/dev/null || true
    pkill -f "uvicorn.*music_gen" 2>/dev/null || true
    sleep 1

    # Create or reuse a window for the server
    if ! tmux list-windows -t "$SESSION" -F "#{window_name}" | python3 -c "import sys; sys.exit(0 if 'music-gen' in sys.stdin.read() else 1)" 2>/dev/null; then
        tmux new-window -t "$SESSION" -n "music-gen"
    fi

    tmux send-keys -t "$SESSION:music-gen" \
        "cd '$MUSIC_GEN_DIR' && LM_BACKEND=mlx PRELOAD_MODELS=1 ./run.sh" Enter

    echo "music-gen.server started in tmux: $SESSION:music-gen"
    echo "  Logs: tmux attach -t $SESSION:music-gen"
}

start_daemon() {
    # Kill any existing bumper daemon
    pkill -f "bumper_daemon.sh" 2>/dev/null || true
    sleep 1

    # Create or reuse a window for the daemon
    if ! tmux list-windows -t "$SESSION" -F "#{window_name}" | python3 -c "import sys; sys.exit(0 if 'bumpers' in sys.stdin.read() else 1)" 2>/dev/null; then
        tmux new-window -t "$SESSION" -n "bumpers"
    fi

    tmux send-keys -t "$SESSION:bumpers" \
        "cd '$RADIO_DIR' && bash mac/bumper_daemon.sh" Enter

    echo "Bumper daemon started in tmux: $SESSION:bumpers"
    echo "  Logs: tmux attach -t $SESSION:bumpers"
}

start_listener() {
    # Kill any existing listener daemon
    pkill -f "listener_daemon.sh" 2>/dev/null || true
    sleep 1

    # Create or reuse a window for the listener daemon
    if ! tmux list-windows -t "$SESSION" -F "#{window_name}" | python3 -c "import sys; sys.exit(0 if 'listener' in sys.stdin.read() else 1)" 2>/dev/null; then
        tmux new-window -t "$SESSION" -n "listener"
    fi

    tmux send-keys -t "$SESSION:listener" \
        "cd '$RADIO_DIR' && bash mac/listener_daemon.sh" Enter

    echo "Listener daemon started in tmux: $SESSION:listener"
    echo "  Logs: tmux attach -t $SESSION:listener"
}

MODE="${1:-all}"
case "$MODE" in
    server)   start_server ;;
    daemon)   start_daemon ;;
    listener) start_listener ;;
    *)        start_server; start_daemon; start_listener ;;
esac

echo ""
echo "Monitor with: tmux attach -t $SESSION"
