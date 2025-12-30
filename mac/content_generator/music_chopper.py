#!/usr/bin/env python3
"""
Music Chopper for WVOID-FM

Chops long album files into radio-friendly segments (2-5 minutes each).
Extracts random or sequential segments from full albums.

Usage:
    uv run python music_chopper.py --source /path/to/album.mp3 --count 3
    uv run python music_chopper.py --source-dir /path/to/music --count 10
"""

import sys
import random
import argparse
import subprocess
from pathlib import Path
from datetime import datetime

# Output directory for chopped segments
OUTPUT_DIR = Path(__file__).parent.parent.parent / "output" / "chopped_music"

def get_duration(filepath: Path) -> float:
    """Get audio file duration in seconds."""
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(filepath)],
            capture_output=True, text=True, timeout=30
        )
        return float(result.stdout.strip())
    except Exception:
        return 0.0


def chop_segment(
    source: Path,
    output: Path,
    start_seconds: float,
    duration_seconds: float
) -> bool:
    """Extract a segment from an audio file."""
    try:
        cmd = [
            "ffmpeg", "-y",
            "-ss", str(start_seconds),
            "-i", str(source),
            "-t", str(duration_seconds),
            "-acodec", "libmp3lame",
            "-b:a", "192k",
            "-ar", "44100",
            "-ac", "2",
            str(output)
        ]
        result = subprocess.run(cmd, capture_output=True, timeout=120)
        return result.returncode == 0
    except Exception as e:
        print(f"Error chopping: {e}")
        return False


def generate_segment_name(source: Path, index: int) -> str:
    """Generate a clean filename for a segment."""
    # Clean up the source filename
    stem = source.stem
    # Remove common YouTube suffixes
    for suffix in ["(Official Video)", "(Official Audio)", "(FULL ALBUM)",
                   "[Official Video]", "[Full Album]", "(Official HD Video)",
                   "(Official Music Video)", "FULL ALBUM"]:
        stem = stem.replace(suffix, "").strip()

    # Limit length
    if len(stem) > 60:
        stem = stem[:60]

    timestamp = datetime.now().strftime("%H%M")
    return f"{stem}_seg{index}_{timestamp}.mp3"


def chop_album(source: Path, count: int = 3, min_len: int = 120, max_len: int = 300) -> list[Path]:
    """Chop an album into multiple random segments.

    Args:
        source: Path to album file
        count: Number of segments to extract
        min_len: Minimum segment length in seconds (default 2 min)
        max_len: Maximum segment length in seconds (default 5 min)

    Returns:
        List of output file paths
    """
    duration = get_duration(source)
    if duration < min_len:
        print(f"Source too short ({duration:.0f}s < {min_len}s): {source.name}")
        return []

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    outputs = []

    # Calculate available range
    available = duration - max_len
    if available < 0:
        available = 0
        max_len = int(duration * 0.8)  # Take 80% max of short files

    for i in range(count):
        # Random start point
        start = random.uniform(30, max(31, available))  # Skip first 30s (often intros)
        seg_duration = random.uniform(min_len, max_len)

        # Don't go past end
        if start + seg_duration > duration - 10:
            seg_duration = duration - start - 10
            if seg_duration < min_len:
                continue

        output_name = generate_segment_name(source, i + 1)
        output_path = OUTPUT_DIR / output_name

        print(f"Chopping: {source.name} @ {start:.0f}s for {seg_duration:.0f}s")
        if chop_segment(source, output_path, start, seg_duration):
            print(f"  -> {output_name}")
            outputs.append(output_path)

    return outputs


def find_albums(source_dir: Path) -> list[Path]:
    """Find all audio files in a directory."""
    extensions = {".mp3", ".flac", ".m4a", ".wav", ".ogg"}
    albums = []

    for ext in extensions:
        albums.extend(source_dir.rglob(f"*{ext}"))

    # Filter to files > 5 minutes (likely albums or long tracks)
    long_tracks = []
    for path in albums:
        duration = get_duration(path)
        if duration > 300:  # 5 minutes
            long_tracks.append(path)
            print(f"Found: {path.name} ({duration/60:.1f} min)")

    return long_tracks


def main():
    parser = argparse.ArgumentParser(description="Chop albums into radio segments")
    parser.add_argument("--source", type=Path, help="Source album file")
    parser.add_argument("--source-dir", type=Path, help="Directory of album files")
    parser.add_argument("--count", type=int, default=3, help="Segments per album")
    parser.add_argument("--min-len", type=int, default=120, help="Min segment length (seconds)")
    parser.add_argument("--max-len", type=int, default=300, help="Max segment length (seconds)")

    args = parser.parse_args()

    outputs = []

    if args.source:
        if not args.source.exists():
            print(f"Source not found: {args.source}")
            sys.exit(1)
        outputs = chop_album(args.source, args.count, args.min_len, args.max_len)

    elif args.source_dir:
        if not args.source_dir.exists():
            print(f"Directory not found: {args.source_dir}")
            sys.exit(1)

        albums = find_albums(args.source_dir)
        for album in albums:
            outputs.extend(chop_album(album, args.count, args.min_len, args.max_len))

    else:
        parser.print_help()
        sys.exit(1)

    print(f"\nChopped {len(outputs)} segments total")


if __name__ == "__main__":
    main()
