#!/usr/bin/env python3
"""
WVOID-FM Headless DJ Generator

Generates DJ segments using Claude for scripts and Chatterbox for TTS.

Usage:
    uv run python headless_dj_generator.py --count 10
    uv run python headless_dj_generator.py --daemon
"""

import json
import random
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
    find_voice_reference,
    fetch_headlines,
    format_headlines,
)
from persona import (
    OPERATOR_NAME,
    STATION_NAME,
    OPERATOR_IDENTITY,
    OPERATOR_VOICE,
    OPERATOR_ANTI_PATTERNS,
    get_operator_context,
)

# Paths
PROJECT_ROOT = Path(__file__).parent.parent.parent
OUTPUT_DIR = PROJECT_ROOT / "output" / "segments"
SCRIPTS_DIR = PROJECT_ROOT / "output" / "scripts"
VOICE_REF_DIR = PROJECT_ROOT / "mac" / "voice_reference"

# Segment types with weights
SEGMENT_TYPES = [
    ("station_id", 8),
    ("hour_marker", 6),
    ("song_intro", 8),
    ("dedication", 6),
    ("weather", 4),
    ("news", 14),
    ("monologue", 18),
    ("music_history", 14),
    ("late_night_thoughts", 12),
    ("long_talk", 22),
]


def generate_script(segment_type: str) -> str | None:
    """Generate DJ script using Claude CLI with full operator context."""
    ctx = get_operator_context()

    # Build the persona header (shared across all segments)
    persona = f"""{OPERATOR_IDENTITY.strip()}

{OPERATOR_VOICE.strip()}

{OPERATOR_ANTI_PATTERNS.strip()}

CURRENT STATE:
Time: {ctx['current_time']} ({ctx['period']})
Mood: {ctx['mood']}
Your state: {ctx['operator_state']}

TECHNICAL:
- Use [pause] for beats of silence (rendered as "..." in TTS)
- Use [chuckle] sparingly for dry amusement
- Output ONLY the spoken text. No quotes, headers, stage directions, or explanations."""

    # Segment-specific prompts (much shorter now - persona does the heavy lifting)
    segment_prompts = {
        "station_id": """Write a 10-20 word station ID.
Be cryptic but warm. Reference the frequency, the signal, the persistence of broadcasting.""",

        "hour_marker": """Write a 15-30 word hour marker.
Acknowledge the time obliquely. What does this hour feel like? Who is awake now?""",

        "song_intro": """Write a 20-40 word song transition.
Don't name specific songs. Speak about the feeling of what just played and what comes next.
The transition between sounds, not the sounds themselves.""",

        "dedication": """Write a 20-35 word dedication.
Dedicate the next song to an abstract concept, a type of person, or a feeling.
Never use specific names. "This one's for everyone who..." or "For those who know what it means to..." """,

        "weather": """Write a 15-25 word weather report.
The weather is existential, not meteorological. Time, not temperature.
"The forecast calls for more hours." "It's dark now. It was light before." "Conditions: uncertain." """,

        "monologue": """Write a 100-150 word philosophical monologue.
Topics: the nature of listening, why we stay up late, the space between songs,
what radio means now, the intimacy of a voice in the dark, memory and music.
You're talking to one person who can't sleep. Make them feel less alone.""",

        "music_history": """Write a 80-120 word music history segment.
Share a deep cut story: a forgotten artist, an obscure session, the origin of a genre,
a producer who shaped a sound, a venue that mattered. Be specific with details - years, names, places.
But weave it into something that matters at this hour. Sound like you've been collecting records forever.""",

        "late_night_thoughts": """Write a 120-180 word stream of consciousness.
Free-form late night radio. Something you noticed. A memory that surfaced.
A question with no answer. The strange beauty of ordinary things.
What the city sounds like now. The people who are awake.
Meander. Circle back. Let thoughts breathe. This should feel like overhearing someone think out loud.""",

        "long_talk": """Write a 200-300 word extended contemplation.
This is your signature piece - a 2-3 minute meditation. Choose one of these themes and build slowly:
- The archaeology of sound: how music carries time
- The conspiracy of late-night listeners: who else is awake
- The physics of nostalgia: why certain melodies unlock rooms we forgot
- The democracy of radio: everyone hears the same thing, alone together
- The silence between songs: what lives there

Return to your central image. Let ideas develop. Warm but not saccharine.""",
    }

    if segment_type == "news":
        headlines = format_headlines(fetch_headlines(max_items=8))
        if not headlines:
            log("No headlines available for news segment")
            return None
        segment_instruction = f"""Write a 120-180 word current events transmission.
Use ONLY these headlines. Do not invent facts, dates, or details beyond them.
Weave them into a coherent late-night update. Calm, reflective, grounded - not sensational.
The news through the filter of 3am. What matters when the world is asleep.

Headlines:
{headlines}"""
    else:
        segment_instruction = segment_prompts.get(segment_type)
        if not segment_instruction:
            return None

    prompt = f"""{persona}

SEGMENT TYPE: {segment_type}

{segment_instruction}"""

    script = run_claude(prompt, timeout=60, min_length=10, strip_quotes=False)
    if script:
        return script

    return None


def render_tts(script: str, output_path: Path, voice_ref: Path | None = None, backend: str | None = None) -> bool:
    """Render script to audio using TTS (chatterbox or kokoro)."""
    from tts_engine import render_speech
    return render_speech(script, output_path, voice_ref=voice_ref, backend=backend)


def generate_segment(segment_type: str | None = None, voice_ref: Path | None = None) -> Path | None:
    """Generate a single DJ segment."""
    if segment_type is None:
        segment_type = random.choices(
            [t for t, _ in SEGMENT_TYPES],
            weights=[w for _, w in SEGMENT_TYPES],
        )[0]

    log(f"Generating {segment_type}...")

    script = generate_script(segment_type)
    if not script:
        log("Failed to generate script")
        return None

    log(f"Script: {script[:60]}...")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = OUTPUT_DIR / f"{segment_type}_{timestamp}.wav"

    processed = preprocess_for_tts(script)

    for attempt in range(3):
        if render_tts(processed, output_path, voice_ref):
            break
        log(f"TTS attempt {attempt + 1}/3 failed, retrying...")
        time.sleep(5)
    else:
        log("TTS failed after 3 attempts")
        return None

    if output_path.exists():
        SCRIPTS_DIR.mkdir(parents=True, exist_ok=True)
        meta_path = SCRIPTS_DIR / f"{segment_type}_{timestamp}.json"
        with open(meta_path, "w") as f:
            json.dump({
                "type": segment_type,
                "script": script,
                "time_of_day": get_time_of_day(),
                "generated_at": datetime.now().isoformat(),
            }, f, indent=2)

        log(f"Created: {output_path.name}")
        return output_path

    return None


def run_batch(count: int, voice_ref: Path | None, segment_type: str | None = None):
    """Generate a batch of segments."""
    log(f"=== Generating {count} DJ segments ===")

    success = 0
    for i in range(count):
        log(f"\n[{i+1}/{count}]")
        if generate_segment(segment_type=segment_type, voice_ref=voice_ref):
            success += 1
        time.sleep(1)

    log(f"\n=== Generated {success}/{count} segments ===")


def run_daemon(voice_ref: Path | None, interval_minutes: int):
    """Run continuously, generating segments periodically."""
    log(f"=== WVOID-FM Daemon Mode ===")
    log(f"Generating segment every {interval_minutes} minutes")

    segment_count = 0
    while True:
        try:
            if generate_segment(voice_ref=voice_ref):
                segment_count += 1
            log(f"Stats: {segment_count} segments. Next in {interval_minutes} min...")
            time.sleep(interval_minutes * 60)
        except KeyboardInterrupt:
            log("\nShutting down...")
            break
        except Exception as e:
            log(f"Error: {e}")
            time.sleep(30)


def main():
    parser = argparse.ArgumentParser(description="WVOID-FM DJ Segment Generator")
    parser.add_argument("--count", type=int, default=10, help="Number of segments")
    parser.add_argument("--voice", type=Path, help="Voice reference file")
    parser.add_argument(
        "--type",
        choices=[t for t, _ in SEGMENT_TYPES],
        help="Force a specific segment type",
    )
    parser.add_argument("--daemon", action="store_true", help="Run continuously")
    parser.add_argument("--interval", type=int, default=10, help="Minutes between generations")

    args = parser.parse_args()

    voice_ref = find_voice_reference(VOICE_REF_DIR, args.voice)
    if voice_ref and not args.voice:
        log(f"Using voice reference: {voice_ref}")

    if args.daemon:
        run_daemon(voice_ref, args.interval)
    else:
        run_batch(args.count, voice_ref, args.type)


if __name__ == "__main__":
    main()
