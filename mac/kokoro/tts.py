#!/usr/bin/env python3
"""
WVOID-FM Kokoro TTS Module

Fast, high-quality TTS using Kokoro. No voice cloning but very fast generation.
Good for parallel batch generation.

Setup:
    cd mac/kokoro
    uv venv
    uv pip install kokoro soundfile

Usage:
    from mac.kokoro.tts import render_speech
    render_speech("Hello world", Path("output.wav"), voice="af_heart")

Available voices:
    American Female: af_heart, af_alloy, af_aoede, af_bella, af_jessica, af_kore, af_nicole, af_nova, af_river, af_sarah, af_sky
    American Male: am_adam, am_echo, am_eric, am_fenrir, am_liam, am_michael, am_onyx, am_puck, am_santa
    British Female: bf_alice, bf_emma, bf_isabella, bf_lily
    British Male: bm_daniel, bm_fable, bm_george, bm_lewis
"""

import os
import subprocess
from pathlib import Path

# Get the kokoro directory (where this file lives)
KOKORO_DIR = Path(__file__).parent
VENV_PYTHON = KOKORO_DIR / ".venv" / "bin" / "python"

# Default voice - deep male for The Operator
DEFAULT_VOICE = "am_michael"


def setup_venv():
    """Create and set up the kokoro venv if it doesn't exist."""
    venv_dir = KOKORO_DIR / ".venv"
    if not venv_dir.exists():
        print("Setting up Kokoro venv...")
        subprocess.run(["uv", "venv"], cwd=KOKORO_DIR, check=True)
        subprocess.run(
            ["uv", "pip", "install", "kokoro", "soundfile", "pip"],
            cwd=KOKORO_DIR,
            check=True
        )
        print("Kokoro venv ready")
    return VENV_PYTHON.exists()


def render_speech(
    text: str,
    output_path: Path,
    voice: str = DEFAULT_VOICE,
    speed: float = 1.0,
) -> bool:
    """
    Render text to speech using Kokoro TTS.

    Args:
        text: The text to speak
        output_path: Where to save the WAV file
        voice: Voice ID (see module docstring for options)
        speed: Speech speed multiplier (0.5-2.0)

    Returns:
        True if successful, False otherwise
    """
    if not VENV_PYTHON.exists():
        if not setup_venv():
            print("Failed to set up Kokoro venv")
            return False

    # Escape text for embedding in Python string
    escaped_text = text.replace('\\', '\\\\').replace('"', '\\"').replace('\n', ' ')

    # Build the TTS script
    tts_script = f'''
import os
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"
import warnings
warnings.filterwarnings("ignore")

from kokoro import KPipeline
import soundfile as sf

pipe = KPipeline(lang_code="a", repo_id="hexgrad/Kokoro-82M")

text = "{escaped_text}"
voice = "{voice}"
speed = {speed}

# Generate audio
generator = pipe(text, voice=voice, speed=speed)

# Collect all audio segments
audio_segments = []
for _, _, audio in generator:
    audio_segments.append(audio)

# Concatenate if multiple segments
import numpy as np
if len(audio_segments) == 1:
    full_audio = audio_segments[0]
else:
    full_audio = np.concatenate(audio_segments)

# Save to file
sf.write("{output_path}", full_audio, 24000)
print("SUCCESS")
'''

    try:
        env = {**os.environ, "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1"}
        result = subprocess.run(
            [str(VENV_PYTHON), "-c", tts_script],
            capture_output=True,
            text=True,
            timeout=300,  # 5 minutes max (Kokoro is fast)
            cwd=str(KOKORO_DIR),
            env=env,
        )
        if "SUCCESS" in result.stdout:
            return True
        else:
            print(f"Kokoro error: {result.stderr}")
            return False
    except subprocess.TimeoutExpired:
        print("Kokoro timed out")
        return False
    except Exception as e:
        print(f"TTS error: {e}")
        return False


# List available voices
VOICES = {
    # American Female
    "af_heart": "American Female - Heart (warm, expressive)",
    "af_alloy": "American Female - Alloy",
    "af_aoede": "American Female - Aoede",
    "af_bella": "American Female - Bella",
    "af_jessica": "American Female - Jessica",
    "af_kore": "American Female - Kore",
    "af_nicole": "American Female - Nicole",
    "af_nova": "American Female - Nova",
    "af_river": "American Female - River",
    "af_sarah": "American Female - Sarah",
    "af_sky": "American Female - Sky",
    # American Male
    "am_adam": "American Male - Adam",
    "am_echo": "American Male - Echo",
    "am_eric": "American Male - Eric",
    "am_fenrir": "American Male - Fenrir (deep)",
    "am_liam": "American Male - Liam",
    "am_michael": "American Male - Michael (warm baritone)",
    "am_onyx": "American Male - Onyx (deep)",
    "am_puck": "American Male - Puck",
    "am_santa": "American Male - Santa",
    # British Female
    "bf_alice": "British Female - Alice",
    "bf_emma": "British Female - Emma",
    "bf_isabella": "British Female - Isabella",
    "bf_lily": "British Female - Lily",
    # British Male
    "bm_daniel": "British Male - Daniel",
    "bm_fable": "British Male - Fable",
    "bm_george": "British Male - George",
    "bm_lewis": "British Male - Lewis",
}


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("text", help="Text to speak")
    parser.add_argument("-o", "--output", default="test.wav", help="Output file")
    parser.add_argument("-v", "--voice", default=DEFAULT_VOICE, help="Voice ID")
    parser.add_argument("-s", "--speed", type=float, default=1.0, help="Speed multiplier")
    parser.add_argument("--list-voices", action="store_true", help="List available voices")
    args = parser.parse_args()

    if args.list_voices:
        print("Available voices:")
        for vid, desc in VOICES.items():
            print(f"  {vid}: {desc}")
    else:
        success = render_speech(args.text, Path(args.output), voice=args.voice, speed=args.speed)
        print("Success!" if success else "Failed")
