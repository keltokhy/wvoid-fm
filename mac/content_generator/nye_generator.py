#!/usr/bin/env python3
"""
Generate New Year's Eve transition content for WVOID-FM.
Special segments for the midnight transition from 2025 to 2026.
"""

import os
import time
from datetime import datetime, timedelta
from pathlib import Path

# Force Kokoro backend for speed
os.environ["WVOID_TTS_BACKEND"] = "kokoro"

from helpers import log, preprocess_for_tts, run_claude
from tts_engine import render_speech
from persona import OPERATOR_IDENTITY, OPERATOR_VOICE

PROJECT_ROOT = Path(__file__).parent.parent.parent
OUTPUT_DIR = PROJECT_ROOT / "output" / "segments"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# NYE-specific segment types
NYE_SEGMENTS = {
    "nye_countdown_hour": {
        "times": ["11:00 PM", "11:15 PM", "11:30 PM", "11:45 PM"],
        "prompt": """Write a 60-80 word segment for {time} on New Year's Eve.
The year is ending. {minutes_left} minutes until midnight.
Acknowledge the weight of the moment - another year passing, another beginning.
Reference the listeners still awake, those at parties, those alone, those working.
The radio as companion through the transition.""",
    },
    "nye_final_minutes": {
        "times": ["11:50 PM", "11:55 PM", "11:58 PM"],
        "prompt": """Write a 40-60 word segment for {time} on New Year's Eve.
Only {minutes_left} minutes left in the year. The final moments.
Intimate, quiet acknowledgment. No forced celebration.
Just presence. The signal persists through the turn of the year.""",
    },
    "nye_midnight": {
        "times": ["12:00 AM"],
        "prompt": """Write a 80-100 word midnight segment for New Year's Day.
It is now midnight. The year has changed. 2025 becomes 2026.
This is the moment. Don't be corny or forced - be present.
Acknowledge those still listening. The radio carried them across.
Welcome to the new year. The signal continues.
Use [pause] for the weight of the moment.""",
    },
    "nye_aftermath": {
        "times": ["12:05 AM", "12:15 AM", "12:30 AM", "1:00 AM", "2:00 AM"],
        "prompt": """Write a 50-70 word segment for {time} on New Year's Day.
The year has turned. The moment has passed. Now it's just... tomorrow.
The quiet after midnight. Those still awake have chosen to be here.
Late night radio energy - contemplative, gentle, present.""",
    },
    "nye_reflection": {
        "times": ["11:30 PM", "12:30 AM"],
        "prompt": """Write a 150-200 word reflection for {time} around New Year's.
A longer piece about transitions, endings, beginnings.
What a year contains. What we carry forward.
The democracy of midnight - everyone experiences it together.
Use [pause] liberally. Let the thoughts breathe.""",
    },
}


def parse_time(time_str: str) -> tuple[int, int]:
    """Parse '11:30 PM' to (23, 30)."""
    dt = datetime.strptime(time_str, "%I:%M %p")
    return (dt.hour, dt.minute)


def minutes_until_midnight(hour: int, minute: int) -> int:
    """Calculate minutes until midnight from given time."""
    if hour < 12:  # Already past midnight
        return 0
    total_minutes = hour * 60 + minute
    midnight = 24 * 60
    return midnight - total_minutes


def generate_nye_segment(seg_type: str, time_str: str) -> Path | None:
    """Generate a single NYE segment."""
    hour, minute = parse_time(time_str)
    mins_left = minutes_until_midnight(hour, minute)

    config = NYE_SEGMENTS[seg_type]
    prompt = config["prompt"].format(
        time=time_str,
        minutes_left=mins_left if mins_left > 0 else "zero",
    )

    # Build time context
    if hour >= 23:
        period = "The final hour of the year."
    elif hour == 0:
        period = "The first hour of the new year."
    else:
        period = "The early hours of the new year."

    full_prompt = f"""{OPERATOR_IDENTITY.strip()}

{OPERATOR_VOICE.strip()}

CRITICAL CONTEXT:
This is New Year's Eve/Day 2025-2026.
This segment will broadcast at EXACTLY {time_str}.
{period}
The listener is experiencing this moment in real time.
Be present. Be warm. Don't be cheesy or forced.

{prompt}

Write only the script. Use [pause] for beats of silence."""

    script = run_claude(full_prompt, timeout=180, strip_quotes=True)
    if not script:
        log(f"  Failed to generate script for {time_str}")
        return None

    processed = preprocess_for_tts(script)

    # Filename: use Jan 1 2026 for post-midnight, Dec 31 2025 for pre-midnight
    if hour < 12:
        date_str = "20260101"
    else:
        date_str = "20251231"

    time_tag = f"{hour:02d}{minute:02d}"
    timestamp = datetime.now().strftime("%S%f")[:4]
    output_path = OUTPUT_DIR / f"{seg_type}_{date_str}_{time_tag}_{timestamp}.wav"

    if not render_speech(processed, output_path):
        log(f"  Failed to render TTS for {time_str}")
        return None

    return output_path


def main():
    log("=== WVOID-FM New Year's Eve Content Generator ===")
    log(f"Generating content for the 2025→2026 transition")

    segments_created = 0

    for seg_type, config in NYE_SEGMENTS.items():
        log(f"\n--- {seg_type} ---")
        for time_str in config["times"]:
            log(f"  Generating for {time_str}...")

            result = generate_nye_segment(seg_type, time_str)

            if result:
                segments_created += 1
                log(f"  ✓ Created: {result.name}")
            else:
                log(f"  ✗ Failed")

            time.sleep(0.5)

    log(f"\n=== Complete ===")
    log(f"Created {segments_created} NYE segments")


if __name__ == "__main__":
    main()
