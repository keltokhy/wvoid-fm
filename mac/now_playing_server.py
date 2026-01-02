#!/usr/bin/env python3
"""
WVOID-FM Now Playing API

Simple HTTP server that exposes the current track info.
Reads from the now_playing.json file written by the streamer.
"""

import http.server
import json
import os
import socketserver
import subprocess
import time
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

# Import play history
try:
    from play_history import get_history
    HISTORY_ENABLED = True
except ImportError:
    HISTORY_ENABLED = False

# Import Discogs lookup and QR generation
try:
    from discogs_lookup import search_discogs, DiscogsResult, HAS_CREDENTIALS as DISCOGS_HAS_CREDS
    DISCOGS_ENABLED = True
except ImportError:
    DISCOGS_ENABLED = False
    DISCOGS_HAS_CREDS = False

try:
    from qr_generator import generate_qr_png, generate_qr_data_url, HAS_QRCODE
    QR_ENABLED = HAS_QRCODE
except ImportError:
    QR_ENABLED = False

# Discogs lookup cache to avoid repeated lookups for the same track
_discogs_cache: dict[str, dict | None] = {}
_discogs_last_track: str | None = None

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_NOW_PLAYING_FILE = PROJECT_ROOT / "output" / "now_playing.json"
MESSAGES_FILE = Path.home() / ".wvoid" / "messages.json"

# Rate limiting for messages
MESSAGE_COOLDOWN = 300  # 5 minutes between messages per IP
last_message_times: dict[str, float] = {}

PORT = int(os.environ.get("WVOID_NOW_PLAYING_PORT", "8001"))
NOW_PLAYING_FILE = Path(
    os.environ.get("WVOID_NOW_PLAYING_FILE", str(DEFAULT_NOW_PLAYING_FILE))
).expanduser()
ICECAST_STATUS_URL = os.environ.get(
    "ICECAST_STATUS_URL",
    "http://localhost:8000/status-json.xsl",
)

# Server start time for uptime tracking
SERVER_START_TIME = time.time()
TRACKS_PLAYED = 0
TOTAL_LISTENERS_SERVED = 0
LAST_TRACK = None


class NowPlayingHandler(http.server.BaseHTTPRequestHandler):
    def _send_json(self, data, cache_control=None):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        if cache_control:
            self.send_header("Cache-Control", cache_control)
        self.end_headers()
        try:
            self.wfile.write(json.dumps(data).encode())
        except BrokenPipeError:
            pass

    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path.rstrip("/") or "/"

        if path in ("/now-playing", "/"):
            data = get_now_playing()
            track_stats_update(data)
            self._send_json(data, "no-cache, no-store, must-revalidate")
        elif path == "/health":
            self._send_json(get_health_status())
        elif path == "/stats":
            self._send_json(get_stats())
        elif path.startswith("/history"):
            self._send_json(get_play_history())
        elif path == "/messages":
            self._send_json(get_messages())
        elif path == "/discogs":
            self._send_json(get_discogs_info())
        elif path == "/qr":
            qr_bytes = get_qr_code()
            if qr_bytes:
                self.send_response(200)
                self.send_header("Content-Type", "image/png")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Cache-Control", "public, max-age=60")
                self.end_headers()
                try:
                    self.wfile.write(qr_bytes)
                except BrokenPipeError:
                    pass
            else:
                self.send_response(404)
                self.send_header("Content-Type", "application/json")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                try:
                    self.wfile.write(json.dumps({"error": "No Discogs info available"}).encode())
                except BrokenPipeError:
                    pass
        else:
            self.send_response(404)
            self.end_headers()

    def _send_error(self, code, msg):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps({"error": msg}).encode())

    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path.rstrip("/")
        if path != "/message":
            self.send_response(404)
            self.end_headers()
            return

        client_ip = self.client_address[0]
        now = time.time()
        if client_ip in last_message_times and now - last_message_times[client_ip] < MESSAGE_COOLDOWN:
            wait_time = int(MESSAGE_COOLDOWN - (now - last_message_times[client_ip]))
            return self._send_error(429, f"Please wait {wait_time}s")

        try:
            content_length = int(self.headers.get('Content-Length', 0))
            data = json.loads(self.rfile.read(content_length).decode('utf-8'))
            message = data.get('message', '').strip()
            if not message or len(message) > 280:
                return self._send_error(400, "Invalid message")

            save_message(message, client_ip)
            last_message_times[client_ip] = now
            self._send_json({"status": "received"})
        except Exception as e:
            self._send_error(500, str(e))

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def log_message(self, format, *args):
        pass  # Suppress logging


def get_listeners() -> int:
    """Get listener count from local Icecast."""
    try:
        with urllib.request.urlopen(ICECAST_STATUS_URL, timeout=2) as response:
            data = json.loads(response.read().decode())
            source = data.get("icestats", {}).get("source", {})
            return source.get("listeners", 0)
    except:
        pass
    return 0


def check_process(name: str) -> bool:
    """Check if process is running."""
    try:
        return subprocess.run(["pgrep", "-f", name], capture_output=True, timeout=5).returncode == 0
    except:
        return False


def check_url(url: str, timeout: int = 2) -> bool:
    """Check if URL responds."""
    try:
        return urllib.request.urlopen(url, timeout=timeout).status == 200
    except:
        return False


def get_health_status() -> dict:
    """Get comprehensive health status of all components."""
    icecast_ok = check_url(ICECAST_STATUS_URL)
    streamer_ok = check_process("stream_gapless")
    tunnel_ok = check_process("cloudflared")
    return {
        "status": "healthy" if icecast_ok and streamer_ok and tunnel_ok else "degraded",
        "timestamp": datetime.now().isoformat(),
        "components": {
            "icecast": {"status": "up" if icecast_ok else "down"},
            "streamer": {"status": "up" if streamer_ok else "down"},
            "tunnel": {"status": "up" if tunnel_ok else "down"},
            "api": {"status": "up"},  # We're responding
        },
        "uptime_seconds": int(time.time() - SERVER_START_TIME),
    }


def get_stats() -> dict:
    """Get server statistics."""
    uptime = int(time.time() - SERVER_START_TIME)
    hours = uptime // 3600
    minutes = (uptime % 3600) // 60

    return {
        "uptime": f"{hours}h {minutes}m",
        "uptime_seconds": uptime,
        "tracks_played": TRACKS_PLAYED,
        "total_listeners_served": TOTAL_LISTENERS_SERVED,
        "current_listeners": get_listeners(),
        "api_started": datetime.fromtimestamp(SERVER_START_TIME).isoformat(),
    }


def track_stats_update(data: dict):
    """Update track statistics."""
    global TRACKS_PLAYED, TOTAL_LISTENERS_SERVED, LAST_TRACK

    current_track = data.get("track")
    if current_track and current_track != LAST_TRACK:
        TRACKS_PLAYED += 1
        LAST_TRACK = current_track

    listeners = data.get("listeners", 0)
    if listeners > 0:
        TOTAL_LISTENERS_SERVED += listeners


def get_play_history() -> dict:
    """Get play history from database."""
    if not HISTORY_ENABLED:
        return {"enabled": False, "message": "History tracking not available"}

    try:
        history = get_history()
        return {
            "enabled": True,
            "recent": history.get_recent_plays(50),
            "stats": history.get_stats(),
            "most_played": history.get_most_played(10),
        }
    except Exception as e:
        return {"enabled": True, "error": str(e)}


def save_message(message: str, ip: str):
    """Save a listener message to the queue."""
    MESSAGES_FILE.parent.mkdir(parents=True, exist_ok=True)

    # Load existing messages
    messages = []
    if MESSAGES_FILE.exists():
        try:
            with open(MESSAGES_FILE) as f:
                messages = json.load(f)
        except:
            messages = []

    # Add new message
    messages.append({
        "message": message,
        "ip": ip,
        "timestamp": datetime.now().isoformat(),
        "read": False,
    })

    # Keep only last 100 messages
    messages = messages[-100:]

    # Save
    with open(MESSAGES_FILE, "w") as f:
        json.dump(messages, f, indent=2)


def get_messages(limit: int = 20) -> list[dict]:
    """Get recent messages."""
    if not MESSAGES_FILE.exists():
        return []

    try:
        with open(MESSAGES_FILE) as f:
            messages = json.load(f)
        # Return newest first, hide IP
        return [
            {"message": m["message"], "timestamp": m["timestamp"], "read": m.get("read", False)}
            for m in reversed(messages[-limit:])
        ]
    except:
        return []


def get_now_playing() -> dict:
    """Read current track info from JSON file."""
    try:
        data = json.loads(NOW_PLAYING_FILE.read_text()) if NOW_PLAYING_FILE.exists() else {}
    except:
        data = {}
    data["listeners"] = get_listeners()
    return data


def _qr_data_url_for(discogs_data: dict | None) -> str | None:
    if not QR_ENABLED or not discogs_data or not discogs_data.get("url"):
        return None
    return generate_qr_data_url(discogs_data["url"])


def get_discogs_info() -> dict:
    """Get Discogs info for the currently playing track.

    Returns a dict with Discogs release info, or an error/status message.
    Caches results to avoid repeated API calls for the same track.
    """
    global _discogs_cache, _discogs_last_track

    if not DISCOGS_ENABLED:
        return {"enabled": False, "message": "Discogs lookup not available"}

    if not DISCOGS_HAS_CREDS:
        return {
            "enabled": False,
            "message": "Discogs API requires authentication",
            "setup": "Set DISCOGS_TOKEN env var. Get token at https://www.discogs.com/settings/developers"
        }

    # Get current track
    now_playing = get_now_playing()
    track_name = now_playing.get("track")
    track_type = now_playing.get("type")
    vibe = now_playing.get("vibe")

    # Only look up music tracks, not segments or podcasts
    if not track_name or track_type != "music":
        return {"enabled": True, "track": track_name, "discogs": None, "reason": "Not a music track"}

    # Check cache
    if track_name in _discogs_cache:
        cached = _discogs_cache[track_name]
        if cached is None:
            return {"enabled": True, "track": track_name, "discogs": None, "reason": "Not found on Discogs"}
        return {
            "enabled": True,
            "track": track_name,
            "discogs": cached,
            "qr_data_url": _qr_data_url_for(cached),
        }

    # Perform lookup (only if track changed)
    if track_name != _discogs_last_track:
        _discogs_last_track = track_name
        result = search_discogs(track_name, vibe)

        if result:
            discogs_data = {
                "release_id": result.release_id,
                "title": result.title,
                "artist": result.artist,
                "year": result.year,
                "url": result.url,
                "thumb_url": result.thumb_url,
                "label": result.label,
                "format": result.format,
            }
            _discogs_cache[track_name] = discogs_data
            return {
                "enabled": True,
                "track": track_name,
                "discogs": discogs_data,
                "qr_data_url": _qr_data_url_for(discogs_data),
            }
        else:
            _discogs_cache[track_name] = None
            return {"enabled": True, "track": track_name, "discogs": None, "reason": "Not found on Discogs"}

    # Track hasn't changed, return cached or pending
    if track_name in _discogs_cache:
        cached = _discogs_cache[track_name]
        if cached is None:
            return {"enabled": True, "track": track_name, "discogs": None, "reason": "Not found on Discogs"}
        return {
            "enabled": True,
            "track": track_name,
            "discogs": cached,
            "qr_data_url": _qr_data_url_for(cached),
        }

    return {"enabled": True, "track": track_name, "discogs": None, "reason": "Lookup pending"}


def get_qr_code() -> bytes | None:
    """Get QR code PNG for the current track's Discogs page."""
    if not QR_ENABLED:
        return None
    discogs_data = get_discogs_info().get("discogs")
    if not discogs_data or not discogs_data.get("url"):
        return None
    return generate_qr_png(discogs_data["url"])


class ReusableTCPServer(socketserver.TCPServer):
    allow_reuse_address = True


def run():
    with ReusableTCPServer(("", PORT), NowPlayingHandler) as httpd:
        print(f"Now Playing API running on http://localhost:{PORT}/now-playing")
        print(f"  /discogs  - Current track's Discogs info")
        print(f"  /qr       - QR code for Discogs page (PNG)")
        if DISCOGS_ENABLED:
            if DISCOGS_HAS_CREDS:
                print("Discogs lookup: enabled (credentials found)")
            else:
                print("Discogs lookup: disabled (no DISCOGS_TOKEN env var)")
                print("  Set DISCOGS_TOKEN or DISCOGS_KEY+DISCOGS_SECRET")
                print("  Get credentials at https://www.discogs.com/settings/developers")
        else:
            print("Discogs lookup: disabled (module not found)")
        print(f"QR generation:  {'enabled' if QR_ENABLED else 'disabled (install qrcode)'}")
        print("Ctrl+C to stop")
        httpd.serve_forever()


if __name__ == "__main__":
    run()
