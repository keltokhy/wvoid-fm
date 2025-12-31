#!/usr/bin/env python3
"""
WVOID-FM Unified TTS Module

Provides a common interface for TTS with multiple backends:
- chatterbox: Voice cloning, slower, uses reference audio
- kokoro: Fast preset voices, no cloning, good for parallel generation

Usage:
    from tts import render_speech

    # Default (chatterbox with voice cloning)
    render_speech("Hello", Path("out.wav"), voice_ref=Path("ref.wav"))

    # Kokoro (fast, preset voices)
    render_speech("Hello", Path("out.wav"), backend="kokoro", voice="am_michael")

Environment:
    WVOID_TTS_BACKEND: "chatterbox" (default) or "kokoro"
"""

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CHATTERBOX_DIR = PROJECT_ROOT / "mac" / "chatterbox"
KOKORO_DIR = PROJECT_ROOT / "mac" / "kokoro"

# Default backend from environment or chatterbox
DEFAULT_BACKEND = os.environ.get("WVOID_TTS_BACKEND", "chatterbox")


def render_speech(
    text: str,
    output_path: Path,
    voice_ref: Path | None = None,
    backend: str | None = None,
    # Chatterbox params
    exaggeration: float = 0.5,
    cfg_weight: float = 0.5,
    temperature: float = 0.8,
    # Kokoro params
    voice: str = "am_michael",
    speed: float = 1.0,
) -> bool:
    """
    Render text to speech using the specified backend.

    Args:
        text: The text to speak
        output_path: Where to save the WAV file
        voice_ref: Voice reference for cloning (chatterbox only)
        backend: "chatterbox" or "kokoro" (default from env or chatterbox)
        exaggeration: Chatterbox voice exaggeration
        cfg_weight: Chatterbox CFG weight
        temperature: Chatterbox generation temperature
        voice: Kokoro voice ID
        speed: Kokoro speed multiplier

    Returns:
        True if successful, False otherwise
    """
    backend = backend or DEFAULT_BACKEND

    if backend == "kokoro":
        # Add kokoro to path and import
        if str(KOKORO_DIR) not in sys.path:
            sys.path.insert(0, str(KOKORO_DIR))

        from tts import render_speech as kokoro_render
        return kokoro_render(text, output_path, voice=voice, speed=speed)

    else:  # chatterbox (default)
        # Add chatterbox to path and import
        if str(CHATTERBOX_DIR) not in sys.path:
            sys.path.insert(0, str(CHATTERBOX_DIR))

        from tts import render_speech as chatterbox_render
        return chatterbox_render(
            text,
            output_path,
            voice_ref=voice_ref,
            exaggeration=exaggeration,
            cfg_weight=cfg_weight,
            temperature=temperature,
        )


# Kokoro voice options for reference
KOKORO_VOICES = {
    # American Male (good for The Operator)
    "am_michael": "Warm baritone",
    "am_fenrir": "Deep voice",
    "am_onyx": "Deep voice",
    "am_adam": "Standard male",
    # American Female
    "af_heart": "Warm, expressive",
    "af_bella": "Standard female",
    # British voices
    "bm_daniel": "British male",
    "bf_emma": "British female",
}


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="WVOID TTS")
    parser.add_argument("text", help="Text to speak")
    parser.add_argument("-o", "--output", default="test.wav", help="Output file")
    parser.add_argument("-b", "--backend", default=DEFAULT_BACKEND, choices=["chatterbox", "kokoro"])
    parser.add_argument("-v", "--voice", help="Voice reference (chatterbox) or voice ID (kokoro)")
    parser.add_argument("-s", "--speed", type=float, default=1.0, help="Speed (kokoro only)")
    args = parser.parse_args()

    voice_ref = Path(args.voice) if args.voice and args.backend == "chatterbox" else None
    voice_id = args.voice if args.voice and args.backend == "kokoro" else "am_michael"

    success = render_speech(
        args.text,
        Path(args.output),
        voice_ref=voice_ref,
        backend=args.backend,
        voice=voice_id,
        speed=args.speed,
    )
    print("Success!" if success else "Failed")
