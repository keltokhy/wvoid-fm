#!/usr/bin/env python3
"""
WRIT-FM Track Selector for ezstream.

Called by ezstream each time it needs the next track to play.
Prints a single file path to stdout.

Maintains state in a JSON file to alternate between talk segments
and music bumpers, handle show transitions, and track consumption.

Also runs the API server on first invocation.
"""

import json
import os
import random
import re
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
STATE_FILE = PROJECT_ROOT / "output" / ".streamer_state.json"
TALK_DIR = PROJECT_ROOT / "output" / "talk_segments"
BUMPER_DIR = PROJECT_ROOT / "output" / "music_bumpers"
SILENCE_FILE = PROJECT_ROOT / "output" / ".silence.wav"
NOW_PLAYING_DEFAULT = PROJECT_ROOT / "output" / "now_playing.json"

sys.path.insert(0, str(Path(__file__).parent))

from schedule import load_schedule
SCHEDULE_PATH = PROJECT_ROOT / "config" / "schedule.yaml"

# Icecast config for listener count
ICECAST_STATUS_URL = os.environ.get(
    "ICECAST_STATUS_URL",
    "http://localhost:8000/status-json.xsl",
)

# Now-playing output paths
NOW_PLAYING_PATHS = [NOW_PLAYING_DEFAULT]
public_repo = Path.home() / "GitHub" / "keltokhy.github.io" / "public" / "now_playing.json"
if public_repo.parent.exists():
    NOW_PLAYING_PATHS.append(public_repo)


# ── Helpers ──────────────────────────────────────────────────────────────────

def log(msg: str):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", file=sys.stderr, flush=True)


def load_state() -> dict:
    """Load streamer state from disk."""
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except Exception:
            pass
    return {
        "next": "talk",          # "talk" or "bumper"
        "bumpers_remaining": 0,  # how many bumpers left in current set
        "show_id": None,
        "consumed": [],          # files to delete
        "last_bumper": None,
    }


def save_state(state: dict):
    """Persist state to disk."""
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state))
    tmp.replace(STATE_FILE)


def get_show():
    """Get current show from schedule."""
    schedule = load_schedule(SCHEDULE_PATH)
    resolved = schedule.resolve()
    return {
        "show_id": resolved.show_id,
        "show_name": resolved.name,
        "host": resolved.host,
        "topic_focus": resolved.topic_focus,
        "bumper_style": resolved.bumper_style,
        "description": resolved.description,
    }


def get_talk_segments(show_id: str) -> list[Path]:
    """Get available talk segments for a show, respecting sequence order."""
    show_dir = TALK_DIR / show_id
    if not show_dir.exists():
        return []
    segments = sorted(show_dir.glob("*.wav"), key=lambda p: p.name)

    # If any files have sequence prefixes (00_, 01_, ...), respect the order
    has_sequence = any(s.name[:3].rstrip("_").isdigit() for s in segments)
    if has_sequence:
        return segments

    lr = [s for s in segments if "listener_response" in s.name]
    rest = [s for s in segments if "listener_response" not in s.name]
    random.shuffle(rest)
    return lr + rest


def get_bumper(show_id: str, exclude: str | None = None) -> Path | None:
    """Pick a random bumper for the show."""
    show_dir = BUMPER_DIR / show_id
    if not show_dir.exists():
        return None
    files = [
        f for f in show_dir.iterdir()
        if f.is_file() and f.suffix.lower() in {".flac", ".mp3", ".wav"}
        and str(f) != exclude
    ]
    return random.choice(files) if files else None


def get_bumper_meta(path: Path) -> tuple[str | None, str | None]:
    """Read bumper metadata JSON if it exists."""
    meta_path = path.with_suffix(".json")
    if meta_path.exists():
        try:
            m = json.loads(meta_path.read_text())
            return m.get("caption"), m.get("display_name")
        except Exception:
            pass
    return None, None


def ensure_silence():
    """Create a short silence WAV file for fallback."""
    if SILENCE_FILE.exists():
        return
    import subprocess
    SILENCE_FILE.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([
        "ffmpeg", "-y", "-v", "quiet",
        "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
        "-t", "30", SILENCE_FILE,
    ], check=True)


def clean_name(filepath: Path) -> str:
    """Human-friendly name from filename."""
    name = filepath.stem
    segment_types = {
        "listener_response": "Listener Mail",
        "deep_dive": "Deep Dive",
        "news_analysis": "Signal Report",
        "interview": "The Interview",
        "panel": "Crosswire",
        "story": "Story Hour",
        "listener_mailbag": "Listener Hours",
        "music_essay": "Sonic Essay",
        "station_id": "WRIT-FM",
        "show_intro": "Show Opening",
        "show_outro": "Show Closing",
    }
    for key, friendly in segment_types.items():
        if key in name.lower():
            return friendly
    return "Transmission"


def get_listener_count() -> int:
    try:
        with urllib.request.urlopen(ICECAST_STATUS_URL, timeout=1.5) as resp:
            data = json.load(resp)
        source = data.get("icestats", {}).get("source", {})
        return int(source.get("listeners", 0) or 0)
    except Exception:
        return 0


def write_now_playing(info: dict):
    """Write now-playing JSON atomically to all configured paths."""
    for path in NOW_PLAYING_PATHS:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_name(f".{path.name}.tmp")
            tmp.write_text(json.dumps(info))
            tmp.replace(path)
        except Exception:
            pass


def record_play(filepath: Path, name: str, track_type: str, show_id: str):
    """Record play in history database."""
    try:
        from play_history import get_history
        get_history().record_play(
            filepath=str(filepath),
            track_name=name,
            vibe=track_type,
            time_period=show_id,
            listeners=get_listener_count(),
        )
    except Exception:
        pass


def consume_files(state: dict):
    """Delete previously played files."""
    for fpath in state.get("consumed", []):
        try:
            p = Path(fpath)
            if p.exists():
                p.unlink()
                log(f"  (consumed {p.name})")
        except Exception:
            pass
    state["consumed"] = []


def handle_metadata():
    """Called by ezstream for metadata updates. Print artist - title."""
    state = load_state()
    show = get_show()
    track = state.get("current_track_name", show["show_name"])
    print(f"{show['host']} - {track}")
    sys.exit(0)


# ── Main: select next track ─────────────────────────────────────────────────

def select_next_track() -> str:
    """Pick the next track. Returns a file path string."""
    state = load_state()
    show = get_show()

    # Consume files from previous iteration
    consume_files(state)

    # Detect show change
    if state["show_id"] != show["show_id"]:
        log(f"Show: {show['show_name']} ({show['show_id']})")
        log(f"  Host: {show['host']} | Focus: {show['topic_focus']}")
        state["show_id"] = show["show_id"]
        state["next"] = "talk"
        state["bumpers_remaining"] = 0

    # Decide: talk or bumper?
    if state["next"] == "bumper" and state["bumpers_remaining"] > 0:
        # Try to play a bumper
        bumper = get_bumper(show["show_id"], exclude=state.get("last_bumper"))
        if bumper:
            caption, display_name = get_bumper_meta(bumper)
            bname = display_name or "AI Music"
            log(f"  MUSIC: {bname}")

            write_now_playing({
                "track": bname,
                "type": "bumper",
                "show_id": show["show_id"],
                "show": show["show_name"],
                "caption": caption,
                "ai_generated": True,
                "timestamp": datetime.now().isoformat(),
                "listeners": get_listener_count(),
            })
            record_play(bumper, bname, "ai_bumper", show["show_id"])

            state["bumpers_remaining"] -= 1
            state["last_bumper"] = str(bumper)
            state["consumed"].append(str(bumper))
            state["current_track_name"] = bname
            if state["bumpers_remaining"] <= 0:
                state["next"] = "talk"
            save_state(state)
            return str(bumper)

        # No bumpers available, fall through to talk
        state["next"] = "talk"
        state["bumpers_remaining"] = 0

    # Try to play a talk segment
    segments = get_talk_segments(show["show_id"])
    if segments:
        seg = segments[0]
        seg_name = clean_name(seg)
        log(f"  TALK: {seg_name}")

        write_now_playing({
            "track": seg_name,
            "type": "talk",
            "host": show["host"],
            "show_id": show["show_id"],
            "show": show["show_name"],
            "timestamp": datetime.now().isoformat(),
            "listeners": get_listener_count(),
        })
        record_play(seg, seg_name, "talk", show["show_id"])

        state["consumed"].append(str(seg))
        state["current_track_name"] = seg_name
        # Queue 1-2 bumpers after this talk segment
        state["next"] = "bumper"
        state["bumpers_remaining"] = random.randint(1, 2)
        save_state(state)
        return str(seg)

    # No talk segments — try bumpers as filler
    bumper = get_bumper(show["show_id"], exclude=state.get("last_bumper"))
    if bumper:
        caption, display_name = get_bumper_meta(bumper)
        bname = display_name or "AI Music"
        log(f"  FILLER: {bname} (no talk available)")

        write_now_playing({
            "track": bname,
            "type": "bumper",
            "show_id": show["show_id"],
            "show": show["show_name"],
            "caption": caption,
            "timestamp": datetime.now().isoformat(),
            "listeners": get_listener_count(),
        })
        record_play(bumper, bname, "ai_bumper", show["show_id"])

        state["last_bumper"] = str(bumper)
        state["consumed"].append(str(bumper))
        state["current_track_name"] = bname
        state["next"] = "talk"  # try talk next time
        save_state(state)
        return str(bumper)

    # Nothing at all — play silence
    log(f"  No content for {show['show_id']} — silence")
    ensure_silence()
    state["next"] = "talk"
    save_state(state)
    return str(SILENCE_FILE)


# ── Entry point ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if "--metadata" in sys.argv:
        handle_metadata()

    track = select_next_track()
    # ezstream expects a single filename on stdout
    print(track)
