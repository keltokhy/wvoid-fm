#!/usr/bin/env python3
"""
ezstream playlist intake program for WRIT-FM.

Reads output/.playlist.m3u (managed by feeder.py) and returns one filename
per invocation, advancing through the list. Tracks position by reading
the previous track from output/.current_track.txt.

Side effects:
- Writes the returned filename to .current_track.txt. That file is the
  shared source of truth — stream_metadata.sh reads it to compose the
  Icecast metadata, feeder.py reads it to populate the now-playing API.
- Archives the previous track to {slot}/aired/ if it lived in a slot
  folder (matching YYYY-MM-DD_HHMM). That's how the station enforces
  "never plays again within the same slot" across crashes/restarts.

ezstream calls this script per track. End-of-playlist behaviour: wraps
to the first track in the current playlist, since the playlist file is
constantly rebuilt by feeder.py for whatever show is airing.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PLAYLIST_PATH = PROJECT_ROOT / "output" / ".playlist.m3u"
CURRENT_TRACK_FILE = PROJECT_ROOT / "output" / ".current_track.txt"
SLOT_RE = re.compile(r"^\d{4}-\d{2}-\d{2}_\d{4}$")


def read_playlist() -> list[str]:
    if not PLAYLIST_PATH.exists():
        return []
    return [
        line.strip()
        for line in PLAYLIST_PATH.read_text().splitlines()
        if line.strip() and not line.startswith("#")
    ]


def read_previous() -> str:
    try:
        if CURRENT_TRACK_FILE.exists():
            return CURRENT_TRACK_FILE.read_text().strip()
    except OSError:
        pass
    return ""


def archive_if_slot_track(prev: str) -> None:
    if not prev:
        return
    p = Path(prev)
    if not p.is_absolute() or not p.exists():
        return
    if not SLOT_RE.match(p.parent.name):
        return
    aired = p.parent / "aired"
    try:
        aired.mkdir(exist_ok=True)
        p.rename(aired / p.name)
    except OSError:
        pass


def write_current(track: str) -> None:
    try:
        tmp = CURRENT_TRACK_FILE.with_suffix(".tmp")
        tmp.write_text(track)
        tmp.replace(CURRENT_TRACK_FILE)
    except OSError:
        pass


def main() -> int:
    tracks = read_playlist()
    if not tracks:
        # Empty playlist — return nothing so ezstream knows the playlist is
        # exhausted; feeder.py will rebuild and we'll be called again.
        return 0

    prev = read_previous()
    archive_if_slot_track(prev)

    if prev in tracks:
        next_idx = tracks.index(prev) + 1
    else:
        next_idx = 0
    if next_idx >= len(tracks):
        next_idx = 0

    next_track = tracks[next_idx]
    write_current(next_track)
    sys.stdout.write(next_track + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
