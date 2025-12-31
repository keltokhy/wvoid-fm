#!/usr/bin/env python3
"""
WVOID-FM Dedication Processor

Reads listener messages and generates on-air dedication segments.

Usage:
    uv run python dedication_processor.py           # Process all unread
    uv run python dedication_processor.py --list    # List pending messages
    uv run python dedication_processor.py --daemon  # Run continuously
"""

import json
import argparse
import time
import sys
from pathlib import Path
from datetime import datetime

from helpers import (
    log,
    get_time_of_day,
    preprocess_for_tts,
    run_claude,
)

# Paths
PROJECT_ROOT = Path(__file__).parent.parent.parent
OUTPUT_DIR = PROJECT_ROOT / "output" / "segments"
VOICE_REF_DIR = PROJECT_ROOT / "mac" / "voice_reference"
CHATTERBOX_DIR = PROJECT_ROOT / "mac" / "chatterbox"
MESSAGES_FILE = Path.home() / ".wvoid" / "messages.json"

# Add chatterbox to path
sys.path.insert(0, str(CHATTERBOX_DIR))


def load_messages() -> list[dict]:
    if not MESSAGES_FILE.exists():
        return []
    try:
        with open(MESSAGES_FILE) as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return []


def save_messages(messages: list[dict]):
    MESSAGES_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(MESSAGES_FILE, "w") as f:
        json.dump(messages, f, indent=2)


def get_unread() -> list[tuple[int, dict]]:
    messages = load_messages()
    return [(i, m) for i, m in enumerate(messages) if not m.get("read", False)]


def mark_read(index: int):
    messages = load_messages()
    if 0 <= index < len(messages):
        messages[index]["read"] = True
        messages[index]["processed_at"] = datetime.now().isoformat()
        save_messages(messages)


def generate_dedication_script(message: dict) -> str | None:
    """Generate a dedication script from a listener message."""
    listener_msg = message.get("message", "").strip()
    timestamp = message.get("timestamp", "")

    try:
        dt = datetime.fromisoformat(timestamp)
        time_str = dt.strftime("%H:%M")
        time_of_day = get_time_of_day(dt.hour)
    except:
        time_str = datetime.now().strftime("%H:%M")
        time_of_day = get_time_of_day(datetime.now().hour)

    prompt = f"""You are The Liminal Operator, DJ of WVOID-FM. A listener sent this message:

"{listener_msg}"

Write a 30-50 word on-air response/dedication. Guidelines:
- Acknowledge the message warmly but maintain your mysterious DJ persona
- If it's a song request, acknowledge you heard it (don't promise to play it)
- If it's a greeting from a location, welcome them to the frequency
- If it's a birthday or special occasion, make it feel special
- If it's philosophical or strange, engage with it cryptically
- Use [pause] for beats of silence
- Never break character or mention being AI

Current time: {time_str} ({time_of_day})

Output ONLY the spoken text."""

    script = run_claude(prompt, timeout=60, min_length=10, strip_quotes=False)
    if script:
        return script

    return None


def process_message(index: int, message: dict, voice_ref: Path | None = None) -> bool:
    """Process a single message into an on-air segment."""
    from tts import render_speech

    listener_msg = message.get("message", "")[:50]
    log(f"Processing: \"{listener_msg}...\"")

    script = generate_dedication_script(message)
    if not script:
        log("Failed to generate script")
        return False

    log(f"Script: {script[:60]}...")

    tts_text = preprocess_for_tts(script, include_cough=False)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = OUTPUT_DIR / f"listener_dedication_{timestamp}.wav"

    if render_speech(tts_text, output_path, voice_ref=voice_ref):
        log(f"Created: {output_path.name}")
        mark_read(index)
        return True

    log("Failed to render audio")
    return False


def list_messages():
    unread = get_unread()
    if not unread:
        print("No unread messages.")
        return

    print(f"\n=== {len(unread)} Unread Messages ===\n")
    for idx, msg in unread:
        ts = msg.get("timestamp", "unknown")
        text = msg.get("message", "")[:60]
        print(f"[{idx}] {ts[:16]}: {text}...")


def process_all(voice_ref: Path | None = None, limit: int | None = None):
    unread = get_unread()
    if not unread:
        log("No unread messages")
        return

    if limit:
        unread = unread[:limit]

    log(f"Processing {len(unread)} messages...")

    success = 0
    for idx, msg in unread:
        if process_message(idx, msg, voice_ref):
            success += 1
        time.sleep(2)

    log(f"Processed {success}/{len(unread)} messages")


def run_daemon(voice_ref: Path | None = None, interval: int = 300):
    log(f"Daemon mode (checking every {interval}s)")

    while True:
        unread = get_unread()
        if unread:
            log(f"Found {len(unread)} unread messages")
            for idx, msg in unread[:3]:
                process_message(idx, msg, voice_ref)
                time.sleep(5)
        time.sleep(interval)


def main():
    parser = argparse.ArgumentParser(description="WVOID-FM Dedication Processor")
    parser.add_argument("--list", action="store_true", help="List pending messages")
    parser.add_argument("--daemon", action="store_true", help="Run continuously")
    parser.add_argument("--interval", type=int, default=300, help="Check interval (seconds)")
    parser.add_argument("--limit", type=int, help="Limit messages to process")
    parser.add_argument("--voice", type=str, help="Voice reference WAV file")
    args = parser.parse_args()

    voice_ref = Path(args.voice) if args.voice else None
    if not voice_ref:
        default_voice = VOICE_REF_DIR / "operator_voice.wav"
        if default_voice.exists():
            voice_ref = default_voice
            log(f"Using voice: {voice_ref}")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    if args.list:
        list_messages()
    elif args.daemon:
        run_daemon(voice_ref, args.interval)
    else:
        process_all(voice_ref, args.limit)


if __name__ == "__main__":
    main()
