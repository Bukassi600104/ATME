"""Bounded, self-contained evidence images; no external resource resolution."""
import base64
import binascii
import hashlib
import io
from functools import lru_cache

from PIL import Image

MAX_PNG_BYTES = 8 * 1024 * 1024
MAX_PIXELS = 16_000_000


@lru_cache(maxsize=8)
def validate_png(payload: str, digest: str) -> None:
    if len(payload) > ((MAX_PNG_BYTES + 2) // 3) * 4:
        raise ValueError("evidence PNG exceeds 8 MiB")
    try:
        raw = base64.b64decode(payload, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise ValueError("evidence PNG must be strict base64") from exc
    if len(raw) > MAX_PNG_BYTES or not raw.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("evidence asset must be a PNG within 8 MiB")
    if hashlib.sha256(raw).hexdigest() != digest:
        raise ValueError("evidence PNG checksum mismatch")
    try:
        with Image.open(io.BytesIO(raw)) as img:
            if img.format != "PNG" or img.width * img.height > MAX_PIXELS:
                raise ValueError("evidence PNG exceeds pixel limit")
            if getattr(img, "n_frames", 1) != 1:
                raise ValueError("animated evidence PNG is not supported")
            img.verify()
    except (OSError, SyntaxError, Image.DecompressionBombError) as exc:
        raise ValueError("invalid evidence PNG") from exc
