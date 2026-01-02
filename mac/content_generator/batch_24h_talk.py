#!/usr/bin/env python3
"""
Generate 24 hours of talk-only radio content using Kokoro TTS.
Simulates a full day starting at 6pm, with time-appropriate content.

Each segment is tagged with its intended broadcast time.
"""

import os
import random
import time
from datetime import datetime, timedelta
from pathlib import Path

# Force Kokoro backend
os.environ["WVOID_TTS_BACKEND"] = "kokoro"

from helpers import log, preprocess_for_tts, run_claude
from tts_engine import render_speech
from persona import OPERATOR_IDENTITY, OPERATOR_VOICE

PROJECT_ROOT = Path(__file__).parent.parent.parent
OUTPUT_DIR = PROJECT_ROOT / "output" / "segments"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# Start time: 6pm today
START_TIME = datetime.now().replace(hour=18, minute=0, second=0, microsecond=0)

# Target: 24 hours
TARGET_SECONDS = 24 * 60 * 60

# Time period definitions
TIME_PERIODS = {
    (0, 6): {"name": "late_night", "mood": "The deepest hours. Insomniacs, night workers, the lonely and the restless.", "energy": "low, contemplative, intimate", "topics": ["insomnia", "memory", "loneliness", "the quality of silence", "why we can't sleep"]},
    (6, 10): {"name": "early_morning", "mood": "Dawn breaking. Early risers, commuters, those who never slept.", "energy": "gentle, warming, hopeful", "topics": ["beginnings", "coffee rituals", "the promise of a new day", "morning light"]},
    (10, 14): {"name": "morning", "mood": "Day fully arrived. Work mode, focused energy.", "energy": "engaged, curious, productive", "topics": ["work", "creativity", "focus", "the rhythm of doing"]},
    (14, 18): {"name": "afternoon", "mood": "The long stretch. Afternoon lull, counting hours.", "energy": "steady, sometimes restless", "topics": ["waiting", "time passing", "afternoon light", "the mundane"]},
    (18, 21): {"name": "evening", "mood": "Day releasing. Transition time, homecoming.", "energy": "unwinding, reflective, social", "topics": ["endings", "coming home", "dinner conversations", "twilight"]},
    (21, 24): {"name": "night", "mood": "Night claiming the world. The in-between hours.", "energy": "contemplative, intimate, mysterious", "topics": ["night thoughts", "what the dark reveals", "solitude", "the radio as companion"]},
}

def get_time_period(hour: int) -> dict:
    """Get mood/context for a given hour."""
    for (start, end), period in TIME_PERIODS.items():
        if start <= hour < end:
            return period
    return TIME_PERIODS[(21, 24)]  # fallback to night

# Segment types with duration ranges (seconds) and weights by time period
SEGMENT_TYPES = {
    "station_id": {
        "duration": (15, 30),
        "prompt": """Write a 15-30 word station ID for WVOID-FM.
Time: {time}. Mood: {mood}.
Reference the frequency between frequencies, the liminal space of radio.""",
    },
    "hour_marker": {
        "duration": (30, 60),
        "prompt": """Write a 40-60 word hour marker.
Time: {time}. {mood}
Connect this specific hour to who's listening, what they might be doing,
the quality of this moment in the day's cycle.""",
    },
    "monologue": {
        "duration": (120, 300),
        "prompt": """Write a 150-300 word philosophical monologue.
Time: {time}. {mood}. Energy: {energy}.
Possible topics: {topics}
You're speaking to one person. Make them feel less alone.
Use [pause] for beats of silence.""",
    },
    "reflection": {
        "duration": (90, 180),
        "prompt": """Write a 100-180 word quiet reflection.
Time: {time}. {mood}.
Topic: {topic}
Brief, intimate, like a thought shared between friends at this hour.""",
    },
    "news_from_elsewhere": {
        "duration": (60, 120),
        "prompt": """Write a 70-130 word "news from elsewhere" segment.
Time: {time}.
Not real news - atmospheric updates from the edges of perception.
Strange occurrences, liminal events, impossible reports delivered deadpan.
Things happening in the frequency between frequencies.""",
    },
    "dedication": {
        "duration": (45, 90),
        "prompt": """Write a 50-90 word dedication.
Time: {time}. {mood}.
Dedicate to a type of listener appropriate for this hour - be specific about
who they are and what they might be doing right now.""",
    },
    "weather": {
        "duration": (45, 90),
        "prompt": """Write a 50-90 word atmospheric weather report.
Time: {time}.
Don't just give temperatures - describe how {time_period} air feels,
what the sky looks like at this hour, what kind of moment it is.""",
    },
    "long_talk": {
        "duration": (300, 600),
        "prompt": """Write a 350-650 word extended monologue.
Time: {time}. {mood}. Energy: {energy}.
Topic: {topic}
Go deeper. This is late-night radio philosophy. Weave personal observation,
memory, and meaning. Let the thought develop fully.
Use [pause] liberally for natural rhythm.""",
    },
}

# Weights for different times of day
TIME_WEIGHTS = {
    "late_night": {"long_talk": 4, "monologue": 3, "reflection": 2, "dedication": 2, "station_id": 1, "hour_marker": 1, "news_from_elsewhere": 2, "weather": 1},
    "early_morning": {"monologue": 3, "reflection": 3, "dedication": 2, "station_id": 2, "hour_marker": 2, "weather": 2, "long_talk": 1, "news_from_elsewhere": 1},
    "morning": {"monologue": 2, "reflection": 2, "station_id": 2, "hour_marker": 2, "dedication": 1, "weather": 1, "news_from_elsewhere": 1, "long_talk": 1},
    "afternoon": {"monologue": 2, "reflection": 2, "station_id": 2, "hour_marker": 2, "dedication": 1, "weather": 2, "news_from_elsewhere": 1, "long_talk": 1},
    "evening": {"monologue": 3, "reflection": 2, "dedication": 2, "station_id": 2, "hour_marker": 2, "weather": 2, "long_talk": 2, "news_from_elsewhere": 1},
    "night": {"long_talk": 3, "monologue": 3, "reflection": 2, "dedication": 2, "station_id": 1, "hour_marker": 2, "news_from_elsewhere": 2, "weather": 1},
}

REFLECTION_TOPICS = [
    "why certain songs only work at certain hours",
    "the sound of your city at this moment",
    "what you'd tell your younger self about nights like this",
    "the last conversation you had that mattered",
    "what home sounds like",
    "the song you've listened to most this year",
    "why we keep the radio on even when not listening",
    "the difference between alone and lonely",
    "what you're avoiding thinking about",
    "the person you hope is listening right now",
]

LONG_TOPICS = [
    "The archaeology of sound - how we excavate meaning from recordings",
    "Why certain songs become time machines",
    "The intimacy of a voice in your ear",
    "Radio as the original parasocial relationship",
    "The geometry of loneliness and how music maps it",
    "What happens to the songs we forget",
    "The democracy of insomnia",
    "Why we listen to sad songs when we're sad",
    "Silence as music's necessary shadow",
    "How cities sound different at 3am",
    "The philosophy of the B-side",
    "Voices in the dark: what radio means now",
    "The end of monoculture and the loneliness of infinite choice",
    "Why we remember where we first heard certain songs",
    "The last record store and what we lose when it closes",
]


def choose_segment_type(period: dict) -> str:
    """Choose a segment type based on time-of-day weights."""
    weights = TIME_WEIGHTS.get(period["name"], TIME_WEIGHTS["night"])
    types = list(weights.keys())
    probs = list(weights.values())
    return random.choices(types, weights=probs, k=1)[0]


def generate_segment(seg_type: str, broadcast_time: datetime) -> tuple[Path, float] | None:
    """Generate a segment for a specific broadcast time."""
    hour = broadcast_time.hour
    period = get_time_period(hour)

    config = SEGMENT_TYPES[seg_type]
    min_dur, max_dur = config["duration"]
    target_words = random.randint(min_dur, max_dur) * 2  # ~2 words/sec

    time_str = broadcast_time.strftime("%I:%M %p")

    # Build prompt
    prompt_template = config["prompt"]
    topic = random.choice(REFLECTION_TOPICS) if seg_type == "reflection" else random.choice(LONG_TOPICS)

    prompt = prompt_template.format(
        time=time_str,
        mood=period["mood"],
        energy=period["energy"],
        topics=", ".join(period["topics"]),
        topic=topic,
        time_period=period["name"],
    )

    # Build time-specific context for the Operator
    time_context = f"""
CRITICAL TIME CONTEXT:
This segment will broadcast at EXACTLY {time_str} ({period['name']} hours).
The listener is hearing this AT {time_str} - reference this specific time naturally.
DO NOT use generic phrases like "tonight" or "this hour" - be specific about {time_str}.
If it's an hour marker, announce that it IS {time_str} right now.
The content MUST feel appropriate for someone listening at {time_str}."""

    full_prompt = f"""{OPERATOR_IDENTITY.strip()}

{OPERATOR_VOICE.strip()}

{time_context}

{prompt}

Write only the script. Use [pause] for beats of silence.
Aim for approximately {target_words} words."""

    script = run_claude(full_prompt, timeout=180, strip_quotes=True)
    if not script:
        return None

    processed = preprocess_for_tts(script)

    # Filename includes broadcast time
    time_tag = broadcast_time.strftime("%Y%m%d_%H%M")
    timestamp = datetime.now().strftime("%S%f")[:4]
    output_path = OUTPUT_DIR / f"{seg_type}_{time_tag}_{timestamp}.wav"

    if not render_speech(processed, output_path):
        return None

    # Get actual duration
    try:
        import subprocess
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(output_path)],
            capture_output=True, text=True, timeout=10
        )
        duration = float(result.stdout.strip())
    except:
        duration = target_words / 2

    return output_path, duration


def main():
    log("=== 24-Hour Talk Content Generator ===")
    log(f"Start time: {START_TIME.strftime('%Y-%m-%d %I:%M %p')}")
    log(f"Target: 24 hours of content")

    current_time = START_TIME
    end_time = START_TIME + timedelta(hours=24)

    total_duration = 0
    segments_created = 0

    # Track last hour marker to ensure one per hour
    last_hour_marker = -1

    while current_time < end_time:
        period = get_time_period(current_time.hour)

        # Force hour marker at top of each hour
        if current_time.hour != last_hour_marker and current_time.minute < 30:
            seg_type = "hour_marker"
            last_hour_marker = current_time.hour
        else:
            seg_type = choose_segment_type(period)

        time_str = current_time.strftime("%I:%M %p")
        log(f"\n[{segments_created + 1}] {time_str} - Generating {seg_type} ({period['name']})...")
        log(f"  Progress: {total_duration / 3600:.2f}h / 24.0h ({100 * total_duration / TARGET_SECONDS:.1f}%)")

        result = generate_segment(seg_type, current_time)

        if result:
            path, duration = result
            total_duration += duration
            segments_created += 1

            # Advance broadcast time by segment duration
            current_time += timedelta(seconds=duration)

            log(f"  Created: {path.name} ({duration:.1f}s)")
            log(f"  Next slot: {current_time.strftime('%I:%M %p')}")
        else:
            log(f"  Failed, retrying...")
            time.sleep(2)
            continue

        time.sleep(0.5)

    log(f"\n=== Complete ===")
    log(f"Total segments: {segments_created}")
    log(f"Total duration: {total_duration / 3600:.2f} hours")
    log(f"Coverage: {START_TIME.strftime('%I:%M %p')} to {current_time.strftime('%I:%M %p')}")


if __name__ == "__main__":
    main()
