#!/usr/bin/env python3
"""
Shared helpers for WRIT-FM content generators.
"""

from __future__ import annotations

import os
import re
import subprocess
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path

DEFAULT_NEWS_FEEDS = (
    "https://feeds.bbci.co.uk/news/rss.xml",
    "https://feeds.npr.org/1001/rss.xml",
)
NEWS_CACHE_TTL_SECONDS = int(os.environ.get("WRIT_NEWS_CACHE_TTL", "600"))
NEWS_TIMEOUT_SECONDS = int(os.environ.get("WRIT_NEWS_TIMEOUT", "6"))

_NEWS_CACHE: dict[str, object] = {"timestamp": 0.0, "items": []}


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


def _strip_namespace(tag: str) -> str:
    if "}" in tag:
        return tag.split("}", 1)[1]
    return tag


def _find_child_text(elem: ET.Element, name: str) -> str:
    for child in elem:
        if _strip_namespace(child.tag) == name and child.text:
            return child.text.strip()
    return ""


def _extract_source_title(root: ET.Element, fallback: str) -> str:
    tag = _strip_namespace(root.tag)
    if tag == "rss":
        for child in root:
            if _strip_namespace(child.tag) == "channel":
                title = _find_child_text(child, "title")
                return title or fallback
    if tag == "feed":
        title = _find_child_text(root, "title")
        return title or fallback
    return fallback


def _normalize_title(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", title.lower()).strip()


def fetch_headlines(max_items: int | None = None) -> list[dict]:
    now = time.time()
    cached_items = _NEWS_CACHE.get("items", [])
    if cached_items and now - float(_NEWS_CACHE.get("timestamp", 0.0)) < NEWS_CACHE_TTL_SECONDS:
        return list(cached_items)

    max_items = max_items or int(os.environ.get("WRIT_NEWS_MAX_ITEMS", "8"))
    feed_env = os.environ.get("WRIT_NEWS_FEEDS")
    feeds = [f.strip() for f in feed_env.split(",")] if feed_env else list(DEFAULT_NEWS_FEEDS)
    feeds = [f for f in feeds if f]

    headlines: list[dict] = []
    seen: set[str] = set()

    for feed_url in feeds:
        try:
            with urllib.request.urlopen(feed_url, timeout=NEWS_TIMEOUT_SECONDS) as response:
                content = response.read()
            root = ET.fromstring(content)
        except Exception:
            continue

        fallback = urllib.parse.urlparse(feed_url).netloc or "Unknown Source"
        source = _extract_source_title(root, fallback)

        for elem in root.iter():
            tag = _strip_namespace(elem.tag)
            if tag not in ("item", "entry"):
                continue
            title = _find_child_text(elem, "title")
            if not title:
                continue
            norm = _normalize_title(title)
            if not norm or norm in seen:
                continue
            seen.add(norm)
            headlines.append({"title": title, "source": source})
            if len(headlines) >= max_items:
                break
        if len(headlines) >= max_items:
            break

    _NEWS_CACHE["timestamp"] = now
    _NEWS_CACHE["items"] = list(headlines)
    return headlines


def format_headlines(headlines: list[dict], max_items: int | None = None) -> str:
    if not headlines:
        return ""
    max_items = max_items or len(headlines)
    lines = []
    for item in headlines[:max_items]:
        title = item.get("title", "").strip()
        source = item.get("source", "").strip() or "Source"
        if title:
            lines.append(f"- [{source}] {title}")
    return "\n".join(lines)


# =============================================================================
# SHARED TTS RENDERING
# =============================================================================

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_KOKORO_DIR = _PROJECT_ROOT / "mac" / "kokoro"
_KOKORO_PYTHON = _KOKORO_DIR / ".venv" / "bin" / "python"


def get_audio_duration(filepath: Path) -> float | None:
    """Get audio duration in seconds via ffprobe."""
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
             "-of", "csv=p=0", str(filepath)],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0 and result.stdout.strip():
            return float(result.stdout.strip())
    except Exception:
        pass
    return None


def render_kokoro(text: str, output_path: Path, voice: str = "am_michael") -> bool:
    """Render text to speech using Kokoro TTS."""
    if not _KOKORO_PYTHON.exists():
        log("Kokoro venv not found")
        return False

    escaped_text = text.replace('\\', '\\\\').replace('"', '\\"').replace('\n', ' ')

    tts_script = f'''
import warnings
warnings.filterwarnings("ignore")

from kokoro import KPipeline
import soundfile as sf
import numpy as np

pipe = KPipeline(lang_code="a", repo_id="hexgrad/Kokoro-82M")

text = "{escaped_text}"
voice = "{voice}"

generator = pipe(text, voice=voice, speed=1.0)
audio_segments = []
for _, _, audio in generator:
    audio_segments.append(audio)

if len(audio_segments) == 1:
    full_audio = audio_segments[0]
else:
    full_audio = np.concatenate(audio_segments)

sf.write("{output_path}", full_audio, 24000)
print("SUCCESS")
'''

    try:
        result = subprocess.run(
            [str(_KOKORO_PYTHON), "-c", tts_script],
            capture_output=True,
            text=True,
            timeout=300,
            cwd=str(_KOKORO_DIR),
        )
        return "SUCCESS" in result.stdout
    except Exception as e:
        log(f"Kokoro error: {e}")
        return False


def concatenate_audio(chunk_files: list[Path], output_path: Path, gap_seconds: float = 0) -> bool:
    """Concatenate WAV files, optionally with silence gaps between them."""
    if len(chunk_files) == 1:
        chunk_files[0].rename(output_path)
        return True

    list_file = output_path.with_suffix('.concat.txt')

    try:
        with open(list_file, 'w') as f:
            for cf in chunk_files:
                f.write(f"file '{cf}'\n")

        cmd = [
            "ffmpeg", "-y", "-f", "concat", "-safe", "0",
            "-i", str(list_file),
            "-ar", "24000", "-ac", "1",
            str(output_path)
        ]

        result = subprocess.run(cmd, capture_output=True, timeout=120)

        list_file.unlink(missing_ok=True)
        for cf in chunk_files:
            cf.unlink(missing_ok=True)

        if result.returncode != 0:
            stderr = result.stderr.decode()
            stdout = result.stdout.decode()
            log(f"  Concat failed (rc={result.returncode}):")
            log(f"  STDERR (last 1500): {stderr[-1500:]}")
            if stdout.strip():
                log(f"  STDOUT: {stdout[-500:]}")
            return False

        return output_path.exists()

    except Exception as e:
        log(f"  Concat error: {e}")
        list_file.unlink(missing_ok=True)
        return False


def render_single_voice(text: str, output_path: Path, voice: str) -> bool:
    """Render a single-voice script to audio, chunking for long content."""
    MAX_CHUNK_WORDS = 100
    words = text.split()

    if len(words) <= MAX_CHUNK_WORDS:
        return render_kokoro(text, output_path, voice)

    sentences = re.split(r'(?<=[.!?])\s+', text)

    chunks: list[str] = []
    current_chunk: list[str] = []
    current_words = 0

    for sentence in sentences:
        sentence_words = len(sentence.split())
        if current_words + sentence_words > MAX_CHUNK_WORDS and current_chunk:
            chunks.append(' '.join(current_chunk))
            current_chunk = [sentence]
            current_words = sentence_words
        else:
            current_chunk.append(sentence)
            current_words += sentence_words

    if current_chunk:
        chunks.append(' '.join(current_chunk))

    log(f"  Rendering {len(chunks)} chunks with voice {voice}...")

    # Use a temp directory for chunks so the streamer doesn't consume them
    import tempfile
    tmp_dir = Path(tempfile.mkdtemp(prefix="writ_chunks_"))

    chunk_files: list[Path] = []
    failed_chunks = 0
    for i, chunk in enumerate(chunks):
        chunk_path = tmp_dir / f"chunk{i:03d}.wav"
        for attempt in range(2):
            if render_kokoro(chunk, chunk_path, voice):
                chunk_files.append(chunk_path)
                break
            time.sleep(2)
        else:
            failed_chunks += 1

    if failed_chunks:
        log(f"  {failed_chunks}/{len(chunks)} chunks failed to render")

    if not chunk_files:
        log("  No chunks rendered")
        tmp_dir.rmdir()
        return False

    result = concatenate_audio(chunk_files, output_path)
    # Clean up temp directory
    import shutil
    shutil.rmtree(tmp_dir, ignore_errors=True)
    return result
