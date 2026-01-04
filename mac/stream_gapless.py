#!/usr/bin/env python3
"""
WVOID-FM Gapless Streamer (Mac Edition)

Streams directly to Icecast from Mac with zero gaps between tracks.
Uses a single ffmpeg encoder fed by continuous PCM from decoded tracks.
Features intelligent playlist curation based on time of day and energy flow.
"""

import subprocess
import random
import signal
import sys
import os
import re
import json
import time
import urllib.request
from pathlib import Path
from datetime import datetime
from dataclasses import dataclass

# Import play history tracker
try:
    from play_history import get_history
    HISTORY_ENABLED = True
except ImportError:
    HISTORY_ENABLED = False

try:
    from schedule import load_schedule, StationSchedule
    SCHEDULE_ENABLED = True
except ImportError:
    SCHEDULE_ENABLED = False

PROJECT_ROOT = Path(__file__).resolve().parents[1]

# Directories
DEFAULT_MUSIC_DIR = PROJECT_ROOT / "output" / "music"
DEFAULT_SEGMENTS_DIR = PROJECT_ROOT / "output" / "segments"
ARCHIVE_MUSIC_DIR = Path(
    os.environ.get("WVOID_ARCHIVE_MUSIC_DIR", "/Volumes/Archive/01_COLD_ARCHIVE/Media/Music")
).expanduser()

env_music_dirs = os.environ.get("WVOID_MUSIC_DIRS")
if env_music_dirs:
    MUSIC_DIRS = [Path(p).expanduser() for p in env_music_dirs.split(os.pathsep) if p]
else:
    MUSIC_DIRS = [DEFAULT_MUSIC_DIR]
    if ARCHIVE_MUSIC_DIR and ARCHIVE_MUSIC_DIR.exists():
        MUSIC_DIRS.append(ARCHIVE_MUSIC_DIR)

SEGMENTS_DIR = Path(os.environ.get("WVOID_SEGMENTS_DIR", str(DEFAULT_SEGMENTS_DIR))).expanduser()

# Podcast directory (longer-form audio content played at scheduled times)
DEFAULT_PODCASTS_DIR = PROJECT_ROOT / "output" / "podcasts"
PODCASTS_DIR = Path(os.environ.get("WVOID_PODCASTS_DIR", str(DEFAULT_PODCASTS_DIR))).expanduser()

# Podcast schedule: hours when podcasts should play (24h format)
# Plays at 12, 3, 6, 9 - both AM and PM
PODCAST_HOURS = {0, 3, 6, 9, 12, 15, 18, 21}

# Weekly schedule (optional)
DEFAULT_SCHEDULE_PATH = PROJECT_ROOT / "config" / "schedule.yaml"
SCHEDULE_PATH = Path(os.environ.get("WVOID_SCHEDULE_PATH", str(DEFAULT_SCHEDULE_PATH))).expanduser()

# Icecast config (local by default; override via env)
ICECAST_HOST = os.environ.get("ICECAST_HOST", "localhost")
ICECAST_PORT = int(os.environ.get("ICECAST_PORT", "8000"))
ICECAST_MOUNT = os.environ.get("ICECAST_MOUNT", "/stream")
ICECAST_USER = os.environ.get("ICECAST_USER", "source")
ICECAST_PASS = os.environ.get("ICECAST_PASS", "wvoid_source_2024")
ICECAST_URL = f"icecast://{ICECAST_USER}:{ICECAST_PASS}@{ICECAST_HOST}:{ICECAST_PORT}{ICECAST_MOUNT}"
ICECAST_STATUS_URL = os.environ.get(
    "ICECAST_STATUS_URL",
    f"http://{ICECAST_HOST}:{ICECAST_PORT}/status-json.xsl",
)

# =============================================================================
# RUNTIME STATE
# =============================================================================

running = True
encoder_proc = None
skip_current = False
force_segment = False
force_podcast = False  # Play a podcast next
last_podcast_slot: str | None = None  # Track which slot we last played a podcast (YYYYMMDDHH)
current_track_info: dict = {
    "track": None,
    "type": None,
    "vibe": None,
    "time_period": None,
    "listeners": 0,
}

# Command file
COMMAND_FILE = Path(
    os.environ.get("WVOID_COMMAND_FILE", str(PROJECT_ROOT / "command.txt"))
).expanduser()

# Now playing JSON (local + optional public path)
DEFAULT_NOW_PLAYING = PROJECT_ROOT / "output" / "now_playing.json"
NOW_PLAYING_PATHS = [DEFAULT_NOW_PLAYING]

env_now_playing = os.environ.get("WVOID_NOW_PLAYING_PATHS")
if env_now_playing:
    NOW_PLAYING_PATHS = [
        Path(p).expanduser() for p in env_now_playing.split(os.pathsep) if p
    ]
else:
    public_repo_path = (
        Path.home() / "GitHub" / "keltokhy.github.io" / "public" / "now_playing.json"
    )
    if public_repo_path.parent.exists():
        NOW_PLAYING_PATHS.append(public_repo_path)

NOW_PLAYING_PATHS = list(dict.fromkeys(NOW_PLAYING_PATHS))


# =============================================================================
# MUSIC CLASSIFICATION - Maps artists/keywords to vibes and energy levels
# =============================================================================

@dataclass
class TrackMood:
    energy: float  # 0.0 (ambient/quiet) to 1.0 (high energy/danceable)
    warmth: float  # 0.0 (cold/electronic) to 1.0 (warm/organic)
    vibe: str      # Category for grouping


@dataclass
class ProgramContext:
    show_id: str
    show_name: str
    show_description: str
    music_profile: dict
    segment_after_tracks: int
    podcasts_enabled: bool
    podcast_hours: set[int]

# Time periods with their ideal characteristics
TIME_PROFILES = {
    "late_night": {  # 00:00-05:59
        "hours": range(0, 6),
        "energy_range": (0.0, 0.4),
        "prefer_warmth": 0.7,
        "vibes": ["ambient", "jazz", "downtempo", "classical", "soul_slow", "dub"],
        "description": "The liminal hours. Slow, contemplative, intimate.",
    },
    "early_morning": {  # 06:00-09:59
        "hours": range(6, 10),
        "energy_range": (0.2, 0.5),
        "prefer_warmth": 0.6,
        "vibes": ["jazz", "classical", "bossa", "folk", "ambient", "soul_slow"],
        "description": "Waking gently. Warm coffee sounds.",
    },
    "morning": {  # 10:00-13:59
        "hours": range(10, 14),
        "energy_range": (0.4, 0.7),
        "prefer_warmth": 0.5,
        "vibes": ["soul", "funk", "indie", "world", "jazz", "hiphop_chill"],
        "description": "Building momentum. Grooving into the day.",
    },
    "early_afternoon": {  # 14:00-14:59 - Talk heavy hour
        "hours": range(14, 15),
        "energy_range": (0.4, 0.6),
        "prefer_warmth": 0.5,
        "vibes": ["jazz", "soul", "indie", "world", "downtempo"],
        "description": "The talk hour. More segments, slower pace.",
    },
    "afternoon": {  # 15:00-17:59
        "hours": range(15, 18),
        "energy_range": (0.5, 0.8),
        "prefer_warmth": 0.4,
        "vibes": ["funk", "disco", "hiphop", "indie", "electronic", "world", "rock"],
        "description": "Peak hours. Full energy, dancing allowed.",
    },
    "evening": {  # 18:00-20:59
        "hours": range(18, 21),
        "energy_range": (0.4, 0.7),
        "prefer_warmth": 0.6,
        "vibes": ["soul", "disco", "funk", "rnb", "indie", "world"],
        "description": "Sunset vibes. Transitioning down with style.",
    },
    "night": {  # 21:00-23:59
        "hours": range(21, 24),
        "energy_range": (0.2, 0.5),
        "prefer_warmth": 0.7,
        "vibes": ["downtempo", "jazz", "soul_slow", "electronic_chill", "dub", "ambient"],
        "description": "Night falling. Getting contemplative.",
    },
}

# Artist/keyword to mood mapping
MOOD_SIGNATURES = {
    # Ambient/Chill - very low energy, variable warmth
    "ambient": {"energy": 0.15, "warmth": 0.5, "vibe": "ambient"},
    "brian eno": {"energy": 0.1, "warmth": 0.6, "vibe": "ambient"},
    "aphex twin": {"energy": 0.3, "warmth": 0.2, "vibe": "electronic"},
    "boards of canada": {"energy": 0.25, "warmth": 0.7, "vibe": "ambient"},
    "burial": {"energy": 0.35, "warmth": 0.3, "vibe": "electronic"},
    "jon hopkins": {"energy": 0.4, "warmth": 0.4, "vibe": "electronic"},
    "tycho": {"energy": 0.3, "warmth": 0.6, "vibe": "ambient"},
    "bonobo": {"energy": 0.4, "warmth": 0.6, "vibe": "downtempo"},

    # Jazz - moderate energy, very warm
    "jazz": {"energy": 0.35, "warmth": 0.9, "vibe": "jazz"},
    "coltrane": {"energy": 0.5, "warmth": 0.9, "vibe": "jazz"},
    "miles davis": {"energy": 0.4, "warmth": 0.85, "vibe": "jazz"},
    "bill evans": {"energy": 0.25, "warmth": 0.95, "vibe": "jazz"},
    "dave brubeck": {"energy": 0.4, "warmth": 0.85, "vibe": "jazz"},
    "art blakey": {"energy": 0.55, "warmth": 0.85, "vibe": "jazz"},
    "cannonball": {"energy": 0.5, "warmth": 0.9, "vibe": "jazz"},
    "thelonious monk": {"energy": 0.4, "warmth": 0.85, "vibe": "jazz"},
    "nujabes": {"energy": 0.35, "warmth": 0.8, "vibe": "jazz"},
    "aruarian": {"energy": 0.3, "warmth": 0.85, "vibe": "jazz"},

    # Classical - low-moderate energy, warm
    "classical": {"energy": 0.25, "warmth": 0.8, "vibe": "classical"},
    "chopin": {"energy": 0.2, "warmth": 0.9, "vibe": "classical"},
    "debussy": {"energy": 0.2, "warmth": 0.85, "vibe": "classical"},
    "arvo pärt": {"energy": 0.15, "warmth": 0.9, "vibe": "classical"},
    "arvo part": {"energy": 0.15, "warmth": 0.9, "vibe": "classical"},
    "satie": {"energy": 0.15, "warmth": 0.85, "vibe": "classical"},
    "bach": {"energy": 0.3, "warmth": 0.8, "vibe": "classical"},
    "ravel": {"energy": 0.3, "warmth": 0.85, "vibe": "classical"},

    # Soul/R&B - moderate-high energy, very warm
    "soul": {"energy": 0.5, "warmth": 0.95, "vibe": "soul"},
    "al green": {"energy": 0.45, "warmth": 0.95, "vibe": "soul"},
    "marvin gaye": {"energy": 0.5, "warmth": 0.95, "vibe": "soul"},
    "d'angelo": {"energy": 0.45, "warmth": 0.9, "vibe": "soul"},
    "erykah badu": {"energy": 0.4, "warmth": 0.9, "vibe": "soul"},
    "stevie wonder": {"energy": 0.6, "warmth": 0.95, "vibe": "soul"},
    "aretha": {"energy": 0.6, "warmth": 0.95, "vibe": "soul"},
    "otis redding": {"energy": 0.55, "warmth": 0.95, "vibe": "soul"},
    "sade": {"energy": 0.35, "warmth": 0.9, "vibe": "soul_slow"},
    "frank ocean": {"energy": 0.35, "warmth": 0.85, "vibe": "soul_slow"},

    # Funk/Disco - high energy, warm
    "funk": {"energy": 0.75, "warmth": 0.85, "vibe": "funk"},
    "disco": {"energy": 0.8, "warmth": 0.7, "vibe": "disco"},
    "james brown": {"energy": 0.8, "warmth": 0.9, "vibe": "funk"},
    "parliament": {"energy": 0.75, "warmth": 0.85, "vibe": "funk"},
    "prince": {"energy": 0.7, "warmth": 0.8, "vibe": "funk"},
    "donna summer": {"energy": 0.85, "warmth": 0.7, "vibe": "disco"},
    "bee gees": {"energy": 0.75, "warmth": 0.75, "vibe": "disco"},
    "chic": {"energy": 0.8, "warmth": 0.75, "vibe": "disco"},
    "anderson paak": {"energy": 0.65, "warmth": 0.85, "vibe": "funk"},
    "vulfpeck": {"energy": 0.65, "warmth": 0.9, "vibe": "funk"},

    # Hip-hop - variable energy
    "tribe called quest": {"energy": 0.55, "warmth": 0.8, "vibe": "hiphop_chill"},
    "j dilla": {"energy": 0.45, "warmth": 0.85, "vibe": "hiphop_chill"},
    "madlib": {"energy": 0.4, "warmth": 0.75, "vibe": "hiphop_chill"},
    "mf doom": {"energy": 0.45, "warmth": 0.7, "vibe": "hiphop_chill"},
    "kendrick": {"energy": 0.65, "warmth": 0.75, "vibe": "hiphop"},
    "kanye": {"energy": 0.7, "warmth": 0.6, "vibe": "hiphop"},
    "tyler": {"energy": 0.6, "warmth": 0.7, "vibe": "hiphop"},
    "outkast": {"energy": 0.7, "warmth": 0.8, "vibe": "hiphop"},

    # Bossa/Brazilian - moderate energy, very warm
    "bossa": {"energy": 0.3, "warmth": 0.95, "vibe": "bossa"},
    "jobim": {"energy": 0.3, "warmth": 0.95, "vibe": "bossa"},
    "gilberto": {"energy": 0.3, "warmth": 0.95, "vibe": "bossa"},
    "astrud": {"energy": 0.3, "warmth": 0.95, "vibe": "bossa"},
    "getz": {"energy": 0.35, "warmth": 0.9, "vibe": "bossa"},
    "buena vista": {"energy": 0.45, "warmth": 0.95, "vibe": "world"},

    # Reggae/Dub - moderate energy, warm
    "reggae": {"energy": 0.45, "warmth": 0.85, "vibe": "dub"},
    "dub": {"energy": 0.4, "warmth": 0.75, "vibe": "dub"},
    "bob marley": {"energy": 0.5, "warmth": 0.9, "vibe": "dub"},
    "king tubby": {"energy": 0.4, "warmth": 0.7, "vibe": "dub"},
    "lee perry": {"energy": 0.45, "warmth": 0.75, "vibe": "dub"},
    "augustus pablo": {"energy": 0.35, "warmth": 0.8, "vibe": "dub"},
    "burning spear": {"energy": 0.5, "warmth": 0.85, "vibe": "dub"},
    "black uhuru": {"energy": 0.5, "warmth": 0.8, "vibe": "dub"},
    "toots": {"energy": 0.55, "warmth": 0.9, "vibe": "dub"},
    "dennis brown": {"energy": 0.5, "warmth": 0.9, "vibe": "dub"},

    # Downtempo/Trip-hop - low-moderate energy
    "downtempo": {"energy": 0.35, "warmth": 0.6, "vibe": "downtempo"},
    "trip-hop": {"energy": 0.4, "warmth": 0.5, "vibe": "downtempo"},
    "massive attack": {"energy": 0.45, "warmth": 0.5, "vibe": "downtempo"},
    "portishead": {"energy": 0.35, "warmth": 0.4, "vibe": "downtempo"},
    "tricky": {"energy": 0.4, "warmth": 0.45, "vibe": "downtempo"},
    "thievery corporation": {"energy": 0.4, "warmth": 0.6, "vibe": "downtempo"},
    "kruder": {"energy": 0.35, "warmth": 0.6, "vibe": "downtempo"},
    "dorfmeister": {"energy": 0.35, "warmth": 0.6, "vibe": "downtempo"},
    "nightmares on wax": {"energy": 0.4, "warmth": 0.7, "vibe": "downtempo"},

    # Indie/Alternative - variable
    "radiohead": {"energy": 0.5, "warmth": 0.5, "vibe": "indie"},
    "arcade fire": {"energy": 0.65, "warmth": 0.6, "vibe": "indie"},
    "bon iver": {"energy": 0.3, "warmth": 0.75, "vibe": "indie"},
    "beach house": {"energy": 0.35, "warmth": 0.6, "vibe": "indie"},
    "tame impala": {"energy": 0.55, "warmth": 0.65, "vibe": "indie"},
    "mac demarco": {"energy": 0.4, "warmth": 0.75, "vibe": "indie"},
    "khruangbin": {"energy": 0.45, "warmth": 0.8, "vibe": "indie"},
    "gorillaz": {"energy": 0.55, "warmth": 0.6, "vibe": "indie"},
    "alt-j": {"energy": 0.45, "warmth": 0.55, "vibe": "indie"},
    "sigur ros": {"energy": 0.35, "warmth": 0.7, "vibe": "indie"},

    # Electronic/Dance - high energy, cold
    "electronic": {"energy": 0.7, "warmth": 0.3, "vibe": "electronic"},
    "house": {"energy": 0.75, "warmth": 0.4, "vibe": "electronic"},
    "techno": {"energy": 0.8, "warmth": 0.2, "vibe": "electronic"},
    "daft punk": {"energy": 0.75, "warmth": 0.5, "vibe": "electronic"},
    "four tet": {"energy": 0.5, "warmth": 0.55, "vibe": "electronic_chill"},
    "floating points": {"energy": 0.5, "warmth": 0.5, "vibe": "electronic_chill"},
    "jamie xx": {"energy": 0.6, "warmth": 0.5, "vibe": "electronic"},
    "kaytranada": {"energy": 0.65, "warmth": 0.6, "vibe": "electronic"},
    "flume": {"energy": 0.7, "warmth": 0.45, "vibe": "electronic"},

    # World Music - moderate energy, very warm
    "world": {"energy": 0.5, "warmth": 0.9, "vibe": "world"},
    "fela kuti": {"energy": 0.65, "warmth": 0.9, "vibe": "world"},
    "ali farka": {"energy": 0.45, "warmth": 0.95, "vibe": "world"},
    "youssou ndour": {"energy": 0.6, "warmth": 0.9, "vibe": "world"},
    "tinariwen": {"energy": 0.5, "warmth": 0.85, "vibe": "world"},
    "mulatu": {"energy": 0.45, "warmth": 0.9, "vibe": "world"},

    # Arabic - moderate energy, very warm
    "amr diab": {"energy": 0.55, "warmth": 0.9, "vibe": "world"},
    "عمرو دياب": {"energy": 0.55, "warmth": 0.9, "vibe": "world"},
    "fairuz": {"energy": 0.35, "warmth": 0.95, "vibe": "world"},
    "umm kulthum": {"energy": 0.4, "warmth": 0.95, "vibe": "world"},
    "abdel halim": {"energy": 0.45, "warmth": 0.95, "vibe": "world"},
    "ahmed mounib": {"energy": 0.4, "warmth": 0.95, "vibe": "world"},
    "salah ragab": {"energy": 0.55, "warmth": 0.9, "vibe": "jazz"},

    # Lo-fi / Chill beats
    "lofi": {"energy": 0.25, "warmth": 0.7, "vibe": "downtempo"},
    "lo-fi": {"energy": 0.25, "warmth": 0.7, "vibe": "downtempo"},
    "tomppabeats": {"energy": 0.25, "warmth": 0.75, "vibe": "downtempo"},
    "jinsang": {"energy": 0.25, "warmth": 0.7, "vibe": "downtempo"},
    "idealism": {"energy": 0.2, "warmth": 0.75, "vibe": "downtempo"},
    "uyama hiroto": {"energy": 0.3, "warmth": 0.8, "vibe": "jazz"},

    # More indie/alternative
    "men i trust": {"energy": 0.35, "warmth": 0.65, "vibe": "indie"},
    "magdalena bay": {"energy": 0.55, "warmth": 0.5, "vibe": "indie"},
    "charli xcx": {"energy": 0.75, "warmth": 0.4, "vibe": "electronic"},
    "lana del rey": {"energy": 0.3, "warmth": 0.7, "vibe": "indie"},
    "fka twigs": {"energy": 0.45, "warmth": 0.5, "vibe": "electronic"},
    "yellow days": {"energy": 0.4, "warmth": 0.75, "vibe": "indie"},

    # Rock classics
    "pink floyd": {"energy": 0.45, "warmth": 0.6, "vibe": "rock"},
    "led zeppelin": {"energy": 0.7, "warmth": 0.7, "vibe": "rock"},
    "the beatles": {"energy": 0.5, "warmth": 0.8, "vibe": "rock"},
    "beatles": {"energy": 0.5, "warmth": 0.8, "vibe": "rock"},
    "fleetwood mac": {"energy": 0.55, "warmth": 0.75, "vibe": "rock"},
    "steely dan": {"energy": 0.5, "warmth": 0.8, "vibe": "rock"},

    # More hip-hop
    "young thug": {"energy": 0.7, "warmth": 0.5, "vibe": "hiphop"},
    "playboi carti": {"energy": 0.75, "warmth": 0.35, "vibe": "hiphop"},
    "travis scott": {"energy": 0.75, "warmth": 0.45, "vibe": "hiphop"},
    "a$ap rocky": {"energy": 0.65, "warmth": 0.55, "vibe": "hiphop"},
    "asap rocky": {"energy": 0.65, "warmth": 0.55, "vibe": "hiphop"},

    # More electronic
    "against all logic": {"energy": 0.6, "warmth": 0.5, "vibe": "electronic"},
    "nicolas jaar": {"energy": 0.45, "warmth": 0.55, "vibe": "electronic_chill"},
    "100 gecs": {"energy": 0.85, "warmth": 0.2, "vibe": "electronic"},

    # K-pop - high energy
    "loona": {"energy": 0.75, "warmth": 0.5, "vibe": "electronic"},
    "이달의 소녀": {"energy": 0.75, "warmth": 0.5, "vibe": "electronic"},

    # Rock - variable energy
    "rock": {"energy": 0.7, "warmth": 0.6, "vibe": "rock"},
    "depeche mode": {"energy": 0.55, "warmth": 0.4, "vibe": "electronic"},
    "cocteau twins": {"energy": 0.4, "warmth": 0.6, "vibe": "indie"},
    "cherry-coloured": {"energy": 0.4, "warmth": 0.6, "vibe": "indie"},

    # Pop - high energy
    "britney": {"energy": 0.8, "warmth": 0.5, "vibe": "electronic"},
    "dua lipa": {"energy": 0.8, "warmth": 0.55, "vibe": "disco"},
    "drake": {"energy": 0.6, "warmth": 0.6, "vibe": "hiphop"},
}


def signal_handler(signum, frame):
    global running, encoder_proc
    log("Shutting down...")
    running = False
    if encoder_proc:
        encoder_proc.terminate()
    sys.exit(0)


def log(msg: str):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


LISTENER_CACHE_SECONDS = 15
_last_listener_count = 0
_last_listener_check = 0.0


def get_listener_count() -> int:
    """Fetch listener count with a short cache to avoid blocking playback."""
    global _last_listener_count, _last_listener_check
    now = time.time()
    if now - _last_listener_check < LISTENER_CACHE_SECONDS:
        return _last_listener_count

    _last_listener_check = now
    try:
        with urllib.request.urlopen(ICECAST_STATUS_URL, timeout=1.5) as resp:
            data = json.load(resp)
        source = data.get("icestats", {}).get("source", {})
        _last_listener_count = int(source.get("listeners", 0) or 0)
    except Exception:
        pass

    return _last_listener_count


def write_json_atomic(path: Path, payload: dict) -> None:
    """Write JSON atomically to avoid partial reads."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f".{path.name}.tmp")
    tmp_path.write_text(json.dumps(payload))
    tmp_path.replace(path)


def update_now_playing(
    track: str,
    track_type: str,
    vibe: str = None,
    time_period: str = None,
    show_id: str | None = None,
    show_name: str | None = None,
):
    """Write current track info to JSON file."""
    global current_track_info
    current_track_info = {
        "track": track,
        "type": track_type,
        "vibe": vibe,
        "time_period": time_period,
        "show_id": show_id,
        "show": show_name,
        "timestamp": datetime.now().isoformat(),
        "listeners": get_listener_count(),
    }
    for path in NOW_PLAYING_PATHS:
        try:
            write_json_atomic(path, current_track_info)
        except Exception:
            pass  # Non-critical


def check_command() -> str | None:
    """Check for pending command."""
    try:
        if COMMAND_FILE.exists() and (cmd := COMMAND_FILE.read_text().strip()):
            COMMAND_FILE.write_text("")
            return cmd
    except Exception:
        pass
    return None


def get_audio_files(directory: Path, recursive: bool = False) -> list[Path]:
    if not directory.exists():
        return []
    extensions = {".mp3", ".wav", ".flac", ".ogg", ".m4a", ".opus"}
    if recursive:
        return [f for f in directory.rglob("*") if f.is_file() and f.suffix.lower() in extensions]
    return [f for f in directory.iterdir() if f.is_file() and f.suffix.lower() in extensions]


def get_all_music() -> list[Path]:
    """Get music from all configured directories."""
    all_music = []
    for music_dir in MUSIC_DIRS:
        recursive = "Archive" in str(music_dir)
        files = get_audio_files(music_dir, recursive=recursive)
        all_music.extend(files)
        log(f"Found {len(files)} tracks in {music_dir.name}")
    return all_music


def clean_name(filepath: Path, is_segment: bool = False) -> str:
    name = filepath.stem

    # For segments, return friendly names based on type
    if is_segment:
        segment_types = {
            "station_id": "WVOID-FM",
            "hour_marker": "The Liminal Hour",
            "long_talk": "The Operator Speaks",
            "music_history": "Sonic Archaeology",
            "late_night": "Late Night Transmission",
            "monologue": "Midnight Musings",
            "dedication": "For the Night Owls",
            "weather": "Conditions Unknown",
            "news": "Signals from Elsewhere",
            "poetry": "Verse from the Void",
        }
        for key, friendly in segment_types.items():
            if key in name.lower():
                return friendly
        return "Transmission"

    patterns = [
        r'\s*\(Official.*?\)', r'\s*\[Official.*?\]',
        r'\s*\(Full Album.*?\)', r'\s*\[Full Album.*?\]',
        r'\s*\(HD\)', r'\s*\[HD\]', r'\s*\(Audio\)', r'\s*\[Audio\]',
        r'\s*\(Lyrics\)', r'\s*\[Lyrics\]', r'\s*\(Visualizer\)',
        r'\s*｜.*$', r'\s*⧹.*$', r'_seg\d+_\d+$',
    ]
    for p in patterns:
        name = re.sub(p, '', name, flags=re.IGNORECASE)
    return name.strip()


def classify_track(filepath: Path) -> TrackMood:
    """Classify a track based on its filename/path."""
    name_lower = str(filepath).lower()
    best = max(
        ((k, v) for k, v in MOOD_SIGNATURES.items() if k in name_lower),
        key=lambda x: len(x[0]),
        default=(None, None)
    )[1]
    if best:
        return TrackMood(energy=best["energy"], warmth=best["warmth"], vibe=best["vibe"])
    return TrackMood(energy=0.5, warmth=0.5, vibe="unknown")


def get_current_time_profile() -> dict:
    """Get the current time period profile."""
    hour = datetime.now().hour
    for name, profile in TIME_PROFILES.items():
        if hour in profile["hours"]:
            return {"name": name, **profile}
    return TIME_PROFILES["late_night"]


def score_track_for_time(track: Path, profile: dict) -> float:
    """Score how well a track fits the current time period."""
    mood = classify_track(track)
    score = 0.0

    # Energy fit (0-40 points)
    min_energy, max_energy = profile["energy_range"]
    if min_energy <= mood.energy <= max_energy:
        score += 40
    else:
        # Penalize based on distance from range
        if mood.energy < min_energy:
            score += max(0, 30 - (min_energy - mood.energy) * 50)
        else:
            score += max(0, 30 - (mood.energy - max_energy) * 50)

    # Warmth fit (0-30 points)
    warmth_diff = abs(mood.warmth - profile["prefer_warmth"])
    score += max(0, 30 - warmth_diff * 40)

    # Vibe bonus (0-30 points)
    if mood.vibe in profile["vibes"]:
        vibe_idx = profile["vibes"].index(mood.vibe)
        score += 30 - (vibe_idx * 3)  # Earlier in list = better fit

    # Small random factor for variety (0-10 points)
    score += random.random() * 10

    return score


def create_curated_queue(music: list[Path], size: int = 20, profile: dict | None = None) -> list[Path]:
    """Create a curated queue of tracks appropriate for the current program."""
    profile = profile or get_current_time_profile()
    log(f"Time period: {profile['name']} - {profile['description']}")

    # Filter out recently played tracks
    if HISTORY_ENABLED:
        history = get_history()
        fresh_music = history.filter_recent(music, hours=24)
        if len(fresh_music) < size * 2:
            # Not enough fresh tracks, allow some repeats
            fresh_music = history.filter_recent(music, hours=6)
        if fresh_music:
            music = fresh_music
            log(f"After history filter: {len(music)} eligible tracks")

    # Score all tracks
    scored = [(track, score_track_for_time(track, profile)) for track in music]

    # Sort by score descending
    scored.sort(key=lambda x: x[1], reverse=True)

    # Take top candidates with some randomization
    # Select from top 50% of scored tracks to maintain variety
    top_half = scored[:max(len(scored) // 2, size * 2)]
    random.shuffle(top_half)

    selected = []
    last_vibe = None

    for track, score in top_half:
        if len(selected) >= size:
            break

        mood = classify_track(track)

        # Avoid too many of same vibe in a row
        if mood.vibe == last_vibe and random.random() < 0.6:
            continue

        selected.append(track)
        last_vibe = mood.vibe

    # If we didn't get enough, just add more from top
    if len(selected) < size:
        for track, score in top_half:
            if track not in selected:
                selected.append(track)
                if len(selected) >= size:
                    break

    return selected


def get_program_context(station_schedule=None) -> ProgramContext:
    """Resolve the current show/program, falling back to time-of-day profiles."""
    if station_schedule is not None:
        resolved = station_schedule.resolve()
        return ProgramContext(
            show_id=resolved.show_id,
            show_name=resolved.name,
            show_description=resolved.description,
            music_profile=resolved.music_profile,
            segment_after_tracks=resolved.segment_after_tracks,
            podcasts_enabled=resolved.podcasts_enabled,
            podcast_hours=set(resolved.podcast_hours),
        )

    profile = get_current_time_profile()
    return ProgramContext(
        show_id=profile["name"],
        show_name=profile["name"],
        show_description=profile["description"],
        music_profile=profile,
        segment_after_tracks=1,
        podcasts_enabled=True,
        podcast_hours=set(PODCAST_HOURS),
    )


def select_show_asset(show_id: str, asset_type: str) -> Path | None:
    """Select the newest show asset WAV (e.g., bumper_in) for a given show_id."""
    show_dir = SEGMENTS_DIR / "shows" / show_id
    if not show_dir.exists():
        return None

    candidates = sorted(
        show_dir.glob(f"{asset_type}_*.wav"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if candidates:
        return candidates[0]

    exact = show_dir / f"{asset_type}.wav"
    if exact.exists():
        return exact

    return None


SEGMENT_TYPES = [
    "listener_dedication", "station_id", "hour_marker", "long_talk",
    "monologue", "late_night", "music_history", "dedication",
    "weather", "news", "poetry"
]


def get_segment_type(seg: Path) -> str:
    """Extract segment type from filename."""
    name = seg.name.lower()
    for stype in SEGMENT_TYPES:
        if stype in name:
            return stype
    return "other"


def get_current_period() -> str:
    """Get the current time period name."""
    hour = datetime.now().hour
    if hour < 6: return "late_night"
    if hour < 12: return "morning"
    if hour < 18: return "afternoon"
    return "evening"


def select_segment(base_dir: Path) -> Path | None:
    """Select a segment from the current period's folder.

    Falls back to any segment if period folder is empty.
    Prioritizes listener dedications.
    """
    global last_segment_type
    period = get_current_period()
    period_dir = base_dir / period

    # Get segments from period folder, or fall back to base
    if period_dir.exists():
        segments = list(period_dir.glob("*.wav"))
    else:
        segments = []

    # Fall back to base directory if period folder empty
    if not segments:
        segments = list(base_dir.glob("*.wav"))

    if not segments:
        return None

    # Prioritize listener dedications (newest first)
    dedications = sorted(
        [s for s in segments if "listener_dedication" in s.name.lower()],
        key=lambda x: x.stat().st_mtime,
        reverse=True
    )
    if dedications and last_segment_type != "listener_dedication":
        selected = dedications[0]
        last_segment_type = "listener_dedication"
        return selected

    # Pick randomly, avoiding same type twice in a row
    available = [s for s in segments if get_segment_type(s) != last_segment_type]
    if not available:
        available = segments

    selected = random.choice(available)
    last_segment_type = get_segment_type(selected)
    return selected


def should_play_segment(time_period: str) -> bool:
    """Play a segment after every song (1 song, 1 talk pattern)."""
    return force_segment or tracks_since_segment >= 1


def get_track_duration(filepath: Path) -> float | None:
    """Get track duration in seconds using ffprobe."""
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(filepath)],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0 and result.stdout.strip():
            return float(result.stdout.strip())
    except:
        pass
    return None


# Track chopping (for long albums/mixes)
MAX_TRACK_DURATION = 150  # 2.5 minutes - chop longer tracks
CHUNK_MIN_DURATION = 90   # 1.5 minutes minimum chunk
CHUNK_MAX_DURATION = 150  # 2.5 minutes maximum chunk

# Runtime state
last_segment_type = None
tracks_since_segment = 0


# =============================================================================
# PODCAST SCHEDULING
# =============================================================================


def get_all_podcasts() -> list[Path]:
    """Get all podcast files from the podcasts directory."""
    if not PODCASTS_DIR.exists():
        return []
    exts = {".mp3", ".flac", ".m4a", ".wav", ".ogg", ".aac"}
    podcasts = [f for f in PODCASTS_DIR.iterdir() if f.suffix.lower() in exts]
    return sorted(podcasts, key=lambda p: p.stat().st_mtime, reverse=True)


def should_play_podcast() -> bool:
    """Check if it's time to play a podcast (every 3 hours)."""
    current_hour = datetime.now().hour
    return current_hour in PODCAST_HOURS and last_podcast_hour != current_hour


def select_podcast(podcasts: list[Path]) -> Path | None:
    """Select a podcast, preferring unplayed ones."""
    if not podcasts:
        return None
    if HISTORY_ENABLED:
        try:
            history = get_history()
            unplayed = [p for p in podcasts if not history.was_played_recently(str(p), hours=24)]
            if unplayed:
                return random.choice(unplayed)
        except Exception:
            pass
    return random.choice(podcasts[:5]) if len(podcasts) > 5 else random.choice(podcasts)




def decode_to_pcm(filepath: Path, start_time: float = 0, duration: float = None, is_speech: bool = False) -> subprocess.Popen:
    """Decode audio file to raw PCM, output to stdout.

    Args:
        filepath: Audio file path
        start_time: Start position in seconds (for chopping long tracks)
        duration: Duration to extract in seconds (None = full track)
        is_speech: If True, use louder normalization for speech content
    """
    cmd = ["ffmpeg", "-v", "warning"]

    # Seek to start position (before input for faster seeking)
    if start_time > 0:
        cmd.extend(["-ss", str(start_time)])

    cmd.extend(["-i", str(filepath)])

    # Limit duration if specified
    if duration is not None:
        cmd.extend(["-t", str(duration)])

    # Build audio filter chain
    # Speech (segments/podcasts) gets louder normalization (-14 LUFS vs -16 for music)
    if is_speech:
        filters = ["loudnorm=I=-14:TP=-1.5:LRA=7"]
    else:
        filters = ["loudnorm=I=-16:TP=-1.5:LRA=11"]

    # Add fade in/out (8 seconds each) - only for music, not speech
    if not is_speech:
        filters.append("afade=t=in:st=0:d=8")
        if duration is not None and duration > 16:
            fade_out_start = max(0, duration - 8)
            filters.append(f"afade=t=out:st={fade_out_start}:d=8")

    filters.append("aresample=44100")

    cmd.extend([
        "-vn",
        "-af", ",".join(filters),
        "-f", "s16le",
        "-acodec", "pcm_s16le",
        "-ar", "44100",
        "-ac", "2",
        "-"
    ])

    return subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL
    )


def start_encoder() -> subprocess.Popen:
    """Start persistent ffmpeg encoder to Icecast."""
    return subprocess.Popen(
        [
            "ffmpeg", "-v", "warning",
            "-re",
            "-f", "s16le",
            "-ar", "44100",
            "-ac", "2",
            "-i", "-",
            "-acodec", "libmp3lame",
            "-b:a", "192k",
            "-content_type", "audio/mpeg",
            "-ice_name", "WVOID-FM",
            "-ice_description", "The frequency between frequencies",
            "-ice_genre", "Eclectic",
            "-f", "mp3",
            ICECAST_URL
        ],
        stdin=subprocess.PIPE,
        stderr=subprocess.PIPE  # Capture stderr to diagnose issues
    )


def wait_for_encoder_ready(encoder: subprocess.Popen, timeout: float = 2.0) -> bool:
    """Wait briefly to ensure encoder connected successfully."""
    import select
    # Give the encoder a moment to fail if it's going to
    time.sleep(0.3)
    if encoder.poll() is not None:
        # Encoder already died - read stderr for reason
        try:
            stderr = encoder.stderr.read().decode() if encoder.stderr else ""
            if stderr:
                log(f"Encoder error: {stderr[:200]}")
        except:
            pass
        return False
    return True


def pipe_track(filepath: Path, encoder: subprocess.Popen, start_time: float = 0, duration: float = None, is_speech: bool = False) -> bool:
    """Decode a track and pipe PCM to encoder. Returns False if encoder died.

    Args:
        filepath: Audio file path
        encoder: ffmpeg encoder subprocess
        start_time: Start position for chopping
        duration: Duration to play
        is_speech: If True, use louder normalization (for segments/podcasts)
    """
    global running, skip_current, force_segment

    if not running or encoder.poll() is not None:
        return False

    decoder = None
    try:
        decoder = decode_to_pcm(filepath, start_time, duration, is_speech=is_speech)

        while running and not skip_current:
            chunk = decoder.stdout.read(8192)
            if not chunk:
                break
            try:
                encoder.stdin.write(chunk)
                encoder.stdin.flush()
            except BrokenPipeError:
                # Try to get error message from encoder
                try:
                    stderr = encoder.stderr.read().decode() if encoder.stderr else ""
                    if stderr:
                        log(f"Encoder pipe broke: {stderr[:200]}")
                except:
                    pass
                return False

            cmd = check_command()
            if cmd == "skip":
                log("⏭ Skipping...")
                skip_current = True
                break
            elif cmd == "segment":
                log("Will play segment next...")
                force_segment = True
            elif cmd == "podcast":
                log("Will play podcast next...")
                force_podcast = True

        return True

    except Exception as e:
        log(f"Error piping {filepath.name}: {e}")
        return False
    finally:
        if decoder:
            try:
                decoder.kill()
                decoder.wait(timeout=1)
            except:
                pass
        if skip_current:
            skip_current = False


def run():
    global running, encoder_proc, force_segment, force_podcast, tracks_since_segment, last_podcast_slot

    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)

    log("=== WVOID-FM Gapless Streamer ===")
    log(f"Music sources: {len(MUSIC_DIRS)}")
    log(f"Segments: {SEGMENTS_DIR}")
    log(f"Podcasts: {PODCASTS_DIR}")
    log(f"Streaming to: {ICECAST_URL}")

    # Load schedule if available
    station_schedule = None
    if SCHEDULE_ENABLED and SCHEDULE_PATH.exists():
        try:
            station_schedule = load_schedule(SCHEDULE_PATH)
            log(f"Loaded schedule with {len(station_schedule.shows)} shows")
        except Exception as e:
            log(f"Schedule load failed, using fallback: {e}")

    all_music = get_all_music()
    all_podcasts = get_all_podcasts()

    # Count segments across period folders
    segment_count = sum(len(list((SEGMENTS_DIR / p).glob("*.wav")))
                       for p in ["late_night", "morning", "afternoon", "evening"]
                       if (SEGMENTS_DIR / p).exists())
    segment_count += len(list(SEGMENTS_DIR.glob("*.wav")))  # Plus any in root
    log(f"Total library: {len(all_music)} tracks, {segment_count} segments, {len(all_podcasts)} podcasts")

    queue_size = 15  # Curate 15 tracks at a time

    while running:
        log("Starting encoder...")
        encoder_proc = start_encoder()

        if not wait_for_encoder_ready(encoder_proc):
            log("Encoder failed to connect, retrying in 10s...")
            time.sleep(10)
            continue

        log("Encoder connected to Icecast")

        while running and encoder_proc.poll() is None:
            # Get current program context from schedule
            ctx = get_program_context(station_schedule)
            profile = ctx.music_profile
            segment_interval = ctx.segment_after_tracks

            log(f"🎯 Show: {ctx.show_name} ({ctx.show_id})")
            log(f"   {ctx.show_description}")

            # Create queue based on show's music profile
            queue = create_curated_queue(all_music, queue_size, profile)
            log(f"Queue: {len(queue)} tracks curated for {ctx.show_name}")

            for track in queue:
                if not running or encoder_proc.poll() is not None:
                    break

                # Check if show changed - if so, break and re-curate
                new_ctx = get_program_context(station_schedule)
                if new_ctx.show_id != ctx.show_id:
                    log(f"Show changed to {new_ctx.show_name} - re-curating...")
                    break

                # Check for scheduled or forced podcast
                now = datetime.now()
                current_slot = now.strftime("%Y%m%d%H")
                should_podcast = (
                    ctx.podcasts_enabled
                    and now.hour in ctx.podcast_hours
                    and last_podcast_slot != current_slot
                )

                if all_podcasts and (force_podcast or should_podcast):
                    podcast = select_podcast(all_podcasts)
                    if podcast:
                        podcast_name = clean_name(podcast)
                        podcast_duration = get_track_duration(podcast)
                        duration_str = f" ({int(podcast_duration // 60)}:{int(podcast_duration % 60):02d})" if podcast_duration else ""
                        prefix = "📻 [FORCED] PODCAST:" if force_podcast else "📻 PODCAST:"
                        log(f"{prefix} {podcast_name}{duration_str}")
                        update_now_playing(podcast_name, "podcast", None, ctx.show_id, ctx.show_name)
                        force_podcast = False
                        if pipe_track(podcast, encoder_proc, is_speech=True):
                            last_podcast_slot = current_slot
                            if HISTORY_ENABLED:
                                try:
                                    history = get_history()
                                    history.record_play(
                                        filepath=str(podcast),
                                        track_name=podcast_name,
                                        vibe="podcast",
                                        time_period=ctx.show_id,
                                        listeners=get_listener_count(),
                                    )
                                except Exception:
                                    pass
                        else:
                            log("Podcast pipe failed, continuing...")

                # Handle forced segment
                if force_segment:
                    seg = select_segment(SEGMENTS_DIR)
                    if seg:
                        log(f"🎙 [FORCED] {clean_name(seg, is_segment=True)}")
                        pipe_track(seg, encoder_proc, is_speech=True)
                    force_segment = False

                # Play track (chop if too long)
                mood = classify_track(track)
                name = clean_name(track)
                track_duration = get_track_duration(track)

                start_time = 0
                play_duration = track_duration

                if track_duration and track_duration > MAX_TRACK_DURATION:
                    play_duration = random.uniform(CHUNK_MIN_DURATION, CHUNK_MAX_DURATION)
                    max_start = track_duration - play_duration - 10
                    if max_start > 10:
                        start_time = random.uniform(10, max_start)
                    mins = int(start_time // 60)
                    secs = int(start_time % 60)
                    log(f"♪ {name} [{mood.vibe}, e:{mood.energy:.1f}] (chunk @{mins}:{secs:02d})")
                else:
                    log(f"♪ {name} [{mood.vibe}, e:{mood.energy:.1f}]")

                update_now_playing(name, "music", mood.vibe, ctx.show_id, ctx.show_name)

                if not pipe_track(track, encoder_proc, start_time, play_duration):
                    log("Pipe failed, reconnecting...")
                    break

                if HISTORY_ENABLED:
                    try:
                        history = get_history()
                        history.record_play(
                            filepath=str(track),
                            track_name=name,
                            vibe=mood.vibe,
                            time_period=ctx.show_id,
                            listeners=get_listener_count(),
                        )
                    except Exception:
                        pass

                tracks_since_segment += 1

                # Play segment based on show's segment_after_tracks setting
                if force_segment or tracks_since_segment >= segment_interval:
                    seg = select_segment(SEGMENTS_DIR)
                    if seg:
                        seg_name = clean_name(seg, is_segment=True)
                        is_listener_dedication = "listener_dedication" in seg.name.lower() or "listener_" in seg.name.lower()
                        log(f"🎙 {seg_name}")
                        update_now_playing(seg_name, "segment", None, ctx.show_id, ctx.show_name)
                        if not pipe_track(seg, encoder_proc, is_speech=True):
                            log("Segment pipe failed, reconnecting...")
                            break
                        if is_listener_dedication:
                            try:
                                seg.unlink()
                                log(f"   (dedication played and removed)")
                            except Exception as e:
                                log(f"   (failed to remove dedication: {e})")
                        tracks_since_segment = 0
                        force_segment = False

            if running and encoder_proc.poll() is None:
                log("Queue complete, refreshing for current show...")

        if running:
            log("Encoder died, restarting...")
            time.sleep(2)

    log("=== Stream stopped ===")


if __name__ == "__main__":
    run()
