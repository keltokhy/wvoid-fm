#!/bin/bash
# Metadata script for ezstream.
#
# ezstream calls this with:
#   - no args      → return the full metadata string ("artist - title")
#   - "artist"     → return just the artist
#   - "title"      → return just the title
# It is NEVER called with the file path. The active track's path lives in
# output/.current_track.txt, written by mac/playlist_intake.py as ezstream
# advances through the playlist.
#
# Archival of finished tracks (move to {slot}/aired/) happens in
# playlist_intake.py — this script is read-only.

set -u

PROJECT_ROOT="/Volumes/K3/agent-working-space/projects/active/2025-12-29-radio-station"
STATE_FILE="$PROJECT_ROOT/output/.current_track.txt"
NOW_PLAYING="$PROJECT_ROOT/output/now_playing.json"

CURRENT=""
[ -f "$STATE_FILE" ] && CURRENT=$(cat "$STATE_FILE" 2>/dev/null || true)

# Clean display name from filename
name_of() {
    local stem
    stem=$(basename "$1")
    stem="${stem%.*}"
    case "$stem" in
        *listener_response*) echo "Listener Mail" ;;
        *deep_dive*)         echo "Deep Dive" ;;
        *news_analysis*)     echo "Signal Report" ;;
        *interview*)         echo "The Interview" ;;
        *panel*)             echo "Crosswire" ;;
        *story*)             echo "Story Hour" ;;
        *listener_mailbag*)  echo "Listener Hours" ;;
        *music_essay*)       echo "Sonic Essay" ;;
        *show_intro*)        echo "Show Opening" ;;
        *show_outro*)        echo "Show Closing" ;;
        *station_id*)        echo "WRIT-FM" ;;
        *bumper*)            echo "AI Music" ;;
        *)                   echo "Transmission" ;;
    esac
}

# Resolve host from now_playing.json (kept up-to-date by feeder.py)
HOST="WRIT-FM"
if [ -f "$NOW_PLAYING" ]; then
    H=$(python3 -c "import json,sys; print(json.load(open('$NOW_PLAYING')).get('host','') or '')" 2>/dev/null || true)
    [ -n "$H" ] && HOST="$H"
fi

# Resolve title from the current track path
if [ -n "$CURRENT" ] && [ -f "$CURRENT" ]; then
    TITLE=$(name_of "$CURRENT")
    BASENAME=$(basename "$CURRENT")
    EXT="${BASENAME##*.}"
    STEM="${BASENAME%.*}"
    META_FILE="$(dirname "$CURRENT")/$STEM.json"
    # Bumpers ship sidecar JSON with a curated display_name; prefer it.
    if [ "$EXT" != "wav" ] && [ -f "$META_FILE" ]; then
        DISPLAY=$(python3 -c "import json; print(json.load(open('$META_FILE')).get('display_name',''))" 2>/dev/null || true)
        [ -n "$DISPLAY" ] && TITLE="$DISPLAY"
    fi
else
    TITLE="WRIT-FM"
fi

# Respond to ezstream's invocation mode
case "${1:-}" in
    artist) printf '%s\n' "$HOST" ;;
    title)  printf '%s\n' "$TITLE" ;;
    *)      printf '%s - %s\n' "$HOST" "$TITLE" ;;
esac
