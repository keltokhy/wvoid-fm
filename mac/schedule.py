#!/usr/bin/env python3
"""
WVOID-FM Weekly Scheduling

Loads `config/schedule.yaml` and resolves the currently-active show based on:
- day of week (mon..sun)
- local time (HH:MM)

The streamer can use this to:
- pick a music profile (energy/warmth/vibes)
- set talk frequency (segment_after_tracks)
- enable/disable podcasts per-show
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
import re
from typing import Any

import yaml


DAY_KEYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
DAY_TO_INDEX = {k: i for i, k in enumerate(DAY_KEYS)}
INDEX_TO_DAY = {i: k for k, i in DAY_TO_INDEX.items()}


class ScheduleError(RuntimeError):
    pass


def _parse_time_hhmm(value: str) -> int:
    if not isinstance(value, str):
        raise ScheduleError(f"Invalid time (expected HH:MM string): {value!r}")
    m = re.fullmatch(r"(\d{1,2}):(\d{2})", value.strip())
    if not m:
        raise ScheduleError(f"Invalid time (expected HH:MM): {value!r}")
    hour = int(m.group(1))
    minute = int(m.group(2))
    if hour < 0 or hour > 23 or minute < 0 or minute > 59:
        raise ScheduleError(f"Invalid time (out of range): {value!r}")
    return hour * 60 + minute


def _normalize_day_token(token: str) -> str:
    t = token.strip().lower()
    aliases = {
        "monday": "mon",
        "tuesday": "tue",
        "wednesday": "wed",
        "thursday": "thu",
        "friday": "fri",
        "saturday": "sat",
        "sunday": "sun",
    }
    return aliases.get(t, t)


def _parse_days(value: Any) -> set[int]:
    if value is None:
        raise ScheduleError("Missing required field: days")
    if not isinstance(value, list) or not value:
        raise ScheduleError(f"Invalid days (expected non-empty list): {value!r}")

    expanded: list[str] = []
    for raw in value:
        if not isinstance(raw, str):
            raise ScheduleError(f"Invalid day token: {raw!r}")
        tok = _normalize_day_token(raw)
        if tok in ("daily", "all"):
            expanded.extend(list(DAY_KEYS))
            continue
        if tok == "weekday":
            expanded.extend(["mon", "tue", "wed", "thu", "fri"])
            continue
        if tok == "weekend":
            expanded.extend(["sat", "sun"])
            continue
        expanded.append(tok)

    days: set[int] = set()
    for tok in expanded:
        if tok not in DAY_TO_INDEX:
            raise ScheduleError(f"Invalid day token: {tok!r}")
        days.add(DAY_TO_INDEX[tok])
    return days


def _expand_minutes(start_minute: int, end_minute: int) -> list[tuple[int, int]]:
    if start_minute == end_minute:
        raise ScheduleError("Schedule block start and end cannot be the same")
    if 0 <= start_minute < 1440 and 0 <= end_minute < 1440:
        if end_minute > start_minute:
            return [(start_minute, end_minute)]
        # Cross-midnight: split into two ranges
        return [(start_minute, 1440), (0, end_minute)]
    raise ScheduleError("Schedule block times out of range")


@dataclass(frozen=True)
class Show:
    show_id: str
    name: str
    description: str
    segment_after_tracks: int = 1
    podcasts_enabled: bool = True
    music: dict[str, Any] = field(default_factory=dict)
    voices: dict[str, str] = field(default_factory=dict)

    def stream_profile(self) -> dict[str, Any]:
        energy_range = self.music.get("energy_range")
        prefer_warmth = self.music.get("prefer_warmth")
        vibes = self.music.get("vibes")
        if (
            not isinstance(energy_range, list)
            or len(energy_range) != 2
            or not all(isinstance(x, (int, float)) for x in energy_range)
        ):
            raise ScheduleError(f"Show {self.show_id}: invalid music.energy_range")
        if not isinstance(prefer_warmth, (int, float)):
            raise ScheduleError(f"Show {self.show_id}: invalid music.prefer_warmth")
        if not isinstance(vibes, list) or not all(isinstance(v, str) for v in vibes):
            raise ScheduleError(f"Show {self.show_id}: invalid music.vibes")
        return {
            "name": self.name,
            "description": self.description,
            "energy_range": (float(energy_range[0]), float(energy_range[1])),
            "prefer_warmth": float(prefer_warmth),
            "vibes": [v.strip() for v in vibes if v.strip()],
        }


@dataclass(frozen=True)
class ScheduleBlock:
    start_minute: int
    end_minute: int
    show_id: str
    days: set[int] | None = None  # None => every day (base)

    def is_cross_midnight(self) -> bool:
        return self.end_minute < self.start_minute

    def matches(self, now: datetime) -> bool:
        minute = now.hour * 60 + now.minute
        day = now.weekday()  # mon=0
        prev_day = (day - 1) % 7

        if self.days is None:
            # Base clock: day-agnostic
            if self.end_minute > self.start_minute:
                return self.start_minute <= minute < self.end_minute
            return minute >= self.start_minute or minute < self.end_minute

        # Overrides: day-aware, including cross-midnight behavior.
        if self.end_minute > self.start_minute:
            return day in self.days and self.start_minute <= minute < self.end_minute

        # Cross-midnight: belongs to the start day; continues into next day.
        return (day in self.days and minute >= self.start_minute) or (
            prev_day in self.days and minute < self.end_minute
        )


@dataclass(frozen=True)
class ResolvedShow:
    show_id: str
    name: str
    description: str
    segment_after_tracks: int
    podcasts_enabled: bool
    podcast_hours: set[int]
    music_profile: dict[str, Any]
    voices: dict[str, str]


@dataclass
class StationSchedule:
    shows: dict[str, Show]
    base: list[ScheduleBlock]
    overrides: list[ScheduleBlock]
    podcast_hours: set[int]

    def validate(self) -> None:
        if not self.base:
            raise ScheduleError("schedule.base is empty")

        # Base coverage: every minute must be covered exactly once.
        coverage = [0] * 1440
        for block in self.base:
            for a, b in _expand_minutes(block.start_minute, block.end_minute):
                for m in range(a, b):
                    coverage[m] += 1

        uncovered = [i for i, c in enumerate(coverage) if c == 0]
        if uncovered:
            first = uncovered[0]
            raise ScheduleError(
                f"schedule.base does not cover the full day (first gap at {first // 60:02d}:{first % 60:02d})"
            )

        overlapped = [i for i, c in enumerate(coverage) if c > 1]
        if overlapped:
            first = overlapped[0]
            raise ScheduleError(
                f"schedule.base overlaps itself (first overlap at {first // 60:02d}:{first % 60:02d})"
            )

        # Show references exist
        for block in self.base + self.overrides:
            if block.show_id not in self.shows:
                raise ScheduleError(f"Schedule references unknown show: {block.show_id!r}")

        # Podcasts hours valid
        for h in self.podcast_hours:
            if h < 0 or h > 23:
                raise ScheduleError(f"podcasts.hours contains invalid hour: {h}")

        # Show config sanity
        for show in self.shows.values():
            if show.segment_after_tracks < 1:
                raise ScheduleError(f"Show {show.show_id}: segment_after_tracks must be >= 1")
            _ = show.stream_profile()  # validates music profile

    def resolve(self, now: datetime | None = None) -> ResolvedShow:
        now = now or datetime.now()

        for block in self.overrides:
            if block.matches(now):
                show = self.shows[block.show_id]
                return ResolvedShow(
                    show_id=show.show_id,
                    name=show.name,
                    description=show.description,
                    segment_after_tracks=show.segment_after_tracks,
                    podcasts_enabled=show.podcasts_enabled,
                    podcast_hours=set(self.podcast_hours),
                    music_profile=show.stream_profile(),
                    voices=dict(show.voices),
                )

        for block in self.base:
            if block.matches(now):
                show = self.shows[block.show_id]
                return ResolvedShow(
                    show_id=show.show_id,
                    name=show.name,
                    description=show.description,
                    segment_after_tracks=show.segment_after_tracks,
                    podcasts_enabled=show.podcasts_enabled,
                    podcast_hours=set(self.podcast_hours),
                    music_profile=show.stream_profile(),
                    voices=dict(show.voices),
                )

        raise ScheduleError("No matching schedule block for current time (base clock may be invalid)")


def load_schedule(path: Path) -> StationSchedule:
    try:
        payload = yaml.safe_load(path.read_text())
    except FileNotFoundError:
        raise
    except Exception as exc:
        raise ScheduleError(f"Failed to read schedule YAML: {exc}") from exc

    if not isinstance(payload, dict):
        raise ScheduleError("Schedule YAML must be a mapping at the top level")

    shows_raw = payload.get("shows")
    if not isinstance(shows_raw, dict) or not shows_raw:
        raise ScheduleError("Missing or invalid `shows` section")

    shows: dict[str, Show] = {}
    for show_id, cfg in shows_raw.items():
        if not isinstance(show_id, str) or not show_id.strip():
            raise ScheduleError(f"Invalid show id: {show_id!r}")
        if not isinstance(cfg, dict):
            raise ScheduleError(f"Show {show_id}: config must be a mapping")
        name = str(cfg.get("name", "")).strip()
        description = str(cfg.get("description", "")).strip()
        if not name or not description:
            raise ScheduleError(f"Show {show_id}: missing name/description")
        segment_after_tracks = int(cfg.get("segment_after_tracks", 1))
        podcasts_enabled = bool(cfg.get("podcasts_enabled", True))
        music = cfg.get("music") if isinstance(cfg.get("music"), dict) else {}
        voices = cfg.get("voices") if isinstance(cfg.get("voices"), dict) else {}
        shows[show_id] = Show(
            show_id=show_id,
            name=name,
            description=description,
            segment_after_tracks=segment_after_tracks,
            podcasts_enabled=podcasts_enabled,
            music=dict(music),
            voices={str(k): str(v) for k, v in voices.items()},
        )

    podcasts_cfg = payload.get("podcasts") if isinstance(payload.get("podcasts"), dict) else {}
    hours_raw = podcasts_cfg.get("hours", [])
    if hours_raw is None:
        hours_raw = []
    if not isinstance(hours_raw, list):
        raise ScheduleError("podcasts.hours must be a list of integers")
    podcast_hours: set[int] = set()
    for item in hours_raw:
        if not isinstance(item, int):
            raise ScheduleError(f"podcasts.hours contains non-int value: {item!r}")
        podcast_hours.add(item)

    sched = payload.get("schedule")
    if not isinstance(sched, dict):
        raise ScheduleError("Missing or invalid `schedule` section")

    base_raw = sched.get("base")
    if not isinstance(base_raw, list) or not base_raw:
        raise ScheduleError("schedule.base must be a non-empty list")

    overrides_raw = sched.get("overrides", [])
    if overrides_raw is None:
        overrides_raw = []
    if not isinstance(overrides_raw, list):
        raise ScheduleError("schedule.overrides must be a list")

    def _parse_block(cfg: Any, *, day_aware: bool) -> ScheduleBlock:
        if not isinstance(cfg, dict):
            raise ScheduleError(f"Schedule block must be a mapping: {cfg!r}")
        start = _parse_time_hhmm(str(cfg.get("start", "")))
        end = _parse_time_hhmm(str(cfg.get("end", "")))
        show_id = str(cfg.get("show", "")).strip()
        if not show_id:
            raise ScheduleError("Schedule block missing `show`")
        days = _parse_days(cfg.get("days")) if day_aware else None
        return ScheduleBlock(start_minute=start, end_minute=end, show_id=show_id, days=days)

    base_blocks = [_parse_block(item, day_aware=False) for item in base_raw]
    override_blocks = [_parse_block(item, day_aware=True) for item in overrides_raw]

    schedule = StationSchedule(
        shows=shows,
        base=base_blocks,
        overrides=override_blocks,
        podcast_hours=podcast_hours,
    )
    schedule.validate()
    return schedule


def _cli() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="WVOID-FM schedule tools")
    parser.add_argument(
        "--schedule",
        default=str(Path(__file__).resolve().parents[1] / "config" / "schedule.yaml"),
        help="Path to schedule.yaml",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("validate", help="Validate schedule file")

    p_now = sub.add_parser("now", help="Print current show")
    p_now.add_argument("--at", help="Override time (YYYY-MM-DD HH:MM)")

    args = parser.parse_args()

    schedule = load_schedule(Path(args.schedule).expanduser())
    if args.cmd == "validate":
        print("OK")
        return 0

    when = datetime.now()
    if args.cmd == "now" and args.at:
        try:
            when = datetime.strptime(args.at, "%Y-%m-%d %H:%M")
        except Exception as exc:
            raise ScheduleError(f"Invalid --at format: {exc}") from exc

    resolved = schedule.resolve(when)
    print(f"{INDEX_TO_DAY[when.weekday()]} {when:%H:%M} — {resolved.name} ({resolved.show_id})")
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())

