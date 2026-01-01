#!/usr/bin/env python3
"""
QR code generator for WVOID-FM.

Generates QR codes linking to Discogs release pages.
Uses caching to avoid regenerating QR codes for the same URL.
"""

import hashlib
import io
from pathlib import Path
from typing import Optional

# Try to import qrcode, fall back to a simpler approach if not available
try:
    import qrcode
    from qrcode.image.pure import PyPNGImage
    HAS_QRCODE = True
except ImportError:
    HAS_QRCODE = False


QR_CACHE_DIR = Path.home() / ".wvoid" / "qr_cache"
QR_SIZE = 200  # pixels


def _url_hash(url: str) -> str:
    """Generate a short hash for a URL."""
    return hashlib.md5(url.encode()).hexdigest()[:12]


def generate_qr_png(url: str) -> Optional[bytes]:
    """Generate a QR code PNG for a URL.

    Args:
        url: The URL to encode

    Returns:
        PNG image bytes, or None if generation failed
    """
    if not HAS_QRCODE:
        return None

    # Check cache
    cache_key = _url_hash(url)
    cache_path = QR_CACHE_DIR / f"{cache_key}.png"

    if cache_path.exists():
        return cache_path.read_bytes()

    try:
        # Generate QR code
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_L,
            box_size=8,
            border=2,
        )
        qr.add_data(url)
        qr.make(fit=True)

        # Create image
        img = qr.make_image(fill_color="black", back_color="white")

        # Save to bytes
        buffer = io.BytesIO()
        img.save(buffer, format="PNG")
        png_bytes = buffer.getvalue()

        # Cache
        QR_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        cache_path.write_bytes(png_bytes)

        return png_bytes

    except Exception:
        return None


def generate_qr_data_url(url: str) -> Optional[str]:
    """Generate a QR code as a data URL for embedding in HTML/JSON.

    Args:
        url: The URL to encode

    Returns:
        Data URL (data:image/png;base64,...) or None if generation failed
    """
    import base64

    png_bytes = generate_qr_png(url)
    if not png_bytes:
        return None

    b64 = base64.b64encode(png_bytes).decode("ascii")
    return f"data:image/png;base64,{b64}"


def get_cached_qr_path(url: str) -> Optional[Path]:
    """Get the cached QR code path for a URL, if it exists.

    Args:
        url: The URL that was encoded

    Returns:
        Path to cached PNG, or None if not cached
    """
    cache_key = _url_hash(url)
    cache_path = QR_CACHE_DIR / f"{cache_key}.png"
    return cache_path if cache_path.exists() else None


def clear_cache() -> int:
    """Clear the QR code cache.

    Returns:
        Number of files deleted
    """
    if not QR_CACHE_DIR.exists():
        return 0

    count = 0
    for f in QR_CACHE_DIR.glob("*.png"):
        try:
            f.unlink()
            count += 1
        except Exception:
            pass
    return count


if __name__ == "__main__":
    # Test
    test_url = "https://www.discogs.com/release/12345"

    if HAS_QRCODE:
        print(f"Generating QR for: {test_url}")
        png_bytes = generate_qr_png(test_url)
        if png_bytes:
            print(f"Generated {len(png_bytes)} bytes")

            # Save test file
            test_path = Path("/tmp/test_qr.png")
            test_path.write_bytes(png_bytes)
            print(f"Saved to: {test_path}")
        else:
            print("Generation failed")
    else:
        print("qrcode library not installed. Run: uv add qrcode")
