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
import urllib.request
from datetime import datetime
from pathlib import Path

# Import play history
try:
    from play_history import get_history
    HISTORY_ENABLED = True
except ImportError:
    HISTORY_ENABLED = False

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
    def do_GET(self):
        if self.path == "/now-playing" or self.path == "/now-playing/" or self.path == "/":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
            self.end_headers()

            data = get_now_playing()
            track_stats_update(data)
            payload = json.dumps(data).encode()
            try:
                self.wfile.write(payload)
            except BrokenPipeError:
                pass
        elif self.path == "/health" or self.path == "/health/":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            health = get_health_status()
            try:
                self.wfile.write(json.dumps(health).encode())
            except BrokenPipeError:
                pass
        elif self.path == "/stats" or self.path == "/stats/":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            stats = get_stats()
            try:
                self.wfile.write(json.dumps(stats).encode())
            except BrokenPipeError:
                pass
        elif self.path.startswith("/history"):
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            history_data = get_play_history()
            try:
                self.wfile.write(json.dumps(history_data).encode())
            except BrokenPipeError:
                pass
        elif self.path == "/messages" or self.path == "/messages/":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            messages = get_messages()
            try:
                self.wfile.write(json.dumps(messages).encode())
            except BrokenPipeError:
                pass
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        if self.path == "/message" or self.path == "/message/":
            # Rate limit check
            client_ip = self.client_address[0]
            now = time.time()

            if client_ip in last_message_times:
                elapsed = now - last_message_times[client_ip]
                if elapsed < MESSAGE_COOLDOWN:
                    self.send_response(429)  # Too Many Requests
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Access-Control-Allow-Origin", "*")
                    self.end_headers()
                    wait_time = int(MESSAGE_COOLDOWN - elapsed)
                    self.wfile.write(json.dumps({"error": f"Please wait {wait_time}s"}).encode())
                    return

            # Read and validate message
            try:
                content_length = int(self.headers.get('Content-Length', 0))
                body = self.rfile.read(content_length).decode('utf-8')
                data = json.loads(body)
                message = data.get('message', '').strip()

                if not message or len(message) > 280:
                    self.send_response(400)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Access-Control-Allow-Origin", "*")
                    self.end_headers()
                    self.wfile.write(json.dumps({"error": "Invalid message"}).encode())
                    return

                # Save message
                save_message(message, client_ip)
                last_message_times[client_ip] = now

                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(json.dumps({"status": "received"}).encode())

            except Exception as e:
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e)}).encode())
        else:
            self.send_response(404)
            self.end_headers()

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
        result = subprocess.run(
            ["pgrep", "-f", name],
            capture_output=True,
            timeout=5,
        )
        return result.returncode == 0
    except:
        return False


def check_url(url: str, timeout: int = 2) -> bool:
    """Check if URL responds."""
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            return response.status == 200
    except:
        return False


def get_health_status() -> dict:
    """Get comprehensive health status of all components."""
    icecast_ok = check_url(ICECAST_STATUS_URL)
    streamer_ok = check_process("stream_gapless")
    tunnel_ok = check_process("cloudflared")
    api_ok = True  # We're responding, so API is up

    all_ok = icecast_ok and streamer_ok and tunnel_ok

    return {
        "status": "healthy" if all_ok else "degraded",
        "timestamp": datetime.now().isoformat(),
        "components": {
            "icecast": {"status": "up" if icecast_ok else "down"},
            "streamer": {"status": "up" if streamer_ok else "down"},
            "tunnel": {"status": "up" if tunnel_ok else "down"},
            "api": {"status": "up" if api_ok else "down"},
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
    data = {"track": None, "type": None, "listeners": 0}

    try:
        if NOW_PLAYING_FILE.exists():
            with open(NOW_PLAYING_FILE, "r") as f:
                data = json.load(f)
    except:
        pass

    # Add listener count
    data["listeners"] = get_listeners()

    return data


def run():
    with socketserver.TCPServer(("", PORT), NowPlayingHandler) as httpd:
        print(f"Now Playing API running on http://localhost:{PORT}/now-playing")
        print("Ctrl+C to stop")
        httpd.serve_forever()


if __name__ == "__main__":
    run()
