#!/usr/bin/env python3
"""
WVOID-FM Scheduled Content Batch Generator

Generates content for all time periods using Gemini CLI for scripts and Kokoro TTS.
Uses the weekly schedule to determine which show's voice and content style to use.

Usage:
    uv run python batch_schedule_generator.py              # Generate for all periods
    uv run python batch_schedule_generator.py --period morning --count 5
    uv run python batch_schedule_generator.py --show jazz_archives --count 10
"""

from __future__ import annotations

import argparse
import json
import os
import random
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from helpers import log, preprocess_for_tts
from persona import (
    OPERATOR_IDENTITY,
    OPERATOR_VOICE,
    OPERATOR_ANTI_PATTERNS,
    TIME_PERIOD_MOODS,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCHEDULE_PATH = PROJECT_ROOT / "config" / "schedule.yaml"
OUTPUT_DIR = PROJECT_ROOT / "output" / "segments"
SCRIPTS_DIR = PROJECT_ROOT / "output" / "scripts"

# Add schedule module to path
sys.path.insert(0, str(PROJECT_ROOT / "mac"))
from schedule import load_schedule, StationSchedule, Show

# Kokoro voice mapping - different voices for different shows
SHOW_VOICES = {
    "overnight_drift": "am_michael",  # Warm baritone for late night
    "sunrise_drift": "am_michael",
    "midday_mosaic": "am_adam",
    "talk_hour": "am_michael",
    "peak_signal": "am_adam",
    "golden_hour": "af_heart",  # Warm female for sunset
    "night_transmission": "am_onyx",  # Deep voice for night
    "jazz_archives": "bm_daniel",  # British male for jazz curation
    "world_circuit": "af_heart",
    "electric_drift": "am_fenrir",  # Deep for electronic
    "memory_lane": "bm_daniel",
    "club_liminal": "am_fenrir",
    "saturday_soul_service": "af_heart",
    "slow_sunday": "bf_emma",  # British female for gentle Sunday
    "listener_mailbag": "am_michael",
}

# Segment types with weights per time period
PERIOD_SEGMENTS = {
    "late_night": [
        ("monologue", 25),
        ("late_night_thoughts", 25),
        ("long_talk", 20),
        ("station_id", 10),
        ("dedication", 10),
        ("hour_marker", 10),
    ],
    "morning": [
        ("station_id", 20),
        ("hour_marker", 15),
        ("song_intro", 20),
        ("music_history", 20),
        ("weather", 15),
        ("dedication", 10),
    ],
    "afternoon": [
        ("song_intro", 25),
        ("music_history", 25),
        ("dedication", 15),
        ("station_id", 15),
        ("hour_marker", 10),
        ("long_talk", 10),
    ],
    "evening": [
        ("dedication", 20),
        ("hour_marker", 15),
        ("late_night_thoughts", 20),
        ("music_history", 15),
        ("station_id", 15),
        ("long_talk", 15),
    ],
}

# Segment prompts for Gemini
SEGMENT_PROMPTS = {
    "station_id": """Write a 10-20 word station ID for WVOID-FM.
Be cryptic but warm. Reference the frequency, the signal, the persistence of broadcasting.
Output ONLY the spoken text. No quotes, headers, or explanations.""",

    "hour_marker": """Write a 15-30 word hour marker.
Acknowledge the time obliquely. What does this hour feel like? Who is awake now?
Output ONLY the spoken text.""",

    "song_intro": """Write a 20-40 word song transition.
Don't name specific songs. Speak about the feeling of what just played and what comes next.
The transition between sounds, not the sounds themselves.
Output ONLY the spoken text.""",

    "dedication": """Write a 20-35 word dedication.
Dedicate the next song to an abstract concept, a type of person, or a feeling.
Never use specific names. "This one's for everyone who..." or "For those who know..."
Output ONLY the spoken text.""",

    "weather": """Write a 15-25 word weather report.
The weather is existential, not meteorological. Time, not temperature.
"The forecast calls for more hours." "It's dark now. It was light before."
Output ONLY the spoken text.""",

    "monologue": """Write a 100-150 word philosophical monologue.
Topics: the nature of listening, why we stay up late, the space between songs,
what radio means now, the intimacy of a voice in the dark, memory and music.
You're talking to one person who can't sleep. Make them feel less alone.
Output ONLY the spoken text.""",

    "music_history": """Write an 80-120 word music history segment.
Share a deep cut story: a forgotten artist, an obscure session, the origin of a genre,
a producer who shaped a sound, a venue that mattered. Be specific with details.
But weave it into something that matters at this hour.
Output ONLY the spoken text.""",

    "late_night_thoughts": """Write a 120-180 word stream of consciousness.
Free-form late night radio. Something you noticed. A memory that surfaced.
A question with no answer. The strange beauty of ordinary things.
What the city sounds like now. The people who are awake.
Meander. Circle back. Let thoughts breathe.
Output ONLY the spoken text.""",

    "long_talk": """Write a 200-300 word extended contemplation.
This is your signature piece - a 2-3 minute meditation. Choose one theme:
- The archaeology of sound: how music carries time
- The conspiracy of late-night listeners: who else is awake
- The physics of nostalgia: why certain melodies unlock rooms we forgot
- The democracy of radio: everyone hears the same thing, alone together
- The silence between songs: what lives there
Return to your central image. Let ideas develop.
Output ONLY the spoken text.""",
}


def build_gemini_prompt(segment_type: str, show: Show | None, period: str) -> str:
    """Build a prompt for Gemini with show context."""
    period_info = TIME_PERIOD_MOODS.get(period, TIME_PERIOD_MOODS.get("night", {}))

    show_context = ""
    if show:
        show_context = f"""
CURRENT SHOW: {show.name}
Show Description: {show.description}
"""

    persona = f"""You are The Liminal Operator, the voice of WVOID-FM.

{OPERATOR_IDENTITY.strip()}

{OPERATOR_VOICE.strip()}

{OPERATOR_ANTI_PATTERNS.strip()}
{show_context}
CURRENT STATE:
Time Period: {period}
Mood: {period_info.get('mood', 'Contemplative')}
Your state: {period_info.get('operator_state', 'Present')}

TECHNICAL:
- Use [pause] for beats of silence
- Use [chuckle] sparingly for dry amusement
"""

    segment_instruction = SEGMENT_PROMPTS.get(segment_type, SEGMENT_PROMPTS["station_id"])

    return f"{persona}\n\nSEGMENT TYPE: {segment_type}\n\n{segment_instruction}"


def run_gemini(prompt: str, timeout: int = 60) -> str | None:
    """Run Gemini CLI to generate script."""
    try:
        result = subprocess.run(
            ["gemini", "-p", prompt],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if result.returncode == 0 and result.stdout.strip():
            # Clean output
            text = result.stdout.strip()
            # Remove markdown formatting
            text = text.replace("*", "").replace("_", "")
            # Remove quotes if wrapped
            if text.startswith('"') and text.endswith('"'):
                text = text[1:-1].strip()
            return text
    except subprocess.TimeoutExpired:
        log("Gemini timed out")
    except FileNotFoundError:
        log("Gemini CLI not found")
    except Exception as e:
        log(f"Gemini error: {e}")
    return None


def render_kokoro(text: str, output_path: Path, voice: str = "am_michael") -> bool:
    """Render text to speech using Kokoro TTS."""
    kokoro_dir = PROJECT_ROOT / "mac" / "kokoro"
    venv_python = kokoro_dir / ".venv" / "bin" / "python"

    if not venv_python.exists():
        log("Kokoro venv not found, run setup first")
        return False

    escaped_text = text.replace('\\', '\\\\').replace('"', '\\"').replace('\n', ' ')

    tts_script = f'''
import os
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"
import warnings
warnings.filterwarnings("ignore")

from kokoro import KPipeline
import soundfile as sf
import numpy as np

pipe = KPipeline(lang_code="a", repo_id="hexgrad/Kokoro-82M")

text = "{escaped_text}"
voice = "{voice}"

generator = pipe(text, voice=voice, speed=1.0)
audio_segments = []
for _, _, audio in generator:
    audio_segments.append(audio)

if len(audio_segments) == 1:
    full_audio = audio_segments[0]
else:
    full_audio = np.concatenate(audio_segments)

sf.write("{output_path}", full_audio, 24000)
print("SUCCESS")
'''

    try:
        env = {**os.environ, "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1"}
        result = subprocess.run(
            [str(venv_python), "-c", tts_script],
            capture_output=True,
            text=True,
            timeout=300,
            cwd=str(kokoro_dir),
            env=env,
        )
        return "SUCCESS" in result.stdout
    except Exception as e:
        log(f"Kokoro error: {e}")
        return False


def generate_segment(
    segment_type: str,
    show: Show | None,
    period: str,
    voice: str,
) -> Path | None:
    """Generate a single segment."""
    log(f"Generating {segment_type} for {period} with voice {voice}...")

    prompt = build_gemini_prompt(segment_type, show, period)
    script = run_gemini(prompt)

    if not script:
        log("Failed to generate script")
        return None

    log(f"Script: {script[:60]}...")

    # Create output directory for this period
    period_dir = OUTPUT_DIR / period
    period_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = period_dir / f"{segment_type}_{timestamp}.wav"

    processed = preprocess_for_tts(script)

    for attempt in range(3):
        if render_kokoro(processed, output_path, voice):
            break
        log(f"TTS attempt {attempt + 1}/3 failed, retrying...")
        time.sleep(2)
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
                "period": period,
                "show": show.show_id if show else None,
                "voice": voice,
                "generated_at": datetime.now().isoformat(),
            }, f, indent=2)

        log(f"Created: {output_path.name}")
        return output_path

    return None


def generate_for_period(
    period: str,
    schedule: StationSchedule,
    count: int = 5,
) -> int:
    """Generate segments for a specific time period."""
    log(f"\n=== Generating {count} segments for {period} ===")

    segments = PERIOD_SEGMENTS.get(period, PERIOD_SEGMENTS["evening"])
    types = [t for t, _ in segments]
    weights = [w for _, w in segments]

    # Get a representative show for this period (just for context)
    # Map period to approximate hour
    period_hours = {
        "late_night": 2,
        "morning": 8,
        "afternoon": 15,
        "evening": 20,
    }

    from datetime import datetime as dt
    # Create a fake datetime for the period
    hour = period_hours.get(period, 12)
    fake_now = dt.now().replace(hour=hour, minute=0)

    try:
        resolved = schedule.resolve(fake_now)
        show = schedule.shows.get(resolved.show_id)
        voice = resolved.voices.get("host", "am_michael")
    except Exception:
        show = None
        voice = "am_michael"

    success = 0
    for i in range(count):
        segment_type = random.choices(types, weights=weights)[0]
        log(f"\n[{i+1}/{count}] {segment_type}")

        if generate_segment(segment_type, show, period, voice):
            success += 1

        time.sleep(1)  # Brief pause between generations

    return success


def generate_for_show(
    show_id: str,
    schedule: StationSchedule,
    count: int = 5,
) -> int:
    """Generate segments for a specific show."""
    if show_id not in schedule.shows:
        log(f"Unknown show: {show_id}")
        return 0

    show = schedule.shows[show_id]
    voice = SHOW_VOICES.get(show_id, show.voices.get("host", "am_michael"))

    log(f"\n=== Generating {count} segments for {show.name} ===")
    log(f"Voice: {voice}")

    # Determine period based on show characteristics
    energy_low, energy_high = show.music.get("energy_range", [0.3, 0.6])
    avg_energy = (energy_low + energy_high) / 2

    if avg_energy < 0.4:
        period = "late_night"
    elif avg_energy < 0.5:
        period = "morning"
    elif avg_energy < 0.7:
        period = "afternoon"
    else:
        period = "evening"

    segments = PERIOD_SEGMENTS.get(period, PERIOD_SEGMENTS["evening"])
    types = [t for t, _ in segments]
    weights = [w for _, w in segments]

    success = 0
    for i in range(count):
        segment_type = random.choices(types, weights=weights)[0]
        log(f"\n[{i+1}/{count}] {segment_type}")

        if generate_segment(segment_type, show, period, voice):
            success += 1

        time.sleep(1)

    return success


def generate_all(schedule: StationSchedule, count_per_period: int = 5) -> dict:
    """Generate content for all time periods."""
    log("=== WVOID-FM Full Schedule Content Generation ===")
    log(f"Generating {count_per_period} segments per period")

    results = {}
    for period in ["late_night", "morning", "afternoon", "evening"]:
        results[period] = generate_for_period(period, schedule, count_per_period)
        time.sleep(2)  # Pause between periods

    log("\n=== Generation Complete ===")
    for period, count in results.items():
        log(f"{period}: {count}/{count_per_period} segments")

    return results


def main():
    parser = argparse.ArgumentParser(description="WVOID-FM Scheduled Content Generator")
    parser.add_argument("--period", choices=["late_night", "morning", "afternoon", "evening"])
    parser.add_argument("--show", help="Show ID to generate for")
    parser.add_argument("--count", type=int, default=5, help="Segments per period/show")
    parser.add_argument("--all", action="store_true", help="Generate for all periods")

    args = parser.parse_args()

    # Load schedule
    try:
        schedule = load_schedule(SCHEDULE_PATH)
        log(f"Loaded schedule with {len(schedule.shows)} shows")
    except Exception as e:
        log(f"Failed to load schedule: {e}")
        return 1

    if args.show:
        generate_for_show(args.show, schedule, args.count)
    elif args.period:
        generate_for_period(args.period, schedule, args.count)
    else:
        generate_all(schedule, args.count)

    return 0


if __name__ == "__main__":
    sys.exit(main())
