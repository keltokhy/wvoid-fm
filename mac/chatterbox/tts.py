#!/usr/bin/env python3
"""
WVOID-FM Chatterbox TTS Module

Renders text to speech using Chatterbox TTS with voice cloning.
This module is self-contained - just needs the venv set up once.

Setup:
    cd mac/chatterbox
    uv venv
    uv pip install chatterbox-tts torch torchaudio

Usage:
    from mac.chatterbox.tts import render_speech
    render_speech("Hello world", Path("output.wav"), voice_ref=Path("voice.wav"))
"""

import os
import sys
import subprocess
from pathlib import Path

# Get the chatterbox directory (where this file lives)
CHATTERBOX_DIR = Path(__file__).parent
VENV_PYTHON = CHATTERBOX_DIR / ".venv" / "bin" / "python"


def setup_venv():
    """Create and set up the chatterbox venv if it doesn't exist."""
    venv_dir = CHATTERBOX_DIR / ".venv"
    if not venv_dir.exists():
        print("Setting up Chatterbox venv...")
        subprocess.run(["uv", "venv"], cwd=CHATTERBOX_DIR, check=True)
        subprocess.run(
            ["uv", "pip", "install", "chatterbox-tts", "torch", "torchaudio"],
            cwd=CHATTERBOX_DIR,
            check=True
        )
        print("Chatterbox venv ready")
    return VENV_PYTHON.exists()


def render_speech(
    text: str,
    output_path: Path,
    voice_ref: Path | None = None,
    exaggeration: float = 0.5,
    cfg_weight: float = 0.5,
    temperature: float = 0.8,
) -> bool:
    """
    Render text to speech using Chatterbox TTS.

    Args:
        text: The text to speak
        output_path: Where to save the WAV file
        voice_ref: Optional voice reference WAV for cloning
        exaggeration: Voice exaggeration factor (0.0-1.0)
        cfg_weight: Classifier-free guidance weight
        temperature: Generation temperature

    Returns:
        True if successful, False otherwise
    """
    if not VENV_PYTHON.exists():
        if not setup_venv():
            print("Failed to set up Chatterbox venv")
            return False

    # Escape text for embedding in Python string
    escaped_text = text.replace('\\', '\\\\').replace('"', '\\"').replace('\n', ' ')

    # Build the TTS script
    tts_script = f'''
import sys
import os
os.environ["TQDM_DISABLE"] = "1"
import warnings
warnings.filterwarnings("ignore")

# Patch perth watermarker
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

text = "{escaped_text}"

wav = model.generate(
    text,
    exaggeration={exaggeration},
    cfg_weight={cfg_weight},
    temperature={temperature},
)

ta.save("{output_path}", wav, model.sr)
print("SUCCESS")
'''

    try:
        result = subprocess.run(
            [str(VENV_PYTHON), "-c", tts_script],
            capture_output=True,
            text=True,
            timeout=1800,  # 30 minutes max
            cwd=str(CHATTERBOX_DIR)
        )
        if "SUCCESS" in result.stdout:
            return True
        else:
            print(f"Chatterbox error: {result.stderr[:500]}")
            return False
    except subprocess.TimeoutExpired:
        print("Chatterbox timed out")
        return False
    except Exception as e:
        print(f"TTS error: {e}")
        return False


if __name__ == "__main__":
    # Quick test
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("text", help="Text to speak")
    parser.add_argument("-o", "--output", default="test.wav", help="Output file")
    parser.add_argument("-v", "--voice", help="Voice reference WAV")
    args = parser.parse_args()

    voice = Path(args.voice) if args.voice else None
    success = render_speech(args.text, Path(args.output), voice_ref=voice)
    print("Success!" if success else "Failed")
