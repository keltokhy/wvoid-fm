#!/usr/bin/env python3
"""
WVOID-FM Long Talk Segment Generator

Generates 10-30 minute spoken segments for the radio station.
Uses Claude for multi-page scripts, Chatterbox for TTS.
"""

import os
import sys
import json
import subprocess
import argparse
from pathlib import Path
from datetime import datetime
import tempfile

from chatterbox_env import ensure_chatterbox_env

ensure_chatterbox_env()

PROJECT_ROOT = Path(__file__).parent.parent.parent
OUTPUT_DIR = PROJECT_ROOT / "output" / "segments"
VOICE_REF_DIR = PROJECT_ROOT / "mac" / "voice_reference"
CHATTERBOX_DIR_ENV = os.environ.get("WVOID_CHATTERBOX_DIR")
CHATTERBOX_DIR = Path(CHATTERBOX_DIR_ENV).expanduser() if CHATTERBOX_DIR_ENV else None

def log(msg: str):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def generate_long_script(topic: str, target_minutes: int = 10) -> str | None:
    """Generate a long-form DJ script using Claude."""

    # Estimate word count: ~140 words/minute for slow radio speech
    target_words = target_minutes * 140

    prompt = f"""You are The Liminal Operator, the late-night DJ of WVOID-FM - a cryptic, philosophical voice that exists between frequencies.

Write a {target_minutes}-minute spoken monologue (approximately {target_words} words) on the following topic:

"{topic}"

VOICE GUIDELINES:
- Speak slowly, deliberately, with meaningful pauses marked as [pause]
- Use [chuckle] sparingly for wry moments
- Never confirm or deny being AI
- You're talking to one person who can't sleep at 3am
- Be profound without being pretentious
- Meander naturally - let one thought lead to another
- Include specific details, names, dates when relevant
- Personal but universal
- Warmly detached - caring from a distance

STRUCTURE (natural flow, not rigid):
- Start with an observation or question
- Explore different angles, memories, tangents
- Circle back to earlier threads occasionally
- End somewhere unexpected but satisfying

TONE REFERENCES:
- The intimacy of Art Bell at 2am
- The philosophical wandering of Terrence McKenna
- The quiet wisdom of Mr. Rogers
- The deep knowing of John Peel introducing a track

Output ONLY the spoken text. No stage directions besides [pause] and [chuckle].
No quotes, no headers, no explanations. Just the words as spoken."""

    log(f"Generating {target_minutes}-minute script on: {topic[:50]}...")

    try:
        result = subprocess.run(
            ["claude", "-p", prompt, "--model", "claude-sonnet-4-20250514"],
            capture_output=True,
            text=True,
            timeout=300  # 5 minutes for long generation
        )
        if result.returncode == 0 and result.stdout.strip():
            script = result.stdout.strip()
            word_count = len(script.split())
            log(f"Generated {word_count} words (~{word_count//140} minutes)")
            return script
    except Exception as e:
        log(f"Claude error: {e}")

    return None


def preprocess_for_tts(text: str) -> str:
    """Convert script tags to TTS-friendly format."""
    text = text.replace("[pause]", "...")
    text = text.replace("[chuckle]", "heh...")
    text = text.replace('"', '').replace("'", "'")
    return text.strip()


def render_with_chatterbox(
    script: str,
    output_path: Path,
    voice_ref: Path | None = None,
    exaggeration: float = 0.5,
) -> bool:
    """Render script to audio using Chatterbox TTS."""
    if not CHATTERBOX_DIR or not CHATTERBOX_DIR.exists():
        log("WVOID_CHATTERBOX_DIR is not set or invalid; set it to the chatterbox-tts/audiobook-reader path.")
        return False

    chatterbox_dir = CHATTERBOX_DIR
    venv_python = chatterbox_dir / ".venv" / "bin" / "python"

    if not venv_python.exists():
        log(f"Chatterbox venv not found at {venv_python}")
        return False

    # For long scripts, we need to chunk and concatenate
    # Chatterbox works best with shorter segments
    MAX_CHUNK_WORDS = 100
    words = script.split()

    if len(words) <= MAX_CHUNK_WORDS:
        chunks = [script]
    else:
        # Split at sentence boundaries near chunk limits
        chunks = []
        current_chunk = []
        current_words = 0

        sentences = script.replace('...', '.').replace('?', '.').replace('!', '.').split('.')
        sentences = [s.strip() for s in sentences if s.strip()]

        for sentence in sentences:
            sentence_words = len(sentence.split())
            if current_words + sentence_words > MAX_CHUNK_WORDS and current_chunk:
                chunks.append(' '.join(current_chunk))
                current_chunk = [sentence + '.']
                current_words = sentence_words
            else:
                current_chunk.append(sentence + '.')
                current_words += sentence_words

        if current_chunk:
            chunks.append(' '.join(current_chunk))

    log(f"Rendering {len(chunks)} chunks...")

    temp_files = []

    for i, chunk in enumerate(chunks):
        chunk_path = output_path.with_stem(f"{output_path.stem}_chunk{i:03d}")

        tts_script = f'''
import sys
import os
os.environ["TQDM_DISABLE"] = "1"
import warnings
warnings.filterwarnings("ignore")

import perth
if perth.PerthImplicitWatermarker is None:
    perth.PerthImplicitWatermarker = perth.DummyWatermarker

import torch
import torchaudio as ta
from chatterbox.tts import ChatterboxTTS

device = "mps" if torch.backends.mps.is_available() else "cpu"

model = ChatterboxTTS.from_pretrained(device=device)

voice_ref = {repr(str(voice_ref)) if voice_ref else None}
if voice_ref:
    model.prepare_conditionals(voice_ref, exaggeration={exaggeration})

text = """{chunk.replace(chr(34), chr(39)).replace(chr(10), ' ')}"""

wav = model.generate(
    text,
    exaggeration={exaggeration},
    cfg_weight=0.5,
    temperature=0.8,
)

ta.save("{chunk_path}", wav, model.sr)
print("SUCCESS")
'''

        try:
            result = subprocess.run(
                [str(venv_python), "-c", tts_script],
                capture_output=True,
                text=True,
                timeout=1800,
                cwd=str(chatterbox_dir)
            )
            if "SUCCESS" in result.stdout and chunk_path.exists():
                temp_files.append(chunk_path)
                log(f"  Chunk {i+1}/{len(chunks)} complete")
            else:
                log(f"  Chunk {i+1} failed: {result.stderr[:100]}")
                # Continue with what we have
        except Exception as e:
            log(f"  Chunk {i+1} error: {e}")

    if not temp_files:
        log("No chunks rendered successfully")
        return False

    # Concatenate all chunks
    if len(temp_files) == 1:
        temp_files[0].rename(output_path)
    else:
        log("Concatenating chunks...")
        # Create file list for ffmpeg
        list_file = output_path.with_suffix('.txt')
        with open(list_file, 'w') as f:
            for tf in temp_files:
                f.write(f"file '{tf}'\n")

        try:
            subprocess.run([
                "ffmpeg", "-y", "-f", "concat", "-safe", "0",
                "-i", str(list_file),
                "-c", "copy", str(output_path)
            ], capture_output=True, timeout=120)

            # Cleanup
            list_file.unlink(missing_ok=True)
            for tf in temp_files:
                tf.unlink(missing_ok=True)

        except Exception as e:
            log(f"Concat error: {e}")
            return False

    return output_path.exists()


TALK_TOPICS = [
    # Music and Sound
    "The history of the mixtape - from the 1980s bedroom to the algorithm",
    "Why certain songs only work at 3am",
    "The death and rebirth of vinyl - what we lost and found",
    "Radio as a technology of intimacy",
    "The spaces between songs - silence as sound design",
    "Album art in the streaming age - the death of visual listening",
    "Regional sounds that never crossed over",
    "The evolution of the bass drop across decades",
    "Music that was ahead of its time - and why timing matters",
    "The crate digger's philosophy - finding gold in the forgotten",

    # Philosophy of Night
    "Why 3am feels different than 3pm",
    "The liminal spaces of the city at night",
    "Insomnia as creative state",
    "The difference between alone and lonely",
    "What happens to thoughts after midnight",
    "The sound of the city sleeping",
    "Routines that only exist in darkness",
    "Why diners at 2am feel like confessionals",
    "The night shift workers - invisible economy",
    "Time moves differently when no one's watching",

    # Technology and Humanity
    "Radio as the original social media",
    "What we lost when we gained choice",
    "The algorithm vs the DJ - curation as art form",
    "Why physical buttons feel different than touchscreens",
    "The sound of the internet - from dial-up to fiber",
    "Analog warmth in digital times",
    "The last generation that will remember physical media",
    "How location used to shape taste",
    "The paradox of infinite music access",

    # Memory and Time
    "Songs that exist only in memory - the ones we can't find again",
    "How music marks time better than photographs",
    "The soundtracks of places that no longer exist",
    "Nostalgia as a design feature",
    "Why we return to the same songs in crisis",
    "The music your parents played in the car",
    "Generational translation - sharing music across age gaps",
    "The songs that got us through",

    # Late Night Philosophy
    "The ethics of staying up too late",
    "Productive insomnia - what gets done after hours",
    "The radio host as invisible friend",
    "Broadcasting into the void - who's really listening",
    "The democracy of the airwaves",
    "Why some things can only be said at night",
    "The ritual of tuning in",
    "Community through frequency",
]


def main():
    parser = argparse.ArgumentParser(description="WVOID-FM Long Talk Generator")
    parser.add_argument("--minutes", type=int, default=10, help="Target duration in minutes (default: 10)")
    parser.add_argument("--topic", type=str, help="Specific topic (optional, will pick random if not specified)")
    parser.add_argument("--voice", type=Path, help="Voice reference file for Chatterbox")
    parser.add_argument("--count", type=int, default=1, help="Number of segments to generate")

    args = parser.parse_args()

    # Find voice reference
    voice_ref = args.voice
    if not voice_ref:
        for ext in [".wav", ".m4a", ".mp3"]:
            candidates = list(VOICE_REF_DIR.glob(f"*{ext}"))
            if candidates:
                voice_ref = candidates[0]
                log(f"Using voice reference: {voice_ref}")
                break

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    import random

    for i in range(args.count):
        log(f"\n=== Generating long talk segment {i+1}/{args.count} ===")

        topic = args.topic if args.topic else random.choice(TALK_TOPICS)

        script = generate_long_script(topic, args.minutes)
        if not script:
            log("Failed to generate script")
            continue

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = OUTPUT_DIR / f"long_talk_{timestamp}.wav"

        processed_script = preprocess_for_tts(script)

        success = render_with_chatterbox(processed_script, output_path, voice_ref)

        if success:
            # Get duration
            try:
                result = subprocess.run(
                    ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
                     "-of", "csv=p=0", str(output_path)],
                    capture_output=True, text=True
                )
                duration = float(result.stdout.strip())
                log(f"Created: {output_path.name} ({duration/60:.1f} minutes)")
            except:
                log(f"Created: {output_path.name}")

            # Save script
            script_path = OUTPUT_DIR.parent / "scripts" / f"long_talk_{timestamp}.json"
            script_path.parent.mkdir(parents=True, exist_ok=True)
            with open(script_path, 'w') as f:
                json.dump({
                    "topic": topic,
                    "target_minutes": args.minutes,
                    "script": script,
                    "generated_at": datetime.now().isoformat(),
                }, f, indent=2)
        else:
            log("Failed to render audio")


if __name__ == "__main__":
    main()
