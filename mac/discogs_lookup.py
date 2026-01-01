#!/usr/bin/env python3
"""
Discogs lookup module for WVOID-FM.

Searches Discogs for track info and generates QR codes linking to release pages.
Uses caching to respect rate limits (60/min authenticated).

AUTHENTICATION REQUIRED:
The Discogs search API requires authentication. You need to:
1. Create a Discogs account at https://www.discogs.com/
2. Go to https://www.discogs.com/settings/developers
3. Generate a personal access token
4. Set the DISCOGS_TOKEN environment variable

Alternatively, create a Discogs Application to get a key/secret pair:
- Set DISCOGS_KEY and DISCOGS_SECRET environment variables

Rate limits: 60 requests/minute with authentication.
"""

import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

# Rate limiting: 60 authenticated requests per minute
# We'll cache aggressively and be conservative
CACHE_TTL_SECONDS = 3600  # Cache hits for 1 hour
CACHE_FILE = Path.home() / ".wvoid" / "discogs_cache.json"
REQUEST_DELAY = 2.5  # Seconds between requests (conservative)

# Discogs API credentials - REQUIRED for search endpoint
DISCOGS_TOKEN = os.environ.get("DISCOGS_TOKEN")
DISCOGS_KEY = os.environ.get("DISCOGS_KEY")
DISCOGS_SECRET = os.environ.get("DISCOGS_SECRET")
DISCOGS_USER_AGENT = "WVOID-FM/1.0 +https://radio.khaledeltokhy.com"

# Check if we have valid credentials
HAS_CREDENTIALS = bool(DISCOGS_TOKEN or (DISCOGS_KEY and DISCOGS_SECRET))

_last_request_time = 0.0
_cache: dict = {}
_cache_loaded = False


@dataclass
class DiscogsResult:
    """Result from a Discogs search."""
    release_id: int
    title: str
    artist: str
    year: Optional[int]
    url: str
    thumb_url: Optional[str] = None
    label: Optional[str] = None
    format: Optional[str] = None


def _load_cache() -> dict:
    """Load cache from disk."""
    global _cache, _cache_loaded
    if _cache_loaded:
        return _cache

    try:
        if CACHE_FILE.exists():
            with open(CACHE_FILE) as f:
                _cache = json.load(f)
    except Exception:
        _cache = {}

    _cache_loaded = True
    return _cache


def _save_cache() -> None:
    """Save cache to disk."""
    try:
        CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(CACHE_FILE, "w") as f:
            json.dump(_cache, f)
    except Exception:
        pass


def _clean_track_name(name: str) -> tuple[str, str]:
    """Extract artist and title from track name.

    Common patterns:
    - "Artist - Title"
    - "01 - Title" (just track number)
    - "Title (Artist)"
    - "Title"

    Returns (artist, title) tuple. Artist may be empty.
    """
    name = name.strip()

    # Remove track numbers like "01 - ", "1. ", etc.
    name = re.sub(r"^\d+[\s\-\.]+", "", name)

    # Try "Artist - Title" pattern
    if " - " in name:
        parts = name.split(" - ", 1)
        if len(parts) == 2:
            return parts[0].strip(), parts[1].strip()

    # Try "Title (Artist)" pattern
    match = re.match(r"(.+?)\s*\(([^)]+)\)\s*$", name)
    if match:
        return match.group(2).strip(), match.group(1).strip()

    # Just the title
    return "", name


def _rate_limit() -> None:
    """Enforce rate limiting."""
    global _last_request_time
    now = time.time()
    elapsed = now - _last_request_time
    if elapsed < REQUEST_DELAY:
        time.sleep(REQUEST_DELAY - elapsed)
    _last_request_time = time.time()


def search_discogs(track_name: str, vibe: str = None) -> Optional[DiscogsResult]:
    """Search Discogs for a track.

    Args:
        track_name: Track name (may include artist)
        vibe: Optional genre hint from the streamer

    Returns:
        DiscogsResult if found, None otherwise

    Note:
        Requires DISCOGS_TOKEN or (DISCOGS_KEY + DISCOGS_SECRET) env vars.
        Get credentials at https://www.discogs.com/settings/developers
    """
    # Check for credentials first
    if not HAS_CREDENTIALS:
        return None

    cache = _load_cache()
    cache_key = track_name.lower()

    # Check cache
    if cache_key in cache:
        entry = cache[cache_key]
        if time.time() - entry.get("timestamp", 0) < CACHE_TTL_SECONDS:
            data = entry.get("data")
            if data is None:
                return None  # Cached miss
            return DiscogsResult(**data)

    # Parse track name
    artist, title = _clean_track_name(track_name)

    # Build search query
    if artist:
        query = f"{artist} {title}"
    else:
        query = title

    # Add vibe as genre hint if useful
    genre_map = {
        "jazz": "jazz",
        "soul": "soul",
        "funk": "funk",
        "disco": "disco",
        "ambient": "electronic",
        "electronic": "electronic",
        "dub": "reggae",
        "classical": "classical",
        "hiphop": "hip hop",
        "hiphop_chill": "hip hop",
        "world": "world",
        "bossa": "bossa nova",
        "downtempo": "electronic",
    }
    genre = genre_map.get(vibe, "")

    # Build URL with auth params if using key/secret
    params = {
        "q": query,
        "type": "release",
        "per_page": 5,
    }
    if genre:
        params["genre"] = genre

    # Add key/secret to URL params if not using token
    if DISCOGS_KEY and DISCOGS_SECRET and not DISCOGS_TOKEN:
        params["key"] = DISCOGS_KEY
        params["secret"] = DISCOGS_SECRET

    url = f"https://api.discogs.com/database/search?{urllib.parse.urlencode(params)}"

    # Rate limit
    _rate_limit()

    # Make request
    headers = {
        "User-Agent": DISCOGS_USER_AGENT,
    }
    # Use token auth if available (preferred)
    if DISCOGS_TOKEN:
        headers["Authorization"] = f"Discogs token={DISCOGS_TOKEN}"

    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=10) as response:
            data = json.loads(response.read().decode())
    except urllib.error.HTTPError as e:
        if e.code == 401:
            # Authentication failed - credentials may be invalid
            pass
        # Cache the miss to avoid repeated failures
        cache[cache_key] = {"timestamp": time.time(), "data": None}
        _save_cache()
        return None
    except Exception as e:
        # Cache the miss to avoid repeated failures
        cache[cache_key] = {"timestamp": time.time(), "data": None}
        _save_cache()
        return None

    results = data.get("results", [])
    if not results:
        # Cache miss
        cache[cache_key] = {"timestamp": time.time(), "data": None}
        _save_cache()
        return None

    # Take first result
    r = results[0]

    # Extract artist from title (format: "Artist - Title" or just "Title")
    result_title = r.get("title", "")
    if " - " in result_title:
        result_artist, result_track = result_title.split(" - ", 1)
    else:
        result_artist = ""
        result_track = result_title

    # Get label and format
    labels = r.get("label", [])
    label = labels[0] if labels else None
    formats = r.get("format", [])
    fmt = formats[0] if formats else None

    result = DiscogsResult(
        release_id=r.get("id"),
        title=result_track,
        artist=result_artist,
        year=r.get("year"),
        url=f"https://www.discogs.com/release/{r.get('id')}",
        thumb_url=r.get("thumb"),
        label=label,
        format=fmt,
    )

    # Cache hit
    cache[cache_key] = {
        "timestamp": time.time(),
        "data": {
            "release_id": result.release_id,
            "title": result.title,
            "artist": result.artist,
            "year": result.year,
            "url": result.url,
            "thumb_url": result.thumb_url,
            "label": result.label,
            "format": result.format,
        }
    }
    _save_cache()

    return result


def get_discogs_url(track_name: str, vibe: str = None) -> Optional[str]:
    """Get Discogs URL for a track.

    Convenience wrapper around search_discogs.
    """
    result = search_discogs(track_name, vibe)
    return result.url if result else None


if __name__ == "__main__":
    # Test
    import sys

    test_tracks = [
        ("Miles Davis - Kind of Blue", "jazz"),
        ("03 - Three Little Birds", "dub"),
        ("Massive Attack - Teardrop", "downtempo"),
        ("Chet Baker - My Funny Valentine", "jazz"),
    ]

    for track, vibe in test_tracks:
        print(f"\nSearching: {track}")
        result = search_discogs(track, vibe)
        if result:
            print(f"  Found: {result.artist} - {result.title}")
            print(f"  Year: {result.year}")
            print(f"  URL: {result.url}")
            print(f"  Label: {result.label}")
        else:
            print("  Not found")
