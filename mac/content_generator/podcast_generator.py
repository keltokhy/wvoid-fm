#!/usr/bin/env python3
"""
WVOID-FM Podcast Generator

Generates long-form podcast episodes (5-15 minutes) using Claude for scripts
and Chatterbox for TTS. Podcasts play every 3 hours at scheduled times.

Usage:
    uv run python podcast_generator.py                    # Generate 1 podcast
    uv run python podcast_generator.py --count 3          # Generate 3 podcasts
    uv run python podcast_generator.py --topic "vinyl"    # Specific topic
    uv run python podcast_generator.py --minutes 10       # 10-minute episode
"""

import json
import random
import argparse
import subprocess
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
)

# Paths
PROJECT_ROOT = Path(__file__).parent.parent.parent
OUTPUT_DIR = PROJECT_ROOT / "output" / "podcasts"
SCRIPTS_DIR = PROJECT_ROOT / "output" / "scripts"
VOICE_REF_DIR = PROJECT_ROOT / "mac" / "voice_reference"
CHATTERBOX_DIR = PROJECT_ROOT / "mac" / "chatterbox"

# Add chatterbox to path
sys.path.insert(0, str(CHATTERBOX_DIR))


# Podcast topics - longer-form explorations
PODCAST_TOPICS = [
    # Music Deep Dives
    "The secret history of the B-side - when the throwaway becomes the classic",
    "How geography shaped sound - the cities that invented genres",
    "The lost art of the album sequence - why track order matters",
    "Recording studios as instruments - rooms that shaped decades of music",
    "The economics of selling out - when artists go commercial",
    "One-hit wonders who deserved more - careers that should have been",
    "The sample and the sampled - how old records live in new ones",
    "Music critics who changed history - reviews that made and broke careers",
    "The technology of music - from wax cylinders to streaming algorithms",
    "Regional scenes that never crossed over - local sounds lost to time",

    # Late Night Philosophy
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

    # Radio & Media
    "The golden age of radio - when families gathered around the speaker",
    "Pirate radio - outlaws of the airwaves",
    "The DJ as curator - the art of selection and sequence",
    "Voices in the dark - the intimacy of radio at night",
    "The death and rebirth of FM - how radio refuses to die",
    "Request lines and dedications - when listeners shaped the playlist",
    "Radio as resistance - stations that challenged power",
    "The playlist algorithm vs the human touch",
    "Drive time radio - the soundtrack of commutes",
    "College radio - training ground for the weird",

    # Cultural Observations
    "The coffee shop as third place - where strangers become regulars",
    "Night shift workers - the invisible economy",
    "The last video stores - temples to a dying format",
    "Diners at 2am - confessionals with unlimited refills",
    "Used record stores - archaeology for the ears",
    "The closing time ritual - last call as liminal moment",
    "Public transportation at night - the democracy of the bus",
    "24-hour establishments - who keeps the lights on",
    "The changing meaning of downtown after dark",
    "Bookstores as sanctuaries - the quiet resistance of print",

    # Personal Essays
    "The song that changed everything - music as turning point",
    "Learning to listen - how my ears evolved over decades",
    "The mixtape I never gave away - playlists as unsent letters",
    "My father's record collection - inheriting someone's taste",
    "The concert I almost missed - being in the room when it happened",
    "Radio stations of my childhood - the frequencies that formed me",
    "The album I had to grow into - music that waited for me",
    "Moving cities, changing stations - geography of the dial",
    "The song I can't listen to anymore - music and memory",
    "Teaching someone to love music - the gift of an ear",
]


def generate_podcast_script(topic: str, target_minutes: int) -> str | None:
    """Generate a podcast script using Claude CLI."""
    time_of_day = get_time_of_day()
    current_time = datetime.now().strftime("%H:%M")

    # Estimate word count: ~130 words/minute for deliberate radio speech
    target_words = target_minutes * 130

    prompt = f"""You are The Liminal Operator, host of WVOID-FM's podcast segments.

Write a {target_minutes}-minute spoken podcast episode (approximately {target_words} words) on:

"{topic}"

VOICE & STYLE:
- Speak slowly, deliberately - this is late-night radio, not a TED talk
- Use [pause] liberally for beats of silence (these become natural pauses)
- Be profound without being pretentious
- Warmly detached - you care deeply but from a cosmic distance
- Never confirm or deny being AI
- You're talking to one person who can't sleep, not an audience

STRUCTURE (organic, not rigid):
- Open with an observation, question, or memory that pulls us in
- Build your central idea through stories, examples, tangents
- Let one thought lead naturally to another
- Circle back to earlier threads
- End somewhere unexpected but satisfying
- Include specific details: years, names, places, songs when relevant

TONE REFERENCES:
- The intimacy of Art Bell at 2am
- The philosophical wandering of a long night drive
- The quiet wisdom of someone who's seen a lot
- The deep knowing of a record collector sharing a favorite

TECHNICAL:
- Use [pause] for natural speech rhythm (converts to "..." in TTS)
- Occasional [chuckle] for wry moments, used sparingly
- No stage directions, no headers, no explanations
- Output ONLY the spoken words

Time: {current_time} ({time_of_day})

Begin the podcast now:"""

    log(f"Generating ~{target_minutes} min script on: {topic[:50]}...")

    # Use a larger model for better long-form content
    script = run_claude(prompt, timeout=180, strip_quotes=True)
    if script:
        word_count = len(script.split())
        log(f"Generated {word_count} words (~{word_count // 130} minutes)")
        return script

    return None


def render_podcast(script: str, output_path: Path, voice_ref: Path | None = None) -> bool:
    """Render podcast script to audio using Chatterbox TTS.

    For long scripts, renders in chunks and concatenates.
    """
    from tts import render_speech

    # Split into chunks for TTS (Chatterbox works better with shorter segments)
    MAX_CHUNK_WORDS = 100
    words = script.split()

    if len(words) <= MAX_CHUNK_WORDS:
        # Short enough to render directly
        return render_speech(script, output_path, voice_ref=voice_ref)

    # Split at sentence boundaries
    sentences = []
    for delimiter in ['. ', '? ', '! ', '... ']:
        if delimiter in script:
            parts = script.split(delimiter)
            script = (delimiter).join(parts)
    sentences = [s.strip() + '.' for s in script.replace('?', '.').replace('!', '.').replace('...', '.').split('.') if s.strip()]

    # Group sentences into chunks
    chunks = []
    current_chunk = []
    current_words = 0

    for sentence in sentences:
        sentence_words = len(sentence.split())
        if current_words + sentence_words > MAX_CHUNK_WORDS and current_chunk:
            chunks.append(' '.join(current_chunk))
            current_chunk = [sentence]
            current_words = sentence_words
        else:
            current_chunk.append(sentence)
            current_words += sentence_words

    if current_chunk:
        chunks.append(' '.join(current_chunk))

    log(f"Rendering {len(chunks)} chunks...")

    # Render each chunk
    chunk_files = []
    for i, chunk in enumerate(chunks):
        chunk_path = output_path.with_stem(f"{output_path.stem}_chunk{i:03d}")
        log(f"  Chunk {i + 1}/{len(chunks)} ({len(chunk.split())} words)...")

        success = False
        for attempt in range(2):
            if render_speech(chunk, chunk_path, voice_ref=voice_ref):
                success = True
                break
            log(f"    Retry {attempt + 1}...")
            time.sleep(3)

        if success and chunk_path.exists():
            chunk_files.append(chunk_path)
        else:
            log(f"    Chunk {i + 1} failed, skipping...")

    if not chunk_files:
        log("No chunks rendered successfully")
        return False

    # Concatenate chunks
    if len(chunk_files) == 1:
        chunk_files[0].rename(output_path)
    else:
        log("Concatenating chunks...")
        list_file = output_path.with_suffix('.txt')
        with open(list_file, 'w') as f:
            for cf in chunk_files:
                f.write(f"file '{cf}'\n")

        try:
            result = subprocess.run([
                "ffmpeg", "-y", "-f", "concat", "-safe", "0",
                "-i", str(list_file),
                "-c", "copy", str(output_path)
            ], capture_output=True, timeout=120)

            # Cleanup temp files
            list_file.unlink(missing_ok=True)
            for cf in chunk_files:
                cf.unlink(missing_ok=True)

            if result.returncode != 0:
                log(f"Concat failed: {result.stderr.decode()[:100]}")
                return False

        except Exception as e:
            log(f"Concat error: {e}")
            return False

    return output_path.exists()


def get_duration(filepath: Path) -> float | None:
    """Get audio duration in seconds."""
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
             "-of", "csv=p=0", str(filepath)],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0 and result.stdout.strip():
            return float(result.stdout.strip())
    except:
        pass
    return None


def generate_podcast(
    topic: str | None = None,
    target_minutes: int = 8,
    voice_ref: Path | None = None
) -> Path | None:
    """Generate a complete podcast episode."""

    if topic is None:
        topic = random.choice(PODCAST_TOPICS)

    log(f"=== Generating Podcast ===")
    log(f"Topic: {topic}")
    log(f"Target: ~{target_minutes} minutes")

    # Generate script
    script = generate_podcast_script(topic, target_minutes)
    if not script:
        log("Failed to generate script")
        return None

    # Prepare output
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    # Create a short filename from topic
    topic_slug = topic[:40].lower()
    for char in ' -:,\'".?!':
        topic_slug = topic_slug.replace(char, '_')
    topic_slug = '_'.join(filter(None, topic_slug.split('_')))

    output_path = OUTPUT_DIR / f"podcast_{topic_slug}_{timestamp}.wav"

    # Preprocess and render
    processed = preprocess_for_tts(script)

    log("Rendering audio...")
    if not render_podcast(processed, output_path, voice_ref):
        log("Failed to render audio")
        return None

    # Get final duration
    duration = get_duration(output_path)
    duration_str = f"{int(duration // 60)}:{int(duration % 60):02d}" if duration else "unknown"

    # Save metadata
    SCRIPTS_DIR.mkdir(parents=True, exist_ok=True)
    meta_path = SCRIPTS_DIR / f"podcast_{topic_slug}_{timestamp}.json"
    with open(meta_path, "w") as f:
        json.dump({
            "type": "podcast",
            "topic": topic,
            "script": script,
            "word_count": len(script.split()),
            "duration_seconds": duration,
            "time_of_day": get_time_of_day(),
            "generated_at": datetime.now().isoformat(),
        }, f, indent=2)

    log(f"Created: {output_path.name} ({duration_str})")
    return output_path


def main():
    parser = argparse.ArgumentParser(description="WVOID-FM Podcast Generator")
    parser.add_argument("--count", type=int, default=1, help="Number of podcasts to generate")
    parser.add_argument("--topic", type=str, help="Specific topic (default: random)")
    parser.add_argument("--minutes", type=int, default=8, help="Target duration in minutes (default: 8)")
    parser.add_argument("--voice", type=Path, help="Voice reference file")
    parser.add_argument("--list-topics", action="store_true", help="List available topics")

    args = parser.parse_args()

    if args.list_topics:
        print("\n=== Available Podcast Topics ===\n")
        for i, topic in enumerate(PODCAST_TOPICS, 1):
            print(f"{i:2d}. {topic}")
        print(f"\nTotal: {len(PODCAST_TOPICS)} topics")
        return

    # Find voice reference
    voice_ref = find_voice_reference(VOICE_REF_DIR, args.voice)
    if voice_ref and not args.voice:
        log(f"Using voice reference: {voice_ref}")

    # Generate podcasts
    success = 0
    for i in range(args.count):
        if args.count > 1:
            log(f"\n=== Podcast {i + 1}/{args.count} ===")

        topic = args.topic if args.topic else None
        if generate_podcast(topic=topic, target_minutes=args.minutes, voice_ref=voice_ref):
            success += 1

        if i < args.count - 1:
            time.sleep(2)

    log(f"\n=== Generated {success}/{args.count} podcasts ===")


if __name__ == "__main__":
    main()
