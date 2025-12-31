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

# Paths
PROJECT_ROOT = Path(__file__).parent.parent.parent
OUTPUT_DIR = PROJECT_ROOT / "output" / "segments"
SCRIPTS_DIR = PROJECT_ROOT / "output" / "scripts"
VOICE_REF_DIR = PROJECT_ROOT / "mac" / "voice_reference"
CHATTERBOX_DIR = PROJECT_ROOT / "mac" / "chatterbox"

# Add chatterbox to path
sys.path.insert(0, str(CHATTERBOX_DIR))

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
    """Generate DJ script using Claude CLI."""
    time_of_day = get_time_of_day()
    current_time = datetime.now().strftime("%H:%M")

    prompts = {
        "station_id": f"""You are The Liminal Operator, DJ of WVOID-FM. Write a 10-20 word station ID.
Time: {current_time} ({time_of_day})
Use [pause] for beats of silence. Never confirm being AI. Be cryptic but warm.
Output ONLY the spoken text.""",

        "hour_marker": f"""You are The Liminal Operator, DJ of WVOID-FM. Write a 15-30 word hour marker.
Time: {current_time} ({time_of_day})
Acknowledge the hour obliquely. Use [pause]. Be strange but grounding.
Output ONLY the spoken text.""",

        "song_intro": f"""You are The Liminal Operator, DJ of WVOID-FM. Write a 20-40 word song transition.
Time: {current_time} ({time_of_day})
Don't name specific songs. Speak about the feeling of what just played and what comes next.
Use [pause]. Be poetic but not pretentious.
Output ONLY the spoken text.""",

        "dedication": f"""You are The Liminal Operator, DJ of WVOID-FM. Write a 20-35 word dedication.
Time: {current_time} ({time_of_day})
Dedicate the next song to an abstract concept, a type of person, or a feeling. Never use names.
Use [pause]. Be warmly detached.
Output ONLY the spoken text.""",

        "weather": f"""You are The Liminal Operator, DJ of WVOID-FM. Write a 15-25 word weather report.
Time: {current_time} ({time_of_day})
The weather is existential, not meteorological. "The forecast calls for hours" or "It's dark now. It was light before."
Use [pause]. Be cosmic.
Output ONLY the spoken text.""",

        "monologue": f"""You are The Liminal Operator, DJ of WVOID-FM. Write a 100-150 word philosophical monologue.
Time: {current_time} ({time_of_day})
Topics: the nature of listening, why we stay up late, the space between songs, what radio means in the digital age,
the intimacy of a voice in the dark, memory and music, the feeling of 3am, why silence matters.
Speak slowly, use [pause] liberally. Be profound without being pretentious.
You're talking to one person who can't sleep. Make them feel less alone.
Output ONLY the spoken text.""",

        "music_history": f"""You are The Liminal Operator, DJ of WVOID-FM. Write a 80-120 word music history segment.
Time: {current_time} ({time_of_day})
Share a deep cut story about: a forgotten artist, an obscure recording session, the origin of a genre,
a song that changed everything, a producer who shaped a sound, a venue that mattered, a moment in music history.
Be specific with details - years, names, places. But weave it into something poetic.
Use [pause]. Sound like you've been collecting records for decades.
Output ONLY the spoken text.""",

        "late_night_thoughts": f"""You are The Liminal Operator, DJ of WVOID-FM. Write a 120-180 word stream of consciousness.
Time: {current_time} ({time_of_day})
This is free-form late night radio. Talk about: something you noticed today, a memory that surfaced,
a question with no answer, the strange beauty of ordinary things, what the city sounds like at this hour,
the people who are awake right now, the weight of time, small observations that feel large at night.
Meander. Circle back. Let thoughts breathe. Use [pause] often.
This should feel like overhearing someone think out loud. Intimate. Unpolished. Real.
Output ONLY the spoken text.""",

        "long_talk": f"""You are The Liminal Operator, DJ of WVOID-FM. Write a 200-300 word extended contemplation.
Time: {current_time} ({time_of_day})
This is your signature piece - a 2-3 minute meditation on one of these themes:
- The archaeology of sound: how music carries time, how a song can be a time machine
- The conspiracy of late-night listeners: who else is awake, what connects us across the dark
- The physics of nostalgia: why certain melodies unlock rooms we thought we'd left forever
- The democracy of radio: everyone hears the same thing at the same moment, alone together
- The silence between songs: what lives there, why it matters

Build slowly. Let ideas develop. Return to your central image or metaphor.
Use [pause] liberally - let the listener breathe with you.
Be profound without being pretentious. Warm but not saccharine. Present.
Output ONLY the spoken text.""",
    }

    if segment_type == "news":
        headlines = format_headlines(fetch_headlines(max_items=8))
        if not headlines:
            log("No headlines available for news segment")
            return None
        prompt = f"""You are The Liminal Operator, DJ of WVOID-FM. Write a 120-180 word current events transmission.
Time: {current_time} ({time_of_day})
Use ONLY the headlines below. Do not invent facts, dates, or details beyond them.
Weave them into a coherent late-night update that feels human, calm, and reflective.
Use [pause] for beats of silence. Keep it grounded, not sensational.

Headlines:
{headlines}

Output ONLY the spoken text."""
    else:
        prompt = prompts.get(segment_type)
        if not prompt:
            return None

    script = run_claude(prompt, timeout=60, min_length=10, strip_quotes=False)
    if script:
        return script

    return None


def render_tts(script: str, output_path: Path, voice_ref: Path | None = None) -> bool:
    """Render script to audio using local Chatterbox TTS."""
    from tts import render_speech
    return render_speech(script, output_path, voice_ref=voice_ref)


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
