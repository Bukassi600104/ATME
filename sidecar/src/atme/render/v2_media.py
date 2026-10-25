"""Checked presentation frames from immutable original media bytes.

This is an owning decoder kernel, not compositor or Split admission. No URI,
host media path, input seek, inferred FPS or timestamp synthesis is accepted.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import subprocess
import threading
from bisect import bisect_right
from collections import OrderedDict
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path

from PIL import Image

from atme.render.animator import find_ffmpeg
from atme.render.v2_media_view import media_active_at
from atme.render.v2_raster import MAX_PIXELS, CanonicalPNG, canonical_png
from atme.store.contracts_v2 import MediaPlayback, MediaStreamPin

# Same source-video ceiling as existing project_media ingress. These are
# bounded kernel operations, not Phase 11 long-project performance acceptance.
MAX_MEDIA_BYTES = 1024 * 1024 * 1024
MAX_MEDIA_FRAMES = 100_000
MAX_DIAGNOSTIC_BYTES = 64 * 1024 * 1024
DECODE_TIMEOUT_SECONDS = 120
DECODE_POLICY = "atme-v2-pts-rgba-framehash-1"
_INVENTORY_CACHE = OrderedDict()
_FRAME_CACHE = OrderedDict()
_CACHE_LOCK = threading.Lock()


def _cache_read(cache, key):
    with _CACHE_LOCK:
        value = cache.pop(key, None)
        if value is not None:
            cache[key] = value
        return value


def _cache_write(cache, key, value, limit):
    # Keys contain only digests/protocol/stream/frame identity, never original
    # source bytes. Values contain bounded inventory metadata or checked PNGs.
    with _CACHE_LOCK:
        cache.pop(key, None)
        cache[key] = value
        while len(cache) > limit:
            cache.popitem(last=False)
    return value


@dataclass(frozen=True)
class PresentationFrame:
    decode_index: int
    pts: int
    duration: int
    rgba_sha256: str


@dataclass(frozen=True)
class CheckedMedia:
    source_sha256: str
    stream_document: str
    frames: tuple[PresentationFrame, ...]

    @property
    def pin(self) -> MediaStreamPin:
        # Never expose a mutable Pydantic object held by the immutable cache.
        return MediaStreamPin.model_validate_json(self.stream_document)


def _tool_identity(executable):
    try:
        path = Path(executable).resolve(strict=True) if executable else None
        if path is None or not path.is_file():
            raise OSError("missing executable")
        stat = path.stat()
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            while block := handle.read(1024 * 1024):
                digest.update(block)
        after = path.stat()
        if (stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns) != (
                after.st_size, after.st_mtime_ns, after.st_ctime_ns):
            raise OSError("executable changed while hashing")
    except (OSError, ValueError, TypeError) as exc:
        raise ValueError("checked FFmpeg decoder is unavailable") from exc
    return (str(path), stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns,
            digest.hexdigest(), DECODE_POLICY)


def _decoder_identity():
    return _tool_identity(find_ffmpeg())


def _assert_decoder(tool):
    try:
        actual = _tool_identity(tool[0])
    except ValueError as exc:
        raise ValueError("checked decoder changed during operation") from exc
    if tool != actual:
        raise ValueError("checked decoder changed during operation")


def _run(raw, tool, arguments, output_limit):
    """Drain both pipes concurrently with hard byte/time bounds, no shell/files."""
    _assert_decoder(tool)
    buffers = [bytearray(), bytearray()]
    errors = []
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    try:
        child = subprocess.Popen([tool[0], *arguments], stdin=subprocess.PIPE,
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                 creationflags=flags)
    except OSError as exc:
        raise ValueError("checked decoder could not start") from exc

    def read(pipe, buffer, limit):
        try:
            while chunk := pipe.read(65536):
                if len(buffer) + len(chunk) > limit:
                    errors.append("decoder output exceeds bounded operation")
                    child.kill()
                    return
                buffer.extend(chunk)
        except OSError:
            errors.append("decoder pipe failed")
            child.kill()
        finally:
            pipe.close()

    def write():
        try:
            child.stdin.write(raw)
            child.stdin.close()
        except (OSError, BrokenPipeError):
            # Invalid streams can terminate before consuming all supplied bytes.
            try:
                child.stdin.close()
            except OSError:
                pass

    workers = [threading.Thread(target=read, args=(child.stdout, buffers[0], output_limit)),
               threading.Thread(target=read, args=(child.stderr, buffers[1], MAX_DIAGNOSTIC_BYTES)),
               threading.Thread(target=write)]
    for worker in workers:
        worker.start()
    try:
        code = child.wait(timeout=DECODE_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        errors.append("decoder exceeded bounded operation deadline")
        child.kill()
        code = child.wait()
    finally:
        for worker in workers:
            worker.join()
    _assert_decoder(tool)
    if errors or code != 0:
        raise ValueError(errors[0] if errors else "decoder rejected source or selected video stream")
    return bytes(buffers[0]), buffers[1].decode("utf-8", errors="replace")


def _input_arguments(stream_index):
    return ["-hide_banner", "-nostdin", "-nostats", "-loglevel", "info", "-copyts",
            "-threads", "1", "-noautorotate", "-protocol_whitelist", "pipe,cache",
            "-i", "cache:pipe:0", "-map", f"0:{stream_index}",
            "-map", "-0:disp:attached_pic?", "-an", "-sn", "-dn"]


_PREFIX = re.compile(r"^\[showinfo@atme_media @ ([0-9a-fA-Fx]+)\]\s+(.*)$")
_CLOCK = re.compile(r"config in time_base: (\d+)/(\d+),")
_FRAME = re.compile(r"n:\s*(\d+) pts:\s*(\S+) pts_time:\S+\s+duration:\s*(\S+) "
                    r"duration_time:\S+\s+fmt:rgba\s+.*?\bs:(\d+)x(\d+)\s")


def _presentation(log):
    clock = None
    address = None
    frames = []
    for line in log.splitlines():
        match = _PREFIX.match(line)
        if match is None:
            continue
        current_address, body = match.groups()
        if body.startswith("config in time_base:"):
            time_base = _CLOCK.match(body)
            if clock is not None or time_base is None:
                raise ValueError("media inventory has ambiguous stream clock")
            num, den = map(int, time_base.groups())
            if num <= 0 or den <= 0:
                raise ValueError("media inventory lacks a positive stream clock")
            clock, address = Fraction(num, den), current_address
        elif body.startswith("n:"):
            record = _FRAME.match(body)
            if clock is None or address != current_address or record is None:
                raise ValueError("media inventory lacks exact decoded presentation timestamps")
            try:
                index, pts, duration, width, height = map(int, record.groups())
            except ValueError as exc:
                raise ValueError("media inventory has missing presentation timestamp or duration") from exc
            if (index != len(frames) or duration <= 0 or width <= 0 or height <= 0
                    or width * height > MAX_PIXELS or index >= MAX_MEDIA_FRAMES):
                raise ValueError("media inventory has invalid or unbounded presentation frames")
            frames.append((index, pts, duration, width, height))
    if not frames or clock is None:
        raise ValueError("source has no admitted video presentation inventory")
    if any(frame[3:] != frames[0][3:] for frame in frames):
        raise ValueError("media inventory changes selected-stream dimensions")
    if len({frame[1] for frame in frames}) != len(frames):
        raise ValueError("media inventory has duplicate presentation timestamps")
    return clock, frames


def _frame_hashes(output, clock, frames):
    """Bind every decoded ordinal to actual RGBA byte length/hash and raw PTS."""
    try:
        lines = output.decode("ascii").splitlines()
        width, height = frames[0][3:]
        if (f"#tb 0: {clock.numerator}/{clock.denominator}" not in lines
                or "#hash: SHA256" not in lines or "#codec_id 0: rawvideo" not in lines
                or f"#dimensions 0: {width}x{height}" not in lines):
            raise ValueError("media inventory disagrees with raw frame output")
        rows = [line.split(",") for line in lines if line and not line.startswith("#")]
        if len(rows) != len(frames):
            raise ValueError("media inventory/raw frame count mismatch")
        hashes = []
        for row, frame in zip(rows, frames, strict=True):
            if (len(row) != 6 or int(row[0]) != 0 or int(row[2]) != frame[1]
                    or int(row[4]) != width * height * 4
                    or re.fullmatch(r"[0-9a-f]{64}", row[5].strip()) is None):
                raise ValueError("media inventory/raw frame timestamp or byte mismatch")
            hashes.append(row[5].strip())
        return hashes
    except (UnicodeError, TypeError, IndexError) as exc:
        raise ValueError("media inventory/raw frame output is malformed") from exc


def _inspect(raw, stream_index, tool):
    source_checksum = _source_sha256(raw)
    key = (source_checksum, stream_index, tool)
    cached = _cache_read(_INVENTORY_CACHE, key)
    if cached is not None:
        return cached
    arguments = _input_arguments(stream_index) + [
        "-vf", "format=rgba,showinfo@atme_media", "-fps_mode", "passthrough",
        "-frames:v", str(MAX_MEDIA_FRAMES + 1), "-c:v", "rawvideo", "-pix_fmt", "rgba",
        "-threads:v", "1", "-enc_time_base:v", "demux", "-f", "framehash", "-hash", "sha256", "pipe:1"]
    output, log = _run(raw, tool, arguments, MAX_DIAGNOSTIC_BYTES)
    clock, frames = _presentation(log)
    hashes = _frame_hashes(output, clock, frames)
    width, height = frames[0][3:]
    ordered = tuple(sorted((PresentationFrame(*frame[:3], pixel_hash)
                            for frame, pixel_hash in zip(frames, hashes, strict=True)), key=lambda f: f.pts))
    inventory = {"version": "1.0.0", "stream_index": stream_index, "width": width, "height": height,
                 "time_base_numerator": clock.numerator, "time_base_denominator": clock.denominator,
                 "frames": [[frame.pts, frame.duration] for frame in ordered]}
    timestamp_checksum = hashlib.sha256(json.dumps(inventory, sort_keys=True, separators=(",", ":"))
                                        .encode("utf-8")).hexdigest()
    pin = MediaStreamPin(version="1.0.0", stream_index=stream_index, width=width, height=height,
                         time_base_numerator=clock.numerator, time_base_denominator=clock.denominator,
                         first_pts=ordered[0].pts, end_pts=ordered[-1].pts + ordered[-1].duration,
                         frame_count=len(ordered), timestamps_sha256=timestamp_checksum)
    checked = CheckedMedia(source_checksum, pin.model_dump_json(), ordered)
    return _cache_write(_INVENTORY_CACHE, key, checked, 2)


def _source_sha256(raw):
    if type(raw) is not bytes or not 0 < len(raw) <= MAX_MEDIA_BYTES:
        raise ValueError("media source must be bounded immutable original bytes")
    return hashlib.sha256(raw).hexdigest()


def inspect_media(raw: bytes, stream_index: int) -> CheckedMedia:
    checksum = _source_sha256(raw)
    if type(stream_index) is not int or stream_index < 0:
        raise ValueError("media stream index must be a nonnegative integer")
    tool = _decoder_identity()
    checked = _inspect(raw, stream_index, tool)
    _assert_decoder(tool)
    if checked.source_sha256 != checksum:
        raise ValueError("media source checksum disagrees with checked inventory")
    return checked


def _decode_frame(raw, tool, stream_document, frame):
    key = (_source_sha256(raw), tool, stream_document, frame)
    cached = _cache_read(_FRAME_CACHE, key)
    if cached is not None:
        return cached
    pin = MediaStreamPin.model_validate_json(stream_document)
    arguments = _input_arguments(pin.stream_index) + [
        "-vf", f"format=rgba,select=eq(n\\,{frame.decode_index}),showinfo@atme_media",
        "-fps_mode", "passthrough", "-frames:v", "1", "-c:v", "rawvideo", "-pix_fmt", "rgba",
        "-threads:v", "1", "-enc_time_base:v", "demux", "-f", "rawvideo", "pipe:1"]
    output, log = _run(raw, tool, arguments, pin.width * pin.height * 4)
    clock, records = _presentation(log)
    if (clock != Fraction(pin.time_base_numerator, pin.time_base_denominator)
            or len(records) != 1 or records[0][1:] != (frame.pts, frame.duration, pin.width, pin.height)
            or len(output) != pin.width * pin.height * 4
            or hashlib.sha256(output).hexdigest() != frame.rgba_sha256):
        raise ValueError("selected source frame disagrees with checked presentation inventory")
    image = Image.frombytes("RGBA", (pin.width, pin.height), output)
    encoded = io.BytesIO()
    image.save(encoded, format="PNG", optimize=False, compress_level=9)
    return _cache_write(_FRAME_CACHE, key, canonical_png(encoded.getvalue()), 4)


def media_frame(raw: bytes, playback: MediaPlayback, at_ms: int) -> CanonicalPNG | None:
    if type(playback) is not MediaPlayback or type(at_ms) is not int or at_ms < 0:
        raise ValueError("media source playback needs a strict integer project clock")
    playback = MediaPlayback.model_validate(playback.model_dump(mode="json"))
    if _source_sha256(raw) != playback.placement.source_sha256:
        raise ValueError("media source checksum disagrees with authored source pin")
    checked = inspect_media(raw, playback.source_stream.stream_index)
    if (checked.source_sha256 != playback.placement.source_sha256
            or checked.pin != playback.source_stream
            or checked.pin.duration_ms != playback.source_duration_ms):
        raise ValueError("media source pins disagree with recomputed stream inventory")
    if not media_active_at(playback, at_ms):
        return None
    clock = playback.source_in_ms + at_ms - playback.timeline_start_ms
    pin = checked.pin
    last_tick = pin.first_pts + clock * pin.time_base_denominator // (pin.time_base_numerator * 1000)
    index = bisect_right(tuple(frame.pts for frame in checked.frames), last_tick) - 1
    tool = _decoder_identity()
    # Inventory and selected-frame decode must use the same resolved decoder.
    if _inspect(raw, pin.stream_index, tool) != checked:
        raise ValueError("media decoder inventory changed during frame selection")
    raster = _decode_frame(raw, tool, checked.stream_document, checked.frames[index])
    _assert_decoder(tool)
    return raster
