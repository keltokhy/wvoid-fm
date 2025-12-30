#!/usr/bin/env python3
"""
Segment Generator for WVOID-FM

Generates DJ segments by:
1. Using LLM to write scripts
2. Using TTS to render them to audio

Usage:
    uv run python generate_segments.py --count 10
    uv run python generate_segments.py --type station_id --count 5
    uv run python generate_segments.py
"""

import argparse
import random
from datetime import datetime
from pathlib import Path

from script_generator import ScriptGenerator, get_time_of_day
from tts_renderer import TTSRenderer


# Output directory for generated segments
OUTPUT_DIR = Path(__file__).parent.parent.parent / "output" / "segments"


def generate_segment(
    generator: ScriptGenerator,
    renderer: TTSRenderer,
    segment_type: str = "random",
    prev_track: dict | None = None,
    next_track: dict | None = None,
) -> Path | None:
    """
    Generate a single DJ segment.

    Args:
        generator: Script generator
        renderer: TTS renderer
        segment_type: Type of segment (song_intro, hour_marker, station_id, etc.)
        prev_track: Previous track metadata
        next_track: Next track metadata

    Returns:
        Path to generated audio file, or None on failure
    """
    time_of_day = get_time_of_day()

    # Pick random type if requested
    if segment_type == "random":
        weights = [
            ("song_intro", 40),
            ("station_id", 30),
            ("hour_marker", 15),
            ("dedication", 10),
            ("weather", 5),
        ]
        segment_type = random.choices(
            [t for t, _ in weights],
            weights=[w for _, w in weights],
        )[0]

    print(f"Generating {segment_type}...")

    # Generate script
    try:
        if segment_type == "song_intro":
            script = generator.generate_song_intro(prev_track, next_track, time_of_day)
        elif segment_type == "hour_marker":
            script = generator.generate_hour_marker(time_of_day)
        elif segment_type == "station_id":
            script = generator.generate_station_id(time_of_day)
        elif segment_type == "dedication":
            script = generator.generate_dedication(next_track, time_of_day)
        elif segment_type == "weather":
            script = generator.generate_weather(time_of_day)
        else:
            print(f"Unknown segment type: {segment_type}")
            return None
    except Exception as e:
        print(f"Script generation failed: {e}")
        return None

    print(f"Script: {script[:100]}...")

    # Render to audio
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{segment_type}_{timestamp}.wav"
    output_path = OUTPUT_DIR / filename

    try:
        renderer.render(script, output_path)
    except Exception as e:
        print(f"TTS rendering failed: {e}")
        return None

    return output_path


def main():
    parser = argparse.ArgumentParser(description="Generate WVOID-FM DJ segments")
    parser.add_argument("--count", "-n", type=int, default=1, help="Number of segments to generate")
    parser.add_argument("--type", "-t", default="random", help="Segment type (song_intro, station_id, hour_marker, dedication, weather, random)")
    parser.add_argument("--voice", "-v", type=Path, help="Path to voice reference audio")

    args = parser.parse_args()

    # Ensure output directory exists
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Initialize generator and renderer
    generator = ScriptGenerator()

    if not generator.is_available():
        print("LM Studio not available. Start it and load a model first.")
        print("(Or set LM_STUDIO_URL environment variable)")
        return

    voice_ref = args.voice or Path(__file__).parent.parent / "voice_reference" / "operator_voice.wav"
    renderer = TTSRenderer(voice_reference=voice_ref if voice_ref.exists() else None)

    # Generate segments
    generated = []
    for i in range(args.count):
        print(f"\n=== Generating segment {i+1}/{args.count} ===")
        path = generate_segment(generator, renderer, args.type)
        if path:
            generated.append(path)

    print(f"\n=== Generated {len(generated)}/{args.count} segments ===")
    for p in generated:
        print(f"  {p}")

if __name__ == "__main__":
    main()
