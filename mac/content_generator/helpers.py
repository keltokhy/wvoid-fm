#!/usr/bin/env python3
"""
Shared helpers for WVOID-FM content generators.
"""

from __future__ import annotations

import subprocess
from datetime import datetime
from pathlib import Path

VOICE_REF_EXTENSIONS = (".wav", ".m4a", ".mp3")


def log(msg: str) -> None:
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def get_time_of_day(hour: int | None = None, profile: str = "default") -> str:
    if hour is None:
        hour = datetime.now().hour

    if profile == "extended":
        if 6 <= hour < 10:
            return "morning"
        if 10 <= hour < 14:
            return "daytime"
        if 14 <= hour < 15:
            return "early_afternoon"
        if 15 <= hour < 18:
            return "afternoon"
        if 18 <= hour < 24:
            return "evening"
        return "late_night"

    if 6 <= hour < 10:
        return "morning"
    if 10 <= hour < 18:
        return "daytime"
    if 18 <= hour < 24:
        return "evening"
    return "late_night"


def preprocess_for_tts(text: str, *, include_cough: bool = True) -> str:
    text = text.replace("[pause]", "...")
    text = text.replace("[chuckle]", "heh...")
    if include_cough:
        text = text.replace("[cough]", "ahem...")
    text = text.replace('"', "")
    return text.strip()


def clean_claude_output(text: str, *, strip_quotes: bool = True) -> str:
    cleaned = text.replace("*", "").replace("_", "").strip()
    if strip_quotes and cleaned.startswith('"') and cleaned.endswith('"'):
        cleaned = cleaned[1:-1].strip()
    return cleaned


def run_claude(
    prompt: str,
    *,
    timeout: int = 60,
    model: str | None = None,
    min_length: int = 0,
    strip_quotes: bool = True,
) -> str | None:
    args = ["claude", "-p", prompt]
    if model:
        args.extend(["--model", model])

    try:
        result = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        log("Claude timed out")
        return None
    except Exception as exc:
        log(f"Claude error: {exc}")
        return None

    if result.returncode != 0 or not result.stdout.strip():
        return None

    script = clean_claude_output(result.stdout, strip_quotes=strip_quotes)
    if len(script) <= min_length:
        return None
    return script


def find_voice_reference(voice_dir: Path, preferred: Path | None = None) -> Path | None:
    if preferred:
        return preferred

    for ext in VOICE_REF_EXTENSIONS:
        candidates = list(voice_dir.glob(f"*{ext}"))
        if candidates:
            return candidates[0]

    return None
