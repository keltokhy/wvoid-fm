#!/usr/bin/env python3
"""
WRIT-FM Talk Segment Generator

Generates long-form talk show content for the talk-first radio format.
Uses Claude CLI for scripts and Kokoro TTS for rendering.

Segment types:
  Long-form (primary content, 1500-3000 words):
    deep_dive       - Extended single-topic exploration
    news_analysis   - Current events through late-night lens (uses RSS headlines)
    interview       - Simulated interview with historical/fictional figure
    panel           - Two hosts discuss topic from different angles
    story           - Narrative storytelling, true stories from music/culture
    listener_mailbag - Invented listener letters + responses
    music_essay     - Extended essay on artist/album/genre

  Short-form (transitions):
    station_id      - 15-30 word station identification
    show_intro      - 80-150 word show opening
    show_outro      - 60-120 word show closing

Usage:
    uv run python talk_generator.py                                # Current show
    uv run python talk_generator.py --show midnight_signal --count 5
    uv run python talk_generator.py --type deep_dive --topic "why vinyl matters"
    uv run python talk_generator.py --all --count 3                # 3 per show
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

sys.path.insert(0, str(Path(__file__).parent))

from helpers import (
    log, preprocess_for_tts, fetch_headlines, format_headlines, run_claude,
    render_kokoro, render_single_voice, concatenate_audio, get_audio_duration,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCHEDULE_PATH = PROJECT_ROOT / "config" / "schedule.yaml"
OUTPUT_DIR = PROJECT_ROOT / "output" / "talk_segments"
SCRIPTS_DIR = PROJECT_ROOT / "output" / "scripts"

sys.path.insert(0, str(PROJECT_ROOT / "mac"))
from schedule import load_schedule, StationSchedule

sys.path.insert(0, str(Path(__file__).parent))
from persona import HOSTS, get_host, build_host_prompt, STATION_NAME

# =============================================================================
# SEGMENT TYPE DEFINITIONS
# =============================================================================

SEGMENT_WORD_TARGETS = {
    # Long-form
    "deep_dive": (1500, 2500),
    "news_analysis": (1500, 2000),
    "interview": (2000, 3000),
    "panel": (2000, 3000),
    "story": (1500, 2500),
    "listener_mailbag": (1500, 2000),
    "music_essay": (1500, 2500),
    # Short-form
    "station_id": (15, 30),
    "show_intro": (80, 150),
    "show_outro": (60, 120),
}

SEGMENT_PROMPTS = {
    "deep_dive": """Write an extended exploration of this topic. Go deep.
Build your central idea through stories, examples, tangents.
Let one thought lead naturally to another. Circle back to earlier threads.
Include specific details: years, names, places when relevant.
Structure: open with a hook, develop through 3-4 connected ideas, land somewhere unexpected.
Use [pause] for natural rhythm. Output ONLY the spoken words.""",

    "news_analysis": """Analyze these headlines through a late-night lens.
Don't just report - interpret. What patterns do you see? What's being missed?
Connect current events to deeper themes. Ask the questions daytime anchors don't.
Be thoughtful, not reactive. Skeptical but not cynical.

HEADLINES:
{headlines}

Use [pause] for natural rhythm. Output ONLY the spoken words.""",

    "interview": """Write a simulated interview where you (the host) talk with {guest_name}.
Format with HOST: and GUEST: markers on separate lines.
The guest is a fictional/composite character, not a real living person being impersonated.
The conversation should feel natural - interruptions, tangents, moments of surprise.
Build to genuine insight or revelation.
Use [pause] for natural rhythm. Output ONLY the spoken dialogue.""",

    "panel": """Write a discussion between two hosts on this topic.
Format with HOST_A: and HOST_B: markers on separate lines.
They have different perspectives but mutual respect.
The conversation should build - start with disagreement, find nuance, reach unexpected common ground.
Include moments of genuine surprise and humor.
Use [pause] for natural rhythm. Output ONLY the spoken dialogue.""",

    "story": """Tell a story. It can be true, apocryphal, or mythological - but tell it like it happened.
Good stories have specific details: the color of the room, the year, the weather.
Build tension. Let the listener wonder where this is going.
The ending should reframe everything that came before.
Use [pause] for dramatic effect. Output ONLY the spoken words.""",

    "listener_mailbag": """Write a segment responding to invented listener messages.
Create 2-3 messages from listeners (with first names and cities).
Each message should touch on something real - a memory, a question, a feeling.
Respond to each with genuine warmth and thoughtfulness.
Format: read the message, then respond. Natural transitions between letters.
Use [pause] for natural rhythm. Output ONLY the spoken words.""",

    "music_essay": """Write an extended essay about music.
This is not a review. It's a love letter, an excavation, a meditation.
Pick a specific angle: a single song, a studio, a year, a collaboration, a genre's birth.
Use vivid, sensory language. Make the listener hear what you're describing.
Be specific with details but universal with feeling.
Use [pause] for natural rhythm. Output ONLY the spoken words.""",

    "station_id": """Write a 15-30 word station ID for WRIT-FM.
Be cryptic but warm. Reference the frequency, the signal, the persistence of broadcasting.
Output ONLY the spoken text. No quotes, headers, or explanations.""",

    "show_intro": """Write an 80-150 word opening for the show.
Welcome listeners. Set the mood. Hint at what's ahead without being specific.
Ground the listener in time and space - what hour is it, what kind of night.
Output ONLY the spoken text.""",

    "show_outro": """Write a 60-120 word show closing.
Thank the listener for staying. Acknowledge the time spent together.
Hint at what's next on the station. Leave them with something to carry.
Output ONLY the spoken text.""",
}

# =============================================================================
# TOPIC POOLS
# =============================================================================

TOPIC_POOLS = {
    "philosophy": [
        "The 3am mind - why we think differently in darkness",
        "Alone together - the paradox of mass media intimacy",
        "The archaeology of memory - how songs excavate the past",
        "Waiting rooms of the soul - the liminal spaces we inhabit",
        "The democracy of insomnia - who else is awake right now",
        "Time as texture - why some hours feel longer than others",
        "The comfort of routine - rituals that hold us together",
        "Nostalgia as navigation - using the past to find the future",
        "The weight of small things - objects that carry meaning",
        "Silence as sound - what we hear when nothing plays",
        "The myth of productivity - what we lose when everything must be useful",
        "Boredom as portal - what happens when we stop filling every moment",
        "The loneliness of crowds versus the company of solitude",
        "Why we tell stories to strangers in the dark",
        "The philosophy of night shifts - what the invisible economy teaches us",
    ],
    "music_history": [
        "The secret history of the B-side - when the throwaway becomes the classic",
        "How geography shaped sound - the cities that invented genres",
        "The lost art of the album sequence - why track order matters",
        "Recording studios as instruments - rooms that shaped decades of music",
        "The sample and the sampled - how old records live in new ones",
        "One-hit wonders who deserved more - careers that should have been",
        "The technology of music - from wax cylinders to streaming algorithms",
        "Regional scenes that never crossed over - local sounds lost to time",
        "Pirate radio - outlaws of the airwaves and the sounds they set free",
        "The golden age of the record shop - archaeology for the ears",
        "How jazz escaped from New Orleans and conquered the world",
        "The birth of electronic music - when machines learned to feel",
        "Ethiopian jazz and the sound of a country's golden age",
        "The DJ as curator - the art of selection and sequence",
        "Vinyl mastering - the physics of grooves and the art of the cut",
    ],
    "current_events": [
        "What the headlines aren't telling you this week",
        "The economy of attention - who benefits when we're distracted",
        "Technology and trust - the crisis nobody's naming",
        "The changing shape of cities after midnight",
        "Climate reports and the language of urgency",
        "The state of journalism at the end of the world",
        "Immigration stories that don't fit the narrative",
        "The education system as a mirror of what we value",
        "Healthcare access and the geography of survival",
        "The gig economy and the myth of freedom",
    ],
    "culture": [
        "The coffee shop as third place - where strangers become regulars",
        "Night shift workers - the invisible economy that keeps everything running",
        "The last video stores - temples to a dying format",
        "Diners at 2am - confessionals with unlimited refills",
        "24-hour establishments - who keeps the lights on and why",
        "The changing meaning of downtown after dark",
        "Bookstores as sanctuaries - the quiet resistance of print",
        "The art of the mix tape - playlists as unsent letters",
        "Street food and the democracy of flavor",
        "Public transportation at night - the bus as equalizer",
    ],
    "soul_music": [
        "What makes a song 'soul' - it's not a genre, it's an approach",
        "The Muscle Shoals sound and the white musicians who played Black",
        "Motown's assembly line of heartbreak",
        "The gospel roots that feed every groove",
        "Curtis Mayfield and the politics of the bassline",
        "Neo-soul and the question of authenticity",
        "The art of the slow jam - why vulnerability needs a groove",
        "Funk as philosophy - Parliament and the mothership connection",
        "Erykah Badu and the church of vibe",
        "Disco's death and resurrection - who killed the dance floor and who brought it back",
    ],
    "night_philosophy": [
        "What the dark knows that the light doesn't",
        "Sleep as surrender - why we resist the thing we need most",
        "Dreams as the radio station of the subconscious",
        "The 4am confession - why truth comes easier in darkness",
        "Nocturnal animals and what they teach us about seeing differently",
        "The history of the night - how humans learned to occupy the dark",
        "Insomnia as unwanted clarity",
        "The night sky before light pollution - what we lost when we lit up the world",
        "Lullabies and the ancient technology of singing someone to sleep",
        "Why creativity peaks after midnight",
    ],
    "listeners": [
        "Letters from the frequency - your messages answered",
        "The songs that changed your lives - listener stories",
        "Questions from the dark - what you've always wanted to know",
        "Dedications and confessions from the inbox",
        "Where are you listening from? - the geography of our audience",
    ],
}

# Guest characters for interview segments
INTERVIEW_GUESTS = [
    {"name": "a retired record store owner from Detroit", "context": "Spent 40 years curating vinyl for a neighborhood"},
    {"name": "a sound engineer who worked on legendary sessions", "context": "Was in the room when history was made on tape"},
    {"name": "a radio historian", "context": "Studies the golden age of pirate and community radio"},
    {"name": "a jazz archivist from a university collection", "context": "Cataloging a century of forgotten recordings"},
    {"name": "a night shift nurse who listens to us every night", "context": "Knows the hospital's secret soundtrack"},
    {"name": "a former musician who chose to listen instead of play", "context": "Understanding music differently from the audience"},
    {"name": "a street food vendor who works the late shift", "context": "The city's midnight economy and its soundtrack"},
    {"name": "a librarian who specializes in sound recordings", "context": "Preserving voices that time is trying to erase"},
]


# =============================================================================
# CORE GENERATION
# =============================================================================


def select_topic(topic_focus: str, segment_type: str) -> str:
    """Pick a topic from the pool matching the show's focus."""
    pool = TOPIC_POOLS.get(topic_focus, [])
    if not pool:
        # Fall back to a combined pool
        all_topics = []
        for topics in TOPIC_POOLS.values():
            all_topics.extend(topics)
        pool = all_topics
    return random.choice(pool)


def build_generation_prompt(
    host_id: str,
    segment_type: str,
    topic: str,
    show_name: str,
    show_description: str,
    topic_focus: str,
    guest_voice: str | None = None,
) -> str:
    """Build the full prompt for content generation."""
    show_context = {
        "show_name": show_name,
        "show_description": show_description,
        "topic_focus": topic_focus,
        "segment_type": segment_type,
    }
    base = build_host_prompt(host_id, show_context)

    min_words, max_words = SEGMENT_WORD_TARGETS.get(segment_type, (1500, 2500))

    prompt_template = SEGMENT_PROMPTS.get(segment_type, SEGMENT_PROMPTS["deep_dive"])

    # Handle special template vars
    if segment_type == "news_analysis":
        headlines = fetch_headlines()
        headline_text = format_headlines(headlines) if headlines else "No headlines available - discuss the nature of news itself."
        prompt_template = prompt_template.format(headlines=headline_text)
    elif segment_type == "interview":
        guest = random.choice(INTERVIEW_GUESTS)
        prompt_template = prompt_template.format(guest_name=guest["name"])
        topic = f"{topic} (Guest context: {guest['context']})"
    elif segment_type == "panel":
        # Panel uses two hosts
        pass

    prompt = f"""{base}

SEGMENT: {segment_type}
TOPIC: {topic}
TARGET LENGTH: {min_words}-{max_words} words

{prompt_template}"""

    return prompt


def run_generation(prompt: str, segment_type: str) -> str | None:
    """Run Claude CLI to generate the script."""
    min_words, max_words = SEGMENT_WORD_TARGETS.get(segment_type, (1500, 2500))
    timeout = 120 if max_words < 200 else 300

    script = run_claude(prompt, timeout=timeout)
    if not script:
        return None

    # Quality gate: check word count
    word_count = len(script.split())
    min_acceptable = int(min_words * 0.8)
    if word_count < min_acceptable:
        log(f"Script too short: {word_count} words (need {min_acceptable}+)")
        return None

    return script


# =============================================================================
# TTS RENDERING (shared functions imported from helpers)
# =============================================================================


def render_multi_voice(script: str, output_path: Path, voices: dict[str, str]) -> bool:
    """Render a multi-voice script (panel/interview) to audio.

    Parses HOST:/GUEST: or HOST_A:/HOST_B: markers and renders each speaker
    with their assigned voice. Concatenates with brief gaps.
    """
    import re

    # Parse speaker markers — only match the markers used in generation prompts
    _SPEAKER_RE = r'((?:HOST_A|HOST_B|HOST|GUEST):)'
    segments = re.split(_SPEAKER_RE, script)

    # Build ordered list of (speaker_key, text)
    parts: list[tuple[str, str]] = []
    current_speaker = None
    for seg in segments:
        seg = seg.strip()
        if not seg:
            continue
        if re.match(r'^(?:HOST_A|HOST_B|HOST|GUEST):$', seg):
            current_speaker = seg.rstrip(':').strip()
        elif current_speaker:
            parts.append((current_speaker, seg))
        else:
            # No speaker marker yet, treat as host
            parts.append(("HOST", seg))

    if not parts:
        # No markers found, render as single voice
        host_voice = voices.get("host", "am_michael")
        return render_single_voice(script, output_path, host_voice)

    # Map speaker keys to voices
    voice_map = {}
    host_voice = voices.get("host", "am_michael")
    guest_voice = voices.get("guest", "af_bella")

    for key in ("HOST", "HOST_A"):
        voice_map[key] = host_voice
    for key in ("GUEST", "HOST_B"):
        voice_map[key] = guest_voice

    log(f"  Rendering {len(parts)} dialogue segments...")

    # Use a temp directory for chunks so the streamer doesn't consume them
    import tempfile, shutil
    tmp_dir = Path(tempfile.mkdtemp(prefix="writ_dialogue_"))

    # Render each part
    chunk_files = []
    for i, (speaker, text) in enumerate(parts):
        voice = voice_map.get(speaker, host_voice)
        chunk_path = tmp_dir / f"part{i:03d}.wav"

        # Clean text
        text = preprocess_for_tts(text)
        if not text.strip():
            continue

        # Render in sub-chunks if long
        if len(text.split()) > 100:
            if render_single_voice(text, chunk_path, voice):
                chunk_files.append(chunk_path)
        else:
            for attempt in range(2):
                if render_kokoro(text, chunk_path, voice):
                    chunk_files.append(chunk_path)
                    break
                time.sleep(2)

    if not chunk_files:
        log("  No dialogue parts rendered")
        shutil.rmtree(tmp_dir, ignore_errors=True)
        return False

    result = concatenate_audio(chunk_files, output_path, gap_seconds=0.3)
    shutil.rmtree(tmp_dir, ignore_errors=True)
    return result


# =============================================================================
# MAIN GENERATION PIPELINE
# =============================================================================


def generate_segment(
    show_id: str,
    show_name: str,
    show_description: str,
    host_id: str,
    topic_focus: str,
    segment_type: str,
    voices: dict[str, str],
    topic: str | None = None,
) -> Path | None:
    """Generate a single talk segment with audio."""
    if topic is None:
        topic = select_topic(topic_focus, segment_type)

    min_words, max_words = SEGMENT_WORD_TARGETS.get(segment_type, (1500, 2500))
    log(f"=== Generating {segment_type} for {show_name} ===")
    log(f"  Topic: {topic[:80]}...")
    log(f"  Target: {min_words}-{max_words} words")
    log(f"  Host: {host_id} (voice: {voices.get('host', 'am_michael')})")

    # Build prompt and generate script
    prompt = build_generation_prompt(
        host_id=host_id,
        segment_type=segment_type,
        topic=topic,
        show_name=show_name,
        show_description=show_description,
        topic_focus=topic_focus,
        guest_voice=voices.get("guest"),
    )

    # Try generation with one retry
    script = None
    for attempt in range(2):
        script = run_generation(prompt, segment_type)
        if script:
            break
        if attempt == 0:
            log("  Retrying generation...")
            time.sleep(3)

    if not script:
        log("  Failed to generate script")
        return None

    word_count = len(script.split())
    est_minutes = word_count / 130
    log(f"  Generated {word_count} words (~{est_minutes:.1f} min)")

    # Prepare output
    show_dir = OUTPUT_DIR / show_id
    show_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    topic_slug = topic[:30].lower()
    for char in ' -:,\'".?!()':
        topic_slug = topic_slug.replace(char, '_')
    topic_slug = '_'.join(filter(None, topic_slug.split('_')))

    output_path = show_dir / f"{segment_type}_{topic_slug}_{timestamp}.wav"

    # Preprocess for TTS
    processed = preprocess_for_tts(script)

    # Render audio
    log("  Rendering audio...")
    is_multi_voice = segment_type in ("panel", "interview")

    if is_multi_voice:
        success = render_multi_voice(processed, output_path, voices)
    else:
        host_voice = voices.get("host", "am_michael")
        success = render_single_voice(processed, output_path, host_voice)

    if not success or not output_path.exists():
        log("  TTS rendering failed")
        return None

    # Get duration and save metadata
    duration = get_audio_duration(output_path)
    duration_str = f"{int(duration // 60)}:{int(duration % 60):02d}" if duration else "?"

    SCRIPTS_DIR.mkdir(parents=True, exist_ok=True)
    meta_path = SCRIPTS_DIR / f"talk_{segment_type}_{timestamp}.json"
    with open(meta_path, "w") as f:
        json.dump({
            "type": segment_type,
            "show_id": show_id,
            "show_name": show_name,
            "host": host_id,
            "topic": topic,
            "script": script,
            "word_count": word_count,
            "duration_seconds": duration,
            "voices": voices,
            "generated_at": datetime.now().isoformat(),
        }, f, indent=2)

    log(f"  Created: {output_path.name} ({duration_str})")
    return output_path


def generate_for_show(
    show_id: str,
    schedule: StationSchedule,
    count: int = 3,
    segment_type: str | None = None,
    topic: str | None = None,
) -> int:
    """Generate segments for a specific show."""
    if show_id not in schedule.shows:
        log(f"Unknown show: {show_id}")
        log(f"Available: {', '.join(schedule.shows.keys())}")
        return 0

    show = schedule.shows[show_id]

    log(f"\n{'='*60}")
    log(f"Generating {count} segments for: {show.name}")
    log(f"{'='*60}")

    success = 0
    for i in range(count):
        # Pick segment type
        if segment_type:
            st = segment_type
        else:
            st = random.choice(show.segment_types)

        log(f"\n[{i+1}/{count}]")

        result = generate_segment(
            show_id=show_id,
            show_name=show.name,
            show_description=show.description,
            host_id=show.host,
            topic_focus=show.topic_focus,
            segment_type=st,
            voices=dict(show.voices),
            topic=topic,
        )
        if result:
            success += 1

        if i < count - 1:
            time.sleep(2)

    return success


def generate_for_current(schedule: StationSchedule, count: int = 3) -> int:
    """Generate segments for the currently active show."""
    resolved = schedule.resolve()
    return generate_for_show(resolved.show_id, schedule, count)


def generate_all(schedule: StationSchedule, count_per_show: int = 3) -> dict[str, int]:
    """Generate content for all shows."""
    log("=== WRIT-FM Full Talk Content Generation ===")
    log(f"Generating {count_per_show} segments per show")

    results = {}
    for show_id in schedule.shows:
        results[show_id] = generate_for_show(show_id, schedule, count_per_show)
        time.sleep(3)

    log("\n=== Generation Complete ===")
    total = 0
    for show_id, count in results.items():
        show = schedule.shows[show_id]
        log(f"  {show.name}: {count}/{count_per_show}")
        total += count

    log(f"Total: {total} segments generated")
    return results


def count_segments() -> dict[str, int]:
    """Count existing segments per show."""
    counts = {}
    if OUTPUT_DIR.exists():
        for show_dir in OUTPUT_DIR.iterdir():
            if show_dir.is_dir():
                wavs = list(show_dir.glob("*.wav"))
                counts[show_dir.name] = len(wavs)
    return counts


# =============================================================================
# CLI
# =============================================================================


def main():
    parser = argparse.ArgumentParser(description="WRIT-FM Talk Segment Generator")
    parser.add_argument("--show", help="Show ID to generate for (default: current show)")
    parser.add_argument("--type", dest="segment_type", help="Specific segment type")
    parser.add_argument("--topic", help="Specific topic")
    parser.add_argument("--count", type=int, default=3, help="Segments to generate (default: 3)")
    parser.add_argument("--all", action="store_true", help="Generate for all shows")
    parser.add_argument("--status", action="store_true", help="Show segment counts per show")
    parser.add_argument("--list-types", action="store_true", help="List segment types")
    parser.add_argument("--list-topics", help="List topics for a focus area")

    args = parser.parse_args()

    if args.list_types:
        print("\n=== Segment Types ===\n")
        print("Long-form (primary content):")
        for st in ["deep_dive", "news_analysis", "interview", "panel", "story", "listener_mailbag", "music_essay"]:
            mn, mx = SEGMENT_WORD_TARGETS[st]
            print(f"  {st:20s} {mn}-{mx} words")
        print("\nShort-form (transitions):")
        for st in ["station_id", "show_intro", "show_outro"]:
            mn, mx = SEGMENT_WORD_TARGETS[st]
            print(f"  {st:20s} {mn}-{mx} words")
        return 0

    if args.list_topics:
        focus = args.list_topics
        pool = TOPIC_POOLS.get(focus)
        if not pool:
            print(f"Unknown focus: {focus}")
            print(f"Available: {', '.join(TOPIC_POOLS.keys())}")
            return 1
        print(f"\n=== Topics: {focus} ===\n")
        for i, topic in enumerate(pool, 1):
            print(f"  {i:2d}. {topic}")
        return 0

    # Load schedule
    try:
        schedule = load_schedule(SCHEDULE_PATH)
        log(f"Loaded schedule with {len(schedule.shows)} shows")
    except Exception as e:
        log(f"Failed to load schedule: {e}")
        return 1

    if args.status:
        counts = count_segments()
        print("\n=== Talk Segment Inventory ===\n")
        for show_id, show in schedule.shows.items():
            c = counts.get(show_id, 0)
            status = "OK" if c >= 6 else "LOW" if c >= 3 else "EMPTY"
            print(f"  {show.name:30s} {c:3d} segments  [{status}]")
        total = sum(counts.values())
        print(f"\n  Total: {total} segments")
        return 0

    # Generate
    if args.all:
        generate_all(schedule, args.count)
    elif args.show:
        generate_for_show(args.show, schedule, args.count, args.segment_type, args.topic)
    else:
        if args.segment_type or args.topic:
            resolved = schedule.resolve()
            generate_for_show(
                resolved.show_id, schedule, args.count, args.segment_type, args.topic
            )
        else:
            generate_for_current(schedule, args.count)

    return 0


if __name__ == "__main__":
    sys.exit(main())
