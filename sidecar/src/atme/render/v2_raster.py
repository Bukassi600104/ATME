"""Strict, deterministic in-memory PNG preparation for v2 project images.

The compositor consumes bytes supplied by the project layer. It never resolves
an asset URI, opens a host path, or fetches a network resource.
"""

from __future__ import annotations

import binascii
import hashlib
import io
import struct
from dataclasses import dataclass
from functools import lru_cache

from PIL import Image

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
MAX_SOURCE_BYTES = 8 * 1024 * 1024
MAX_CANONICAL_BYTES = 16 * 1024 * 1024
MAX_PIXELS = 16_000_000


class UnsupportedProjectPNG(ValueError):
    """A project image cannot be decoded without an implicit media policy."""


@dataclass(frozen=True)
class CanonicalPNG:
    payload: bytes
    width: int
    height: int
    source_sha256: str


def _check_chunks(raw: bytes) -> tuple[int, int]:
    if not raw.startswith(PNG_SIGNATURE) or not 0 < len(raw) <= MAX_SOURCE_BYTES:
        raise UnsupportedProjectPNG("project image must be a PNG within 8 MiB")
    offset = len(PNG_SIGNATURE)
    seen_ihdr = False
    seen_idat = False
    seen_iend = False
    idat_closed = False
    seen_srgb = False
    dimensions = None
    while offset < len(raw):
        if len(raw) - offset < 12:
            raise UnsupportedProjectPNG("project PNG has a truncated chunk")
        length = struct.unpack_from(">I", raw, offset)[0]
        end = offset + 12 + length
        if end > len(raw):
            raise UnsupportedProjectPNG("project PNG has a truncated chunk")
        kind = raw[offset + 4:offset + 8]
        body = raw[offset + 8:offset + 8 + length]
        crc = struct.unpack_from(">I", raw, offset + 8 + length)[0]
        if binascii.crc32(kind + body) & 0xFFFFFFFF != crc:
            raise UnsupportedProjectPNG("project PNG chunk checksum failed")
        if not seen_ihdr:
            if kind != b"IHDR" or length != 13:
                raise UnsupportedProjectPNG("project PNG needs a canonical IHDR")
            width, height, bit_depth, color, compression, filtering, interlace = struct.unpack(
                ">IIBBBBB", body
            )
            if (not width or not height or width * height > MAX_PIXELS
                    or bit_depth != 8 or color not in (2, 6)
                    or compression != 0 or filtering != 0 or interlace != 0):
                raise UnsupportedProjectPNG("project PNG needs bounded upright RGB/RGBA pixels")
            dimensions = (width, height)
            seen_ihdr = True
        elif kind == b"sRGB":
            if seen_srgb or seen_idat or length != 1 or body[0] > 3:
                raise UnsupportedProjectPNG("project PNG has unsupported color metadata")
            seen_srgb = True
        elif kind == b"IDAT":
            if idat_closed:
                raise UnsupportedProjectPNG("project PNG has noncontiguous image data")
            seen_idat = True
        elif kind == b"IEND":
            if not seen_idat or length != 0 or end != len(raw):
                raise UnsupportedProjectPNG("project PNG has trailing or missing image data")
            seen_iend = True
        else:
            # Palette, animation, orientation, ICC/gamma and arbitrary ancillary
            # chunks are not silently interpreted or carried into the frame.
            raise UnsupportedProjectPNG("project PNG has unsupported metadata or animation")
        if seen_idat and kind != b"IDAT":
            idat_closed = True
        offset = end
        if seen_iend:
            break
    if not seen_iend or offset != len(raw):
        raise UnsupportedProjectPNG("project PNG lacks a final IEND")
    return dimensions


@lru_cache(maxsize=4)
def canonical_png(raw: bytes) -> CanonicalPNG:
    """Verify encoded bytes, then strip metadata into stable upright RGBA8."""
    if type(raw) is not bytes:
        raise UnsupportedProjectPNG("project image bytes must be immutable")
    width, height = _check_chunks(raw)
    try:
        with Image.open(io.BytesIO(raw)) as image:
            if (image.format != "PNG" or image.size != (width, height)
                    or image.mode not in {"RGB", "RGBA"}
                    or getattr(image, "n_frames", 1) != 1):
                raise UnsupportedProjectPNG("project PNG decoded format is unsupported")
            rgba = image.convert("RGBA")
            rgba.load()
        # A new image has no inherited ancillary metadata or orientation.
        clean = Image.new("RGBA", (width, height))
        clean.paste(rgba)
        output = io.BytesIO()
        clean.save(output, format="PNG", optimize=False, compress_level=9)
        encoded = output.getvalue()
    except (OSError, SyntaxError, ValueError, Image.DecompressionBombError) as exc:
        if isinstance(exc, UnsupportedProjectPNG):
            raise
        raise UnsupportedProjectPNG("project PNG pixels could not be decoded") from exc
    if len(encoded) > MAX_CANONICAL_BYTES:
        raise UnsupportedProjectPNG("canonical project PNG exceeds 16 MiB")
    return CanonicalPNG(encoded, width, height, hashlib.sha256(raw).hexdigest())
