#!/usr/bin/env python3
"""
Generate personalized listener response segments for WVOID-FM.

Usage:
    uv run python listener_response.py "Go DJ-Claude, hi from the Netherlands!"
    uv run python listener_response.py --request "play billie jean"
"""

import argparse
import json
from datetime import datetime
from pathlib import Path

from helpers import log, preprocess_for_tts, run_claude, find_voice_reference
from persona import OPERATOR_IDENTITY, OPERATOR_VOICE, OPERATOR_ANTI_PATTERNS, get_operator_context
from tts_engine import render_speech

PROJECT_ROOT = Path(__file__).parent.parent.parent
OUTPUT_DIR = PROJECT_ROOT / "output" / "segments"
SCRIPTS_DIR = PROJECT_ROOT / "output" / "scripts"
VOICE_REF_DIR = PROJECT_ROOT / "mac" / "voice_reference"


def generate_listener_response(message: str, is_request: bool = False) -> Path | None:
    """Generate a personalized response to a listener message."""
    ctx = get_operator_context()

    persona = f"""{OPERATOR_IDENTITY.strip()}

{OPERATOR_VOICE.strip()}

{OPERATOR_ANTI_PATTERNS.strip()}

CURRENT STATE:
Time: {ctx['current_time']} ({ctx['period']})
Mood: {ctx['mood']}

TECHNICAL:
- Use [pause] for beats of silence
- Output ONLY the spoken text. No quotes, headers, or explanations."""

    if is_request:
        prompt = f"""{persona}

LISTENER REQUEST: "{message}"

Write a 25-45 word response acknowledging this song request.
You cannot actually play specific songs on command - your music selection is curated.
But acknowledge the request warmly. Maybe the song will come around. Maybe something in that spirit.
The gesture matters more than the fulfillment."""
    else:
        prompt = f"""{persona}

LISTENER MESSAGE: "{message}"

Write a 30-50 word response to this listener.
Acknowledge them specifically - their location if mentioned, the sentiment they shared.
This is late night radio - someone reached out from the void. That matters.
Keep the WVOID mystique but let warmth through."""

    script = run_claude(prompt, timeout=60, min_length=20)
    if not script:
        log("Failed to generate script")
        return None

    log(f"Script: {script}")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    segment_type = "listener_response"
    output_path = OUTPUT_DIR / f"{segment_type}_{timestamp}.wav"

    processed = preprocess_for_tts(script)
    voice_ref = find_voice_reference(VOICE_REF_DIR)

    if render_speech(processed, output_path, voice_ref=voice_ref):
        SCRIPTS_DIR.mkdir(parents=True, exist_ok=True)
        meta_path = SCRIPTS_DIR / f"{segment_type}_{timestamp}.json"
        with open(meta_path, "w") as f:
            json.dump({
                "type": segment_type,
                "script": script,
                "original_message": message,
                "is_request": is_request,
                "generated_at": datetime.now().isoformat(),
            }, f, indent=2)

        log(f"Created: {output_path.name}")
        return output_path

    log("TTS failed")
    return None


def main():
    parser = argparse.ArgumentParser(description="Generate listener response segment")
    parser.add_argument("message", help="The listener message to respond to")
    parser.add_argument("--request", action="store_true", help="This is a song request")
    args = parser.parse_args()

    generate_listener_response(args.message, is_request=args.request)


if __name__ == "__main__":
    main()
