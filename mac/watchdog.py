#!/usr/bin/env python3
"""
WVOID-FM Watchdog
Monitors all radio components and auto-restarts on failure.
Sends Pushover alerts when things go wrong.
"""

import subprocess
import urllib.request
import json
import time
import os
from datetime import datetime
from pathlib import Path

# Configuration
CHECK_INTERVAL = 30  # seconds
MAX_RETRIES = 3
LOG_FILE = Path("/tmp/wvoid_watchdog.log")

# Pushover credentials (from environment)
PUSHOVER_USER = os.environ.get("PUSHOVER_USER", "")
PUSHOVER_TOKEN = os.environ.get("PUSHOVER_TOKEN", "")

# Component definitions
COMPONENTS = {
    "icecast": {
        "check_url": "http://localhost:8000/status-json.xsl",
        "process_name": "icecast",
        "start_cmd": ["/opt/homebrew/opt/icecast/bin/icecast", "-c", "/Volumes/K3/agent-working-space/projects/active/2025-12-29-radio-station/config/icecast.xml"],
        "critical": True,
    },
    "streamer": {
        "check_url": None,  # Check by process
        "process_name": "stream_gapless",
        "start_cmd": ["uv", "run", "python", "/Volumes/K3/agent-working-space/projects/active/2025-12-29-radio-station/mac/stream_gapless.py"],
        "critical": True,
    },
    "tunnel": {
        "check_url": None,
        "process_name": "cloudflared",
        "start_cmd": ["cloudflared", "tunnel", "run", "wvoid-radio"],
        "critical": True,
    },
    "api": {
        "check_url": "http://localhost:8001/now-playing",
        "process_name": "now_playing_server",
        "start_cmd": ["uv", "run", "python", "/Volumes/K3/agent-working-space/projects/active/2025-12-29-radio-station/mac/now_playing_server.py"],
        "critical": False,
    },
}

# Track failure counts and alert cooldowns
failure_counts: dict[str, int] = {name: 0 for name in COMPONENTS}
last_alert_time: dict[str, float] = {name: 0 for name in COMPONENTS}
ALERT_COOLDOWN = 300  # Don't spam alerts - 5 min cooldown per component


def log(message: str):
    """Log with timestamp."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{timestamp}] {message}"
    print(line)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")


def send_pushover(title: str, message: str, priority: int = 0):
    """Send Pushover notification."""
    if not PUSHOVER_USER or not PUSHOVER_TOKEN:
        log("Pushover credentials not configured, skipping alert")
        return False

    try:
        data = {
            "token": PUSHOVER_TOKEN,
            "user": PUSHOVER_USER,
            "title": title,
            "message": message,
            "priority": priority,
            "sound": "alien" if priority >= 1 else "pushover",
        }

        req = urllib.request.Request(
            "https://api.pushover.net/1/messages.json",
            data=json.dumps(data).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        with urllib.request.urlopen(req, timeout=10) as response:
            if response.status == 200:
                log(f"Pushover alert sent: {title}")
                return True
    except Exception as e:
        log(f"Failed to send Pushover alert: {e}")

    return False


def check_url(url: str, timeout: int = 5) -> bool:
    """Check if URL is responding."""
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            return response.status == 200
    except Exception:
        return False


def check_process(name: str) -> bool:
    """Check if process is running by name."""
    try:
        result = subprocess.run(
            ["pgrep", "-f", name],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return result.returncode == 0
    except Exception:
        return False


def start_component(name: str, config: dict) -> bool:
    """Start a component in the background."""
    try:
        log(f"Starting {name}...")
        subprocess.Popen(
            config["start_cmd"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        time.sleep(3)  # Give it time to start
        return True
    except Exception as e:
        log(f"Failed to start {name}: {e}")
        return False


def check_component(name: str, config: dict) -> bool:
    """Check if component is healthy."""
    # Try URL check first
    if config["check_url"]:
        return check_url(config["check_url"])

    # Fall back to process check
    return check_process(config["process_name"])


def handle_failure(name: str, config: dict):
    """Handle component failure with retries and alerts."""
    global failure_counts, last_alert_time

    failure_counts[name] += 1
    log(f"{name} FAILED (attempt {failure_counts[name]}/{MAX_RETRIES})")

    # Try to restart
    if failure_counts[name] <= MAX_RETRIES:
        if start_component(name, config):
            # Check if it came back
            time.sleep(2)
            if check_component(name, config):
                log(f"{name} recovered after restart")
                failure_counts[name] = 0
                return

    # Still down after retries - send alert
    now = time.time()
    if now - last_alert_time[name] > ALERT_COOLDOWN:
        priority = 1 if config["critical"] else 0
        send_pushover(
            f"WVOID-FM: {name} DOWN",
            f"{name} has failed after {MAX_RETRIES} restart attempts. "
            f"Manual intervention may be required.",
            priority=priority,
        )
        last_alert_time[name] = now


def handle_recovery(name: str):
    """Handle component recovery."""
    global failure_counts, last_alert_time

    if failure_counts[name] > 0:
        log(f"{name} recovered")
        # Send recovery notification if we previously alerted
        if last_alert_time[name] > 0:
            send_pushover(
                f"WVOID-FM: {name} RECOVERED",
                f"{name} is back online.",
                priority=-1,  # Low priority for recovery
            )
        failure_counts[name] = 0


def run_checks():
    """Run all component checks."""
    all_ok = True
    status = []

    for name, config in COMPONENTS.items():
        is_healthy = check_component(name, config)

        if is_healthy:
            handle_recovery(name)
            status.append(f"{name}: OK")
        else:
            handle_failure(name, config)
            status.append(f"{name}: FAILED")
            all_ok = False

    return all_ok, status


def main():
    """Main watchdog loop."""
    log("=" * 50)
    log("WVOID-FM Watchdog starting")
    log(f"Monitoring: {', '.join(COMPONENTS.keys())}")
    log(f"Check interval: {CHECK_INTERVAL}s")
    log(f"Pushover configured: {'Yes' if PUSHOVER_USER else 'No'}")
    log("=" * 50)

    # Initial status
    all_ok, status = run_checks()
    for s in status:
        log(s)

    if all_ok:
        log("All components healthy")

    # Main loop
    while True:
        time.sleep(CHECK_INTERVAL)
        all_ok, status = run_checks()

        # Only log if something changed or every 10 minutes
        if not all_ok:
            for s in status:
                if "FAILED" in s:
                    log(s)


if __name__ == "__main__":
    main()
