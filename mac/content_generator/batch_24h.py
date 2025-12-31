#!/usr/bin/env python3
"""
Generate 24 hours of radio content using Kokoro TTS.

Content mix:
- Short segments (30s-2min): station IDs, hour markers, dedications, weather
- Medium segments (2-5min): monologues, music history, news
- Long podcasts (5-15min): deep dives, philosophy, essays

Target: 24 hours = 86400 seconds
"""

import os
import random
import time
from datetime import datetime
from pathlib import Path

# Force Kokoro backend
os.environ["WVOID_TTS_BACKEND"] = "kokoro"

from helpers import log, get_time_of_day, preprocess_for_tts, run_claude
from tts_engine import render_speech
from persona import OPERATOR_IDENTITY, OPERATOR_VOICE, get_operator_context

PROJECT_ROOT = Path(__file__).parent.parent.parent
OUTPUT_DIR = PROJECT_ROOT / "output" / "segments"
PODCASTS_DIR = PROJECT_ROOT / "output" / "podcasts"

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
PODCASTS_DIR.mkdir(parents=True, exist_ok=True)

# Target durations in seconds
TARGET_TOTAL = 24 * 60 * 60  # 24 hours

# Content types with target durations
SHORT_TYPES = {
    "station_id": (15, 30),
    "hour_marker": (20, 45),
    "dedication": (30, 60),
    "weather": (30, 60),
    "song_intro": (15, 30),
}

MEDIUM_TYPES = {
    "monologue": (120, 240),
    "music_history": (180, 300),
    "news": (120, 240),
    "late_night_thoughts": (150, 270),
}

LONG_TYPES = {
    "podcast": (300, 900),  # 5-15 minutes
}

# Prompts for each type
PROMPTS = {
    "station_id": """Write a 15-30 word station ID for WVOID-FM.
Be creative - reference the frequency between frequencies, the liminal hours,
the space where radio waves meet dreams. Brief but evocative.""",

    "hour_marker": """Write a 30-50 word hour marker announcing the time.
Current time: {time}. Make it poetic - connect the hour to mood, to the listeners
still awake, to the quality of darkness at this moment.""",

    "dedication": """Write a 50-80 word dedication segment.
Dedicate a song to night workers, insomniacs, the heartbroken, lonely drivers,
or anyone listening in the dark. Be specific but universal.""",

    "weather": """Write a 50-80 word atmospheric weather report.
Don't just give temperatures - describe how the air feels, what the sky looks like,
what kind of night it is for wandering or staying in.""",

    "song_intro": """Write a 20-40 word song introduction.
Don't name a specific song. Instead, set a mood - describe what kind of song
is coming, what feeling it carries, who it's for.""",

    "monologue": """Write a 150-250 word philosophical monologue.
Topics: the nature of listening, why we stay up late, the intimacy of radio,
memory and music, what it means to be the only one awake.
You're talking to one person in the dark.""",

    "music_history": """Write a 200-300 word segment about music history.
Pick an obscure but fascinating moment: a forgotten genre, a pivotal recording session,
a musician who changed everything and was forgotten, the birth of a sound.
Make history feel alive and present.""",

    "news": """Write a 150-250 word "news from elsewhere" segment.
Not real news - atmospheric updates from the edges of perception.
Strange occurrences, liminal events, things happening in the frequency between frequencies.
Deadpan delivery of impossible reports.""",

    "late_night_thoughts": """Write a 180-280 word late night reflection.
Topics: the quality of 3am silence, why certain songs only work at night,
the democracy of insomnia, conversations with yourself, the radio as companion.
Intimate and slightly melancholic.""",

    "podcast": """Write a {minutes}-minute podcast monologue (~{words} words).
Topic: {topic}
Go deep. This is long-form exploration of an idea. Weave in personal observation,
historical context, philosophical tangent. Let the thought breathe and develop.
This is radio for people who want to think alongside you.""",
}

PODCAST_TOPICS = [
    "The archaeology of sound - how we excavate meaning from old recordings",
    "Why certain songs become time machines",
    "The intimacy of the voice in your ear",
    "Radio as the original parasocial relationship",
    "The geometry of loneliness and how music maps it",
    "What happens to songs we forget",
    "The night shift: a meditation on working while others sleep",
    "Why we listen to sad songs when we're sad",
    "The album as journey vs the playlist as mood",
    "Silence as music's necessary shadow",
    "The democratization of melancholy through radio",
    "How cities sound different at 3am",
    "The last record store and what we lose",
    "Teaching someone to love music",
    "The songs that saved your life",
    "Why we remember where we first heard certain songs",
    "The philosophy of the B-side",
    "Voices in the dark: the history of late night radio",
    "What vinyl actually sounds like vs what we think it sounds like",
    "The end of monoculture and the loneliness of infinite choice",
]


def generate_segment(seg_type: str, duration_range: tuple[int, int]) -> tuple[Path, float] | None:
    """Generate a single segment. Returns (path, duration) or None."""
    min_dur, max_dur = duration_range
    target_words = random.randint(min_dur, max_dur) * 2  # ~2 words/sec for natural speech

    ctx = get_operator_context()

    prompt_template = PROMPTS.get(seg_type, PROMPTS["monologue"])

    if seg_type == "hour_marker":
        prompt = prompt_template.format(time=datetime.now().strftime("%I:%M %p"))
    elif seg_type == "podcast":
        minutes = random.randint(5, 15)
        words = minutes * 130
        topic = random.choice(PODCAST_TOPICS)
        prompt = prompt_template.format(minutes=minutes, words=words, topic=topic)
        target_words = words
    else:
        prompt = prompt_template

    full_prompt = f"""{OPERATOR_IDENTITY.strip()}

{OPERATOR_VOICE.strip()}

Context: {ctx['time_of_day']}, listener count unknown.

{prompt}

Write only the script, no stage directions except [pause] for beats of silence.
Aim for approximately {target_words} words."""

    script = run_claude(full_prompt, timeout=120, strip_quotes=True)
    if not script:
        return None

    processed = preprocess_for_tts(script)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    if seg_type == "podcast":
        output_path = PODCASTS_DIR / f"podcast_{timestamp}.wav"
    else:
        output_path = OUTPUT_DIR / f"{seg_type}_{timestamp}.wav"

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
        duration = target_words / 2  # Estimate

    return output_path, duration


def main():
    log("=== 24-Hour Content Generator ===")
    log(f"Target: {TARGET_TOTAL / 3600:.1f} hours")

    total_duration = 0
    segments_created = 0

    # Distribution: 30% short, 40% medium, 30% long
    short_target = TARGET_TOTAL * 0.30
    medium_target = TARGET_TOTAL * 0.40
    long_target = TARGET_TOTAL * 0.30

    short_duration = 0
    medium_duration = 0
    long_duration = 0

    while total_duration < TARGET_TOTAL:
        # Choose category based on what's needed
        if short_duration < short_target and (medium_duration >= medium_target or random.random() < 0.3):
            seg_type = random.choice(list(SHORT_TYPES.keys()))
            duration_range = SHORT_TYPES[seg_type]
            category = "short"
        elif medium_duration < medium_target and (long_duration >= long_target or random.random() < 0.6):
            seg_type = random.choice(list(MEDIUM_TYPES.keys()))
            duration_range = MEDIUM_TYPES[seg_type]
            category = "medium"
        else:
            seg_type = "podcast"
            duration_range = LONG_TYPES[seg_type]
            category = "long"

        log(f"\n[{segments_created + 1}] Generating {seg_type} ({category})...")
        log(f"  Progress: {total_duration / 3600:.2f}h / {TARGET_TOTAL / 3600:.1f}h ({100 * total_duration / TARGET_TOTAL:.1f}%)")

        result = generate_segment(seg_type, duration_range)

        if result:
            path, duration = result
            total_duration += duration
            segments_created += 1

            if category == "short":
                short_duration += duration
            elif category == "medium":
                medium_duration += duration
            else:
                long_duration += duration

            log(f"  Created: {path.name} ({duration:.1f}s)")
            log(f"  Total: {total_duration / 3600:.2f}h")
        else:
            log(f"  Failed to generate {seg_type}, retrying...")
            time.sleep(2)
            continue

        # Brief pause between generations
        time.sleep(1)

    log(f"\n=== Complete ===")
    log(f"Total segments: {segments_created}")
    log(f"Total duration: {total_duration / 3600:.2f} hours")
    log(f"  Short: {short_duration / 3600:.2f}h")
    log(f"  Medium: {medium_duration / 3600:.2f}h")
    log(f"  Long: {long_duration / 3600:.2f}h")


if __name__ == "__main__":
    main()
