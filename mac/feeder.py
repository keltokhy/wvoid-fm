#!/usr/bin/env python3
"""
WRIT-FM Playlist Feeder for ezstream.

Runs as a daemon alongside ezstream. Builds and updates the playlist file
based on the current show schedule. Sends SIGHUP to ezstream to reload
when the playlist changes.

Also runs the API server and handles file consumption.
"""

import json
import os
import random
import signal
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PLAYLIST_FILE = PROJECT_ROOT / "output" / ".playlist.m3u"
SILENCE_FILE = PROJECT_ROOT / "output" / ".silence.wav"
TALK_DIR = PROJECT_ROOT / "output" / "talk_segments"
BUMPER_DIR = PROJECT_ROOT / "output" / "music_bumpers"
NOW_PLAYING_DEFAULT = PROJECT_ROOT / "output" / "now_playing.json"
EZSTREAM_PID_FILE = PROJECT_ROOT / "output" / ".ezstream.pid"

sys.path.insert(0, str(Path(__file__).parent))
from schedule import load_schedule
SCHEDULE_PATH = PROJECT_ROOT / "config" / "schedule.yaml"

# Import play history
try:
    from play_history import get_history
    HISTORY_ENABLED = True
except ImportError:
    HISTORY_ENABLED = False

# Now-playing paths
NOW_PLAYING_PATHS = [NOW_PLAYING_DEFAULT]
public_repo = Path.home() / "GitHub" / "keltokhy.github.io" / "public" / "now_playing.json"
if public_repo.parent.exists():
    NOW_PLAYING_PATHS.append(public_repo)

ICECAST_STATUS_URL = os.environ.get("ICECAST_STATUS_URL", "http://localhost:8000/status-json.xsl")

running = True


def log(msg: str):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def signal_handler(signum, frame):
    global running
    log("Feeder shutting down...")
    running = False


def get_show():
    schedule = load_schedule(SCHEDULE_PATH)
    resolved = schedule.resolve()
    return {
        "show_id": resolved.show_id,
        "show_name": resolved.name,
        "host": resolved.host,
        "topic_focus": resolved.topic_focus,
        "description": resolved.description,
    }


def get_talk_segments(show_id: str) -> list[Path]:
    show_dir = TALK_DIR / show_id
    if not show_dir.exists():
        return []
    segments = sorted(show_dir.glob("*.wav"), key=lambda p: p.name)

    # If any files have sequence prefixes (00_, 01_, ...), respect the order
    has_sequence = any(s.name[:3].rstrip("_").isdigit() for s in segments)
    if has_sequence:
        return segments  # already sorted by name = by sequence

    # Otherwise: listener responses first, rest shuffled
    lr = [s for s in segments if "listener_response" in s.name]
    rest = [s for s in segments if "listener_response" not in s.name]
    random.shuffle(rest)
    return lr + rest


def get_bumpers(show_id: str) -> list[Path]:
    show_dir = BUMPER_DIR / show_id
    if not show_dir.exists():
        return []
    files = [
        f for f in show_dir.iterdir()
        if f.is_file() and f.suffix.lower() in {".flac", ".mp3", ".wav"}
    ]
    random.shuffle(files)
    return files


def clean_name(filepath: Path) -> str:
    name = filepath.stem
    types = {
        "listener_response": "Listener Mail", "deep_dive": "Deep Dive",
        "news_analysis": "Signal Report", "interview": "The Interview",
        "panel": "Crosswire", "story": "Story Hour",
        "listener_mailbag": "Listener Hours", "music_essay": "Sonic Essay",
        "station_id": "WRIT-FM", "show_intro": "Show Opening",
        "show_outro": "Show Closing",
    }
    for key, friendly in types.items():
        if key in name.lower():
            return friendly
    return "Transmission"


def get_listener_count() -> int:
    try:
        import urllib.request
        with urllib.request.urlopen(ICECAST_STATUS_URL, timeout=1.5) as resp:
            data = json.load(resp)
        source = data.get("icestats", {}).get("source", {})
        return int(source.get("listeners", 0) or 0)
    except Exception:
        return 0


def write_now_playing(info: dict):
    for path in NOW_PLAYING_PATHS:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_name(f".{path.name}.tmp")
            tmp.write_text(json.dumps(info))
            tmp.replace(path)
        except Exception:
            pass


def record_play(filepath: Path, name: str, track_type: str, show_id: str):
    if HISTORY_ENABLED:
        try:
            get_history().record_play(
                filepath=str(filepath),
                track_name=name,
                vibe=track_type,
                time_period=show_id,
                listeners=get_listener_count(),
            )
        except Exception:
            pass


def get_ezstream_pid() -> int | None:
    """Find the ezstream process ID."""
    if EZSTREAM_PID_FILE.exists():
        try:
            pid = int(EZSTREAM_PID_FILE.read_text().strip())
            os.kill(pid, 0)  # check if alive
            return pid
        except (ValueError, ProcessLookupError, PermissionError):
            pass
    # Fallback: find by process name
    try:
        result = subprocess.run(["pgrep", "-f", "ezstream.*radio.xml"],
                                capture_output=True, text=True, timeout=2)
        if result.stdout.strip():
            return int(result.stdout.strip().split()[0])
    except Exception:
        pass
    return None


def signal_ezstream_reload():
    """Send SIGHUP to ezstream to reload the playlist."""
    pid = get_ezstream_pid()
    if pid:
        try:
            os.kill(pid, signal.SIGHUP)
        except Exception:
            pass


def build_playlist(show_id: str) -> list[dict]:
    """Build an ordered playlist for the current show.

    Returns list of {path, type, name} dicts.
    """
    entries = []
    talks = get_talk_segments(show_id)
    bumpers = get_bumpers(show_id)
    bumper_idx = 0

    if not talks and not bumpers:
        # Nothing — use silence
        entries.append({"path": str(SILENCE_FILE), "type": "silence", "name": "Silence"})
        return entries

    if not talks:
        # No talk, play bumpers as filler (up to 3)
        for b in bumpers[:3]:
            entries.append({"path": str(b), "type": "bumper", "name": "AI Music"})
        entries.append({"path": str(SILENCE_FILE), "type": "silence", "name": "Silence"})
        return entries

    # Interleave: talk, 1-2 bumpers, talk, 1-2 bumpers, ...
    for talk in talks:
        entries.append({"path": str(talk), "type": "talk", "name": clean_name(talk)})
        n_bumpers = random.randint(1, 2)
        for _ in range(n_bumpers):
            if bumper_idx < len(bumpers):
                b = bumpers[bumper_idx]
                meta_path = b.with_suffix(".json")
                bname = "AI Music"
                if meta_path.exists():
                    try:
                        m = json.loads(meta_path.read_text())
                        bname = m.get("display_name", bname)
                    except Exception:
                        pass
                entries.append({"path": str(b), "type": "bumper", "name": bname})
                bumper_idx += 1

    return entries


def write_playlist(entries: list[dict]):
    """Write the M3U playlist file."""
    PLAYLIST_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = PLAYLIST_FILE.with_suffix(".tmp")
    with open(tmp, "w") as f:
        for entry in entries:
            f.write(entry["path"] + "\n")
    tmp.replace(PLAYLIST_FILE)


def run():
    global running, ezstream_proc
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)

    log("=== WRIT-FM Feeder ===")
    log(f"Playlist: {PLAYLIST_FILE}")

    # Ensure silence file exists for fallback
    if not SILENCE_FILE.exists():
        log("Creating silence fallback file...")
        SILENCE_FILE.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run([
            "ffmpeg", "-y", "-v", "quiet",
            "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
            "-t", "30", str(SILENCE_FILE),
        ], check=True)

    # Shared state for API server
    track_info = {"track": None, "type": None, "show": None}

    # Proxy object so API health check reports "up" when ezstream is running
    class _StreamProxy:
        def poll(self):
            if ezstream_proc is None:
                return 1
            return ezstream_proc.poll()

    _proxy = _StreamProxy()

    # Start API server
    try:
        from api_server import start_api_thread
        start_api_thread(track_info, lambda: _proxy, get_listener_count)
        log("API server started on port 8001")
    except Exception as e:
        log(f"API server failed: {e}")

    current_show_id = None
    playlist_entries = []
    played_idx = 0
    last_check = 0

    while running:
        show = get_show()

        # Show changed — rebuild playlist
        if show["show_id"] != current_show_id:
            log(f"Show: {show['show_name']} ({show['show_id']})")
            log(f"  Host: {show['host']} | Focus: {show['topic_focus']}")
            current_show_id = show["show_id"]
            playlist_entries = build_playlist(show["show_id"])
            played_idx = 0
            write_playlist(playlist_entries)
            signal_ezstream_reload()
            log(f"  Playlist: {len(playlist_entries)} tracks")
            for e in playlist_entries:
                log(f"    [{e['type']}] {e['name']}")

        # Update now-playing info
        now = time.time()
        if now - last_check >= 5:
            last_check = now
            np_info = {
                "track": playlist_entries[0]["name"] if playlist_entries else show["show_name"],
                "type": playlist_entries[0]["type"] if playlist_entries else "silence",
                "show_id": show["show_id"],
                "show": show["show_name"],
                "host": show["host"],
                "timestamp": datetime.now().isoformat(),
                "listeners": get_listener_count(),
            }
            # Update shared dict for API server
            track_info.update(np_info)
            # Write to disk for external consumers
            write_now_playing(np_info)

        # Check if ezstream died and restart it
        if ezstream_proc and ezstream_proc.poll() is not None:
            log("  ezstream died, restarting...")
            ezstream_proc = start_ezstream()

        # Check if we need to rebuild (e.g., new content appeared)
        if now - last_check >= 30:
            talks_now = len(get_talk_segments(current_show_id))
            talks_in_playlist = sum(1 for e in playlist_entries if e["type"] == "talk")
            if talks_now > talks_in_playlist:
                log(f"  New content detected ({talks_now} > {talks_in_playlist}), rebuilding playlist")
                playlist_entries = build_playlist(current_show_id)
                write_playlist(playlist_entries)
                signal_ezstream_reload()

        time.sleep(5)

    # Clean up ezstream if we started it
    if ezstream_proc and ezstream_proc.poll() is None:
        log("Stopping ezstream...")
        ezstream_proc.terminate()
        ezstream_proc.wait(timeout=5)

    log("Feeder stopped")


# Global handle for ezstream subprocess
ezstream_proc = None

RADIO_XML = PROJECT_ROOT / "mac" / "radio.xml"


def start_ezstream() -> subprocess.Popen:
    """Start ezstream as a child process."""
    log("Starting ezstream...")
    # Build initial playlist before starting
    show = get_show()
    entries = build_playlist(show["show_id"])
    write_playlist(entries)

    proc = subprocess.Popen(
        ["ezstream", "-v", "-c", str(RADIO_XML)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        cwd=str(PROJECT_ROOT),
    )

    # Read stderr in a thread so it doesn't block
    def _log_ezstream(pipe):
        for line in iter(pipe.readline, b""):
            text = line.decode().strip()
            if text:
                log(f"  [ezstream] {text}")
        pipe.close()

    import threading
    threading.Thread(target=_log_ezstream, args=(proc.stderr,), daemon=True).start()

    time.sleep(2)
    if proc.poll() is not None:
        log("ERROR: ezstream failed to start")
        return proc

    log("ezstream connected to Icecast")
    return proc


if __name__ == "__main__":
    if "--start-ezstream" in sys.argv:
        ezstream_proc = start_ezstream()
    run()
