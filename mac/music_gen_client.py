#!/usr/bin/env python3
"""REST client for music-gen.server (ACE-Step music generation).

API: POST /generate → base64-encoded audio
Server: github.com/kortexa-ai/music-gen.server (default: localhost:4009)
"""

import base64
import json
import os
import urllib.error
import urllib.request
from pathlib import Path

MUSIC_GEN_BASE_URL = os.environ.get("MUSIC_GEN_URL", "http://localhost:4009")


def is_server_available(base_url: str = MUSIC_GEN_BASE_URL, timeout: float = 2.0) -> bool:
    """Check if music-gen.server is reachable."""
    try:
        with urllib.request.urlopen(f"{base_url}/health", timeout=timeout):
            return True
    except Exception:
        return False


def generate_music(
    caption: str,
    output_path: Path,
    duration: float = 90.0,
    audio_format: str = "flac",
    seed: int = -1,
    instrumental: bool = True,
    lyrics: str = "[Instrumental]",
    base_url: str = MUSIC_GEN_BASE_URL,
    timeout: float = 600.0,
) -> bool:
    """Generate music via ACE-Step and save to output_path.

    Args:
        caption: Text description of the music style/mood.
        output_path: Where to save the generated audio file.
        duration: Length in seconds (10-600).
        audio_format: Output format (flac, mp3, wav, opus, aac).
        seed: Random seed (-1 for random).
        instrumental: If True, generate instrumental only.
        lyrics: Lyrics text (used when instrumental=False).
        base_url: music-gen.server base URL.
        timeout: HTTP request timeout in seconds (generation can be slow).

    Returns:
        True if successful, False otherwise.
    """
    payload = json.dumps({
        "caption": caption,
        "instrumental": instrumental,
        "lyrics": lyrics,
        "duration": duration,
        "audio_format": audio_format,
        "seed": seed,
        "inference_steps": 8,
        "guidance_scale": 7.0,
        "thinking": True,
    }).encode()

    req = urllib.request.Request(
        f"{base_url}/generate",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        print(f"[music_gen] HTTP {e.code}: {e.read().decode()[:200]}")
        return False
    except Exception as e:
        print(f"[music_gen] Request failed: {e}")
        return False

    audios = data.get("audios", [])
    if not audios:
        print("[music_gen] No audio in response")
        return False

    try:
        audio_bytes = base64.b64decode(audios[0])
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(audio_bytes)
        return True
    except Exception as e:
        print(f"[music_gen] Failed to save audio: {e}")
        return False
