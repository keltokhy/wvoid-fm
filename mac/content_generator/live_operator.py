#!/usr/bin/env python3
"""
WVOID-FM Live Operator System

A persistent daemon that:
1. Monitors the stream status
2. Generates DJ segments on demand or on schedule
3. Can be controlled via a simple command interface

Run with: uv run python live_operator.py

Commands (via stdin or control file):
- segment [type] - Generate a segment (song_intro, station_id, hour_marker, dedication, weather)
- status - Show current stream status
- queue - Show pending segments
- quit - Shutdown

For headless/background operation, write commands to:
  ~/.wvoid/commands.txt
"""

import sys
import time
import json
import random
import threading
from pathlib import Path
from datetime import datetime
from queue import Queue, Empty

import httpx

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from script_generator import ScriptGenerator, get_time_of_day

# Paths
CONTROL_DIR = Path.home() / ".wvoid"
COMMAND_FILE = CONTROL_DIR / "commands.txt"
STATUS_FILE = CONTROL_DIR / "status.json"
LOG_FILE = CONTROL_DIR / "operator.log"
OUTPUT_DIR = Path(__file__).parent.parent.parent / "output" / "segments"

# Local stream status
ICECAST_STATUS = "http://localhost:8000/status-json.xsl"
NOW_PLAYING_FILE = Path(__file__).parent.parent.parent / "output" / "now_playing.json"

# Timing
SEGMENT_INTERVAL_MINUTES = 15  # Generate a segment every N minutes
STATUS_CHECK_SECONDS = 30     # Check stream status every N seconds


def log(message: str):
    """Log to file and stdout."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{timestamp}] {message}"
    print(line, flush=True)

    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")


def get_stream_status() -> dict:
    """Get current stream status from Icecast."""
    try:
        response = httpx.get(ICECAST_STATUS, timeout=5)
        data = response.json()
        source = data.get("icestats", {}).get("source", {})
        return {
            "online": True,
            "listeners": source.get("listeners", 0),
            "stream_start": source.get("stream_start_iso8601"),
        }
    except Exception as e:
        return {"online": False, "error": str(e)}


def get_now_playing() -> str:
    """Get currently playing track from local now_playing.json."""
    try:
        if NOW_PLAYING_FILE.exists():
            data = json.loads(NOW_PLAYING_FILE.read_text())
            track = data.get("track")
            if track:
                return track
        return "Unknown"
    except Exception:
        return "Unknown"


def generate_segment(generator: ScriptGenerator, segment_type: str = "random") -> Path | None:
    """Generate a single DJ segment."""
    from tts_renderer import TTSRenderer

    time_of_day = get_time_of_day()

    if segment_type == "random":
        weights = [
            ("song_intro", 40),
            ("station_id", 30),
            ("hour_marker", 15),
            ("dedication", 10),
            ("weather", 5),
        ]
        segment_type = random.choices(
            [t for t, _ in weights],
            weights=[w for _, w in weights],
        )[0]

    log(f"Generating {segment_type} segment...")

    try:
        if segment_type == "song_intro":
            script = generator.generate_song_intro(time_of_day=time_of_day)
        elif segment_type == "hour_marker":
            script = generator.generate_hour_marker(time_of_day)
        elif segment_type == "station_id":
            script = generator.generate_station_id(time_of_day)
        elif segment_type == "dedication":
            script = generator.generate_dedication(time_of_day=time_of_day)
        elif segment_type == "weather":
            script = generator.generate_weather(time_of_day)
        else:
            log(f"Unknown segment type: {segment_type}")
            return None

        log(f"Script: {script[:80]}...")

        # Render TTS
        voice_ref = Path(__file__).parent.parent / "voice_reference" / "operator_voice.wav"
        renderer = TTSRenderer(voice_reference=voice_ref if voice_ref.exists() else None)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{segment_type}_{timestamp}.wav"
        output_path = OUTPUT_DIR / filename
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

        renderer.render(script, output_path)
        log(f"Generated: {output_path.name}")
        return output_path

    except Exception as e:
        log(f"Generation failed: {e}")
        return None


def update_status(status: dict):
    """Write status to file for external monitoring."""
    STATUS_FILE.parent.mkdir(parents=True, exist_ok=True)
    status["updated"] = datetime.now().isoformat()
    with open(STATUS_FILE, "w") as f:
        json.dump(status, f, indent=2)


def read_commands() -> list[str]:
    """Read and clear commands from control file."""
    if not COMMAND_FILE.exists():
        return []

    try:
        commands = COMMAND_FILE.read_text().strip().split("\n")
        COMMAND_FILE.write_text("")  # Clear after reading
        return [c.strip() for c in commands if c.strip()]
    except Exception:
        return []


class LiveOperator:
    """Main operator daemon."""

    def __init__(self):
        self.running = False
        self.generator = None
        self.command_queue = Queue()
        self.last_segment_time = datetime.now()
        self.segments_generated = 0

    def init_generator(self):
        """Initialize the LLM generator."""
        log("Initializing script generator...")
        self.generator = ScriptGenerator()

        if not self.generator.is_available():
            log("WARNING: LM Studio not available. Start it for segment generation.")
            return False

        models = self.generator.list_models()
        log(f"LM Studio connected. Models: {models}")
        return True

    def process_command(self, cmd: str):
        """Process a single command."""
        parts = cmd.lower().split()
        if not parts:
            return

        action = parts[0]

        if action == "segment":
            seg_type = parts[1] if len(parts) > 1 else "random"
            if self.generator and self.generator.is_available():
                path = generate_segment(self.generator, seg_type)
                if path:
                    self.segments_generated += 1
            else:
                log("Cannot generate: LM Studio not available")

        elif action == "status":
            status = get_stream_status()
            now_playing = get_now_playing()
            log(f"Stream: {'ONLINE' if status.get('online') else 'OFFLINE'}")
            log(f"Listeners: {status.get('listeners', 0)}")
            log(f"Now playing: {now_playing}")
            log(f"Segments generated this session: {self.segments_generated}")

        elif action == "queue":
            if OUTPUT_DIR.exists():
                files = list(OUTPUT_DIR.glob("*.wav"))
                log(f"Pending segments: {len(files)}")
                for f in files[-5:]:
                    log(f"  {f.name}")
            else:
                log("No segments queued")

        elif action == "quit" or action == "exit":
            log("Shutdown requested")
            self.running = False

        else:
            log(f"Unknown command: {cmd}")

    def background_loop(self):
        """Background thread for scheduled tasks."""
        while self.running:
            try:
                # Check for commands from file
                for cmd in read_commands():
                    self.command_queue.put(cmd)

                now = datetime.now()

                # Auto-generate segments on schedule
                if self.generator and self.generator.is_available():
                    if (now - self.last_segment_time).total_seconds() > SEGMENT_INTERVAL_MINUTES * 60:
                        self.command_queue.put("segment random")
                        self.last_segment_time = now

                # Update status file
                status = get_stream_status()
                status["now_playing"] = get_now_playing()
                status["segments_generated"] = self.segments_generated
                status["last_segment"] = self.last_segment_time.isoformat()
                update_status(status)

                time.sleep(STATUS_CHECK_SECONDS)

            except Exception as e:
                log(f"Background loop error: {e}")
                time.sleep(10)

    def run(self):
        """Main run loop."""
        log("=" * 50)
        log("WVOID-FM Live Operator starting...")
        log("=" * 50)

        # Setup
        CONTROL_DIR.mkdir(parents=True, exist_ok=True)
        self.init_generator()

        self.running = True

        # Start background thread
        bg_thread = threading.Thread(target=self.background_loop, daemon=True)
        bg_thread.start()

        log("")
        log("Commands: segment [type], status, queue, quit")
        log(f"Or write commands to: {COMMAND_FILE}")
        log("")

        # Main loop - process commands
        while self.running:
            try:
                # Check queue first
                try:
                    cmd = self.command_queue.get_nowait()
                    self.process_command(cmd)
                except Empty:
                    pass

                # Check stdin (non-blocking would be better but this works)
                # For true headless, just use the command file
                import select
                if select.select([sys.stdin], [], [], 1)[0]:
                    line = sys.stdin.readline().strip()
                    if line:
                        self.process_command(line)

            except KeyboardInterrupt:
                log("Interrupted")
                self.running = False
            except Exception as e:
                log(f"Error: {e}")
                time.sleep(1)

        log("Live Operator shutdown complete")


def main():
    operator = LiveOperator()
    operator.run()


if __name__ == "__main__":
    main()
