#!/usr/bin/env python3
"""
WVOID-FM Listener Message Responder

Generates personalized DJ segments responding to listener messages.
"""

import json
import sys
from datetime import datetime
from pathlib import Path

from helpers import log, get_time_of_day, preprocess_for_tts, run_claude, find_voice_reference
from persona import (
    OPERATOR_IDENTITY,
    OPERATOR_VOICE,
    OPERATOR_ANTI_PATTERNS,
    get_operator_context,
)

PROJECT_ROOT = Path(__file__).parent.parent.parent
OUTPUT_DIR = PROJECT_ROOT / "output" / "segments"
SCRIPTS_DIR = PROJECT_ROOT / "output" / "scripts"
VOICE_REF_DIR = PROJECT_ROOT / "mac" / "voice_reference"


def generate_listener_response(message: str) -> str | None:
    """Generate a response to a listener message."""
    ctx = get_operator_context()

    prompt = f"""{OPERATOR_IDENTITY.strip()}

{OPERATOR_VOICE.strip()}

{OPERATOR_ANTI_PATTERNS.strip()}

CURRENT STATE:
Time: {ctx['current_time']} ({ctx['period']})
Mood: {ctx['mood']}
Your state: {ctx['operator_state']}

TECHNICAL:
- Use [pause] for beats of silence
- Output ONLY the spoken text. No quotes or explanations.

---

A listener just sent this message: "{message}"

Write a 30-60 word on-air acknowledgment/response.

GUIDELINES FOR LISTENER RESPONSES:
- Acknowledge them warmly but don't be saccharine
- If it's a song request: acknowledge the taste, say you'll see what you can do
  (WVOID doesn't take specific requests, but the sentiment matters)
- If it's a greeting or thank you: respond in kind with the station's contemplative vibe
- If it's playful/silly: be playfully cryptic back. Dry humor is welcome.
- If they're sharing something personal: honor it. Don't over-comfort, just acknowledge.
- They reached out in the dark. That means something. Treat it accordingly."""

    return run_claude(prompt, timeout=60, min_length=20, strip_quotes=False)


def render_segment(script: str, segment_name: str) -> Path | None:
    """Render a script to audio."""
    from tts_engine import render_speech

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = OUTPUT_DIR / f"listener_{segment_name}_{timestamp}.wav"

    processed = preprocess_for_tts(script)
    voice_ref = find_voice_reference(VOICE_REF_DIR)

    log(f"Rendering: {processed[:50]}...")

    if render_speech(processed, output_path, voice_ref=voice_ref):
        # Save script metadata
        SCRIPTS_DIR.mkdir(parents=True, exist_ok=True)
        meta_path = SCRIPTS_DIR / f"listener_{segment_name}_{timestamp}.json"
        with open(meta_path, "w") as f:
            json.dump({
                "type": "listener_response",
                "script": script,
                "time_of_day": get_time_of_day(),
                "generated_at": datetime.now().isoformat(),
            }, f, indent=2)

        log(f"Created: {output_path.name}")
        return output_path

    return None


def process_messages(messages: list[dict]) -> int:
    """Process a list of listener messages."""
    success = 0

    for i, msg in enumerate(messages):
        content = msg.get("message", "").strip()
        if not content:
            continue

        log(f"\n[{i+1}/{len(messages)}] Processing: {content[:40]}...")

        script = generate_listener_response(content)
        if not script:
            log("Failed to generate script")
            continue

        log(f"Script: {script[:60]}...")

        # Use a sanitized version of the message for naming
        safe_name = "".join(c if c.isalnum() else "_" for c in content[:20]).strip("_")

        if render_segment(script, safe_name):
            success += 1

    return success


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Respond to listener messages")
    parser.add_argument("--message", "-m", help="Single message to respond to")
    parser.add_argument("--file", "-f", type=Path, help="JSON file with messages")
    args = parser.parse_args()

    if args.message:
        script = generate_listener_response(args.message)
        if script:
            print(f"\nScript:\n{script}\n")
            render_segment(script, "manual")
    elif args.file:
        with open(args.file) as f:
            messages = json.load(f)
        unread = [m for m in messages if not m.get("read", False)]
        processed = process_messages(unread)
        log(f"\nProcessed {processed}/{len(unread)} messages")
    else:
        print("Provide --message or --file")
