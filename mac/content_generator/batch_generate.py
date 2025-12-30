#!/usr/bin/env python3
"""
Batch generator for DJ segments.

Generates scripts and optionally renders them to audio.
Can run in parallel batches for high throughput.

Usage:
    uv run python batch_generate.py --scripts 20
    uv run python batch_generate.py --scripts 10 --tts
"""

import sys
import json
import random
import argparse
import subprocess
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent))

from script_generator import ScriptGenerator, get_time_of_day

# Output directories
SCRIPTS_DIR = Path(__file__).parent.parent.parent / "output" / "scripts"
SEGMENTS_DIR = Path(__file__).parent.parent.parent / "output" / "segments"


def generate_scripts(count: int, output_dir: Path) -> list[Path]:
    """Generate DJ scripts without TTS."""
    output_dir.mkdir(parents=True, exist_ok=True)

    gen = ScriptGenerator()
    if not gen.is_available():
        print("LM Studio not available!")
        return []

    print(f"Using model: {gen._get_model()}")

    segment_types = [
        ("station_id", 30),
        ("hour_marker", 20),
        ("song_intro", 35),
        ("dedication", 10),
        ("weather", 5),
    ]

    outputs = []
    for i in range(count):
        # Weighted random selection
        seg_type = random.choices(
            [t for t, _ in segment_types],
            weights=[w for _, w in segment_types],
        )[0]

        time_of_day = get_time_of_day()
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        print(f"[{i+1}/{count}] Generating {seg_type}...", end=" ", flush=True)

        try:
            if seg_type == "station_id":
                script = gen.generate_station_id(time_of_day)
            elif seg_type == "hour_marker":
                script = gen.generate_hour_marker(time_of_day)
            elif seg_type == "song_intro":
                script = gen.generate_song_intro(time_of_day=time_of_day)
            elif seg_type == "dedication":
                script = gen.generate_dedication(time_of_day=time_of_day)
            elif seg_type == "weather":
                script = gen.generate_weather(time_of_day)
            else:
                continue

            if not script.strip():
                print("empty response, skipping")
                continue

            # Save script
            filename = f"{seg_type}_{timestamp}_{i:03d}.json"
            output_path = output_dir / filename

            data = {
                "type": seg_type,
                "time_of_day": time_of_day,
                "generated_at": datetime.now().isoformat(),
                "script": script,
            }

            with open(output_path, "w") as f:
                json.dump(data, f, indent=2)

            print(f"OK ({len(script)} chars)")
            print(f"    \"{script[:80]}{'...' if len(script) > 80 else ''}\"")
            outputs.append(output_path)

        except Exception as e:
            print(f"error: {e}")
            continue

    return outputs


def render_with_say(script_paths: list[Path], output_dir: Path) -> list[Path]:
    """Render scripts using macOS 'say' command (fallback TTS)."""
    output_dir.mkdir(parents=True, exist_ok=True)
    outputs = []

    for script_path in script_paths:
        with open(script_path) as f:
            data = json.load(f)

        script = data["script"]
        seg_type = data["type"]

        # Preprocess for say
        processed = script.replace("[pause]", "... ").replace("[chuckle]", "heh... ")
        processed = processed.replace("[cough]", "ahem... ")

        timestamp = datetime.now().strftime("%H%M%S")
        output_path = output_dir / f"{seg_type}_{timestamp}.aiff"

        print(f"Rendering: {script_path.name}...", end=" ", flush=True)

        try:
            subprocess.run(
                ["say", "-v", "Samantha", "-o", str(output_path), processed],
                check=True, timeout=60
            )
            print("OK")
            outputs.append(output_path)
        except Exception as e:
            print(f"error: {e}")

    return outputs


def main():
    parser = argparse.ArgumentParser(description="Batch generate DJ segments")
    parser.add_argument("--scripts", type=int, default=10, help="Number of scripts to generate")
    parser.add_argument("--tts", action="store_true", help="Render scripts with macOS say")

    args = parser.parse_args()

    print(f"=== WVOID-FM Batch Generator ===")
    print(f"Generating {args.scripts} DJ scripts...\n")

    # Generate scripts
    script_paths = generate_scripts(args.scripts, SCRIPTS_DIR)
    print(f"\nGenerated {len(script_paths)} scripts")

    # Optional TTS
    if args.tts and script_paths:
        print(f"\nRendering with macOS TTS...")
        audio_paths = render_with_say(script_paths, SEGMENTS_DIR)
        print(f"Rendered {len(audio_paths)} audio files")


if __name__ == "__main__":
    main()
