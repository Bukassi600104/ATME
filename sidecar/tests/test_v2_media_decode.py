"""P3-40 real encoded frames: exact presentation time, not average FPS."""

import gc
import hashlib
import io
import json
import os
import struct
import subprocess
import sys
from copy import deepcopy

import pytest
from PIL import Image
from test_v2_media_contract import media_playback

from atme.render.animator import find_ffmpeg
from atme.store.contracts_v2 import MediaPlayback

COLORS = ((255, 0, 0, 255), (0, 255, 0, 255), (0, 0, 255, 255))


@pytest.fixture(scope="module")
def encoded_vfr():
    ffmpeg = find_ffmpeg()
    assert ffmpeg, "This native acceptance requires the existing local FFmpeg"
    raw = b"".join(bytes(color) * (80 * 40) for color in COLORS)
    command = [ffmpeg, "-hide_banner", "-v", "error", "-f", "rawvideo", "-pixel_format", "rgba",
               "-video_size", "80x40", "-framerate", "1", "-i", "pipe:0",
               "-vf", "setpts=if(eq(N\\,0)\\,0\\,if(eq(N\\,1)\\,2\\,5))",
               "-fps_mode", "passthrough", "-c:v", "libx264rgb", "-crf", "0",
               "-movflags", "frag_keyframe+empty_moov", "-f", "mp4", "pipe:1"]
    result = subprocess.run(command, input=raw, capture_output=True, timeout=30, check=False)
    assert result.returncode == 0, result.stderr.decode(errors="replace")
    return result.stdout


@pytest.fixture
def decoder():
    from atme.render import v2_media
    return v2_media


def playback_for(checked, raw, *, source_in_ms=1000, source_out_ms=5500, timeline_start_ms=200):
    document = deepcopy(media_playback())
    document.update(source_stream=checked.pin.model_dump(mode="json"),
                    source_duration_ms=checked.pin.duration_ms,
                    source_in_ms=source_in_ms, source_out_ms=source_out_ms,
                    timeline_start_ms=timeline_start_ms)
    document["placement"].update(source_sha256=hashlib.sha256(raw).hexdigest())
    return MediaPlayback.model_validate(document)


def test_real_vfr_inventory_is_exact_and_recomputed_from_encoded_bytes(decoder, encoded_vfr):
    checked = decoder.inspect_media(encoded_vfr, 0)
    pin = checked.pin
    assert checked.source_sha256 == hashlib.sha256(encoded_vfr).hexdigest()
    assert (pin.width, pin.height, pin.frame_count, pin.duration_ms) == (80, 40, 3, 6000)
    assert [(frame.pts - pin.first_pts) * pin.time_base_numerator * 1000
            // pin.time_base_denominator for frame in checked.frames] == [0, 2000, 5000]
    inventory = {"version": "1.0.0", "stream_index": 0, "width": 80, "height": 40,
                 "time_base_numerator": pin.time_base_numerator,
                 "time_base_denominator": pin.time_base_denominator,
                 "frames": [[frame.pts, frame.duration] for frame in checked.frames]}
    expected = hashlib.sha256(json.dumps(inventory, sort_keys=True, separators=(",", ":"))
                              .encode("utf-8")).hexdigest()
    assert pin.timestamps_sha256 == expected
    assert [frame.decode_index for frame in checked.frames] == [0, 1, 2]
    assert [frame.rgba_sha256 for frame in checked.frames] == [
        hashlib.sha256(bytes(color) * (80 * 40)).hexdigest() for color in COLORS]
    # Cached state cannot be rewritten by mutating a returned Pydantic view.
    pin.first_pts = 99
    assert decoder.inspect_media(encoded_vfr, 0).pin.first_pts != 99


@pytest.mark.parametrize("at_ms,color", [
    (200, COLORS[0]), (1199, COLORS[0]), (1200, COLORS[1]),
    (4199, COLORS[1]), (4200, COLORS[2]), (4699, COLORS[2]),
])
def test_real_vfr_range_selects_exact_boundary_pixels(decoder, encoded_vfr, at_ms, color):
    playback = playback_for(decoder.inspect_media(encoded_vfr, 0), encoded_vfr)
    frame = decoder.media_frame(encoded_vfr, playback, at_ms)
    assert (frame.width, frame.height) == (80, 40)
    with Image.open(io.BytesIO(frame.payload)) as image:
        assert image.convert("RGBA").tobytes() == bytes(color) * (80 * 40)


def test_backward_random_seek_matches_fresh_pixels_and_half_open_lifetime(decoder, encoded_vfr):
    playback = playback_for(decoder.inspect_media(encoded_vfr, 0), encoded_vfr)
    original = bytes(encoded_vfr)
    expected = {at: decoder.media_frame(encoded_vfr, playback, at).payload
                for at in (200, 1100, 1200, 3000, 4200, 4699)}
    for at in (4699, 200, 4200, 1200, 3000, 1100, 4699, 200):
        assert decoder.media_frame(encoded_vfr, playback, at).payload == expected[at]
    assert decoder.media_frame(encoded_vfr, playback, 199) is None
    assert decoder.media_frame(encoded_vfr, playback, 4700) is None
    assert encoded_vfr == original


@pytest.mark.parametrize("field,value", [
    ("source_sha256", "0" * 64), ("timestamps_sha256", "0" * 64),
    ("first_pts", -1), ("frame_count", 4),
])
def test_warm_cache_does_not_certify_tampered_source_pins(decoder, encoded_vfr, field, value):
    checked = decoder.inspect_media(encoded_vfr, 0)
    raw = playback_for(checked, encoded_vfr).model_dump(mode="json")
    if field == "source_sha256":
        raw["placement"][field] = value
    else:
        raw["source_stream"][field] = value
        pin = raw["source_stream"]
        raw["source_duration_ms"] = ((pin["end_pts"] - pin["first_pts"])
                                     * pin["time_base_numerator"] * 1000
                                     // pin["time_base_denominator"])
    playback = MediaPlayback.model_validate(raw)
    with pytest.raises(ValueError, match="source|inventory|stream"):
        decoder.media_frame(encoded_vfr, playback, 200)


def test_cache_cannot_hide_changed_decoder_resolution(decoder, encoded_vfr, monkeypatch, tmp_path):
    decoder.inspect_media(encoded_vfr, 0)
    monkeypatch.setenv("ATME_FFMPEG", str(tmp_path / "not-installed-ffmpeg.exe"))
    with pytest.raises(ValueError, match="decoder|FFmpeg"):
        decoder.inspect_media(encoded_vfr, 0)


@pytest.mark.parametrize("index", [-1, True, 1.5, 99])
def test_invalid_or_absent_global_stream_rejects(decoder, encoded_vfr, index):
    with pytest.raises(ValueError, match="stream|decoder"):
        decoder.inspect_media(encoded_vfr, index)


def test_invalid_or_mutable_media_bytes_reject_without_fallback(decoder, encoded_vfr):
    for raw in (b"", b"not a video", bytearray(encoded_vfr)):
        with pytest.raises(ValueError, match="source|decoder"):
            decoder.inspect_media(raw, 0)


def test_exact_global_stream_index_ignores_audio_and_rejects_nonvideo(decoder, encoded_vfr):
    command = [find_ffmpeg(), "-hide_banner", "-v", "error", "-i", "pipe:0",
               "-f", "lavfi", "-i", "anullsrc=r=8000:cl=mono:d=6", "-map", "1:a:0",
               "-map", "0:v:0", "-c:a", "aac", "-c:v", "copy",
               "-movflags", "frag_keyframe+empty_moov", "-f", "mp4", "pipe:1"]
    result = subprocess.run(command, input=encoded_vfr, capture_output=True, timeout=30, check=False)
    assert result.returncode == 0, result.stderr.decode(errors="replace")
    checked = decoder.inspect_media(result.stdout, 1)
    assert checked.pin.stream_index == 1 and checked.pin.frame_count == 3
    assert checked.frames[1].rgba_sha256 == hashlib.sha256(bytes(COLORS[1]) * (80 * 40)).hexdigest()
    with pytest.raises(ValueError, match="stream|decoder"):
        decoder.inspect_media(result.stdout, 0)


def test_attached_picture_is_not_a_video_stream(decoder, encoded_vfr, tmp_path):
    cover = tmp_path / "cover.png"
    Image.new("RGB", (80, 40), "yellow").save(cover)
    destination = tmp_path / "with-cover.mp4"
    command = [find_ffmpeg(), "-hide_banner", "-v", "error", "-i", "pipe:0", "-i", str(cover),
               "-map", "0:v:0", "-map", "1:v:0", "-c", "copy", "-disposition:v:1", "attached_pic",
               str(destination)]
    result = subprocess.run(command, input=encoded_vfr, capture_output=True, timeout=30, check=False)
    assert result.returncode == 0, result.stderr.decode(errors="replace")
    source = destination.read_bytes()
    assert decoder.inspect_media(source, 0).pin.frame_count == 3
    with pytest.raises(ValueError, match="stream|decoder"):
        decoder.inspect_media(source, 1)


@pytest.mark.parametrize("offset", [7, -2])
def test_real_signed_origin_is_preserved_then_normalized_for_selection(decoder, offset):
    # MPEG-TS carries signed/wrapped source PTS; copyts must retain the demuxed
    # signed presentation origin, rather than silently shifting the source to 0.
    raw = b"".join(bytes(color) * (80 * 40) for color in COLORS)
    command = [find_ffmpeg(), "-hide_banner", "-v", "error", "-f", "rawvideo",
               "-pixel_format", "rgba", "-video_size", "80x40", "-framerate", "1",
               "-i", "pipe:0", "-c:v", "mpeg2video", "-bf", "0",
               "-output_ts_offset", str(offset), "-avoid_negative_ts", "disabled",
               "-mpegts_copyts", "1", "-muxdelay", "0", "-f", "mpegts", "pipe:1"]
    result = subprocess.run(command, input=raw, capture_output=True, timeout=30, check=False)
    assert result.returncode == 0, result.stderr.decode(errors="replace")
    checked = decoder.inspect_media(result.stdout, 0)
    pin = checked.pin
    assert pin.first_pts * pin.time_base_numerator == offset * pin.time_base_denominator
    assert pin.duration_ms == 3000
    playback = playback_for(checked, result.stdout, source_in_ms=0, source_out_ms=3000,
                            timeline_start_ms=0)
    for at_ms, expected in ((0, COLORS[0]), (1000, COLORS[1]), (2000, COLORS[2])):
        frame = decoder.media_frame(result.stdout, playback, at_ms)
        with Image.open(io.BytesIO(frame.payload)) as image:
            actual = image.convert("RGBA").getpixel((40, 20))
        assert all(abs(a - b) <= 5 for a, b in zip(actual, expected, strict=True))


def test_real_b_frames_keep_presentation_order_not_packet_order(decoder):
    colors = [(index * 30, 120, 240 - index * 25, 255) for index in range(8)]
    raw = b"".join(bytes(color) * (80 * 40) for color in colors)
    command = [find_ffmpeg(), "-hide_banner", "-v", "error", "-f", "rawvideo",
               "-pixel_format", "rgba", "-video_size", "80x40", "-framerate", "1", "-i", "pipe:0",
               "-c:v", "libx264rgb", "-crf", "18", "-bf", "2", "-g", "12",
               "-x264-params", "b-adapt=0:scenecut=0", "-movflags", "frag_keyframe+empty_moov",
               "-f", "mp4", "pipe:1"]
    result = subprocess.run(command, input=raw, capture_output=True, timeout=30, check=False)
    assert result.returncode == 0, result.stderr.decode(errors="replace")
    # Independently show the fixture really contains B pictures; -bf alone is
    # not proof, since the lossless encoder disables B frames.
    probe = subprocess.run([find_ffmpeg(), "-hide_banner", "-nostats", "-loglevel", "info",
                            "-copyts", "-i", "pipe:0", "-vf", "showinfo", "-fps_mode",
                            "passthrough", "-f", "null", "-"],
                           input=result.stdout, capture_output=True, timeout=30, check=False)
    assert probe.returncode == 0 and b"type:B" in probe.stderr
    checked = decoder.inspect_media(result.stdout, 0)
    pin = checked.pin
    assert pin.frame_count == 8 and pin.duration_ms == 8000
    assert [(frame.pts - pin.first_pts) * pin.time_base_numerator * 1000
            // pin.time_base_denominator for frame in checked.frames] == list(range(0, 8000, 1000))
    document = playback_for(checked, result.stdout).model_dump(mode="json")
    document.update(source_in_ms=0, source_out_ms=8000, timeline_start_ms=0)
    playback = MediaPlayback.model_validate(document)
    for index in (7, 0, 4, 1, 6, 2, 5, 3):
        frame = decoder.media_frame(result.stdout, playback, index * 1000)
        with Image.open(io.BytesIO(frame.payload)) as image:
            actual = image.convert("RGBA").getpixel((40, 20))
        assert all(abs(a - b) <= 5 for a, b in zip(actual, colors[index], strict=True))


@pytest.mark.parametrize("records", [
    [(0, "NOPTS", 1)], [(0, 0, 0)], [(0, 0, -1)], [(0, 0, "N/A")],
    [(0, 0, 1), (1, 0, 1)], [(0, 0, 1), (2, 2, 1)],
])
def test_malformed_or_ambiguous_presentation_inventory_is_not_inferred(decoder, records):
    # Parser negatives complement real encoded acceptance, not replace it.
    prefix = "[showinfo@atme_media @ 1234] "
    log = prefix + "config in time_base: 1/1000, frame_rate: 1/1\n"
    log += "\n".join(prefix + f"n: {n} pts: {pts} pts_time:0 duration: {duration} "
                     "duration_time:0 fmt:rgba cl:unknown sar:1/1 s:80x40 i:P"
                     for n, pts, duration in records)
    with pytest.raises(ValueError, match="inventory"):
        decoder._presentation(log)


@pytest.mark.parametrize("at_ms", [True, 1.5, -1])
def test_runtime_clock_must_remain_strict_integer(decoder, encoded_vfr, at_ms):
    playback = playback_for(decoder.inspect_media(encoded_vfr, 0), encoded_vfr)
    with pytest.raises(ValueError, match="clock"):
        decoder.media_frame(encoded_vfr, playback, at_ms)


def test_source_checksum_is_checked_before_entering_decoder(decoder, encoded_vfr, monkeypatch):
    playback = playback_for(decoder.inspect_media(encoded_vfr, 0), encoded_vfr)
    raw = playback.model_dump(mode="json")
    raw["placement"]["source_sha256"] = "0" * 64
    invalid = MediaPlayback.model_validate(raw)

    def forbidden(*_args):
        pytest.fail("unchecked source reached decoder")

    monkeypatch.setattr(decoder, "inspect_media", forbidden)
    with pytest.raises(ValueError, match="source"):
        decoder.media_frame(encoded_vfr, invalid, 200)


def test_real_decoder_output_is_bounded_and_child_is_reaped(decoder, encoded_vfr):
    tool = decoder._decoder_identity()
    args = decoder._input_arguments(0) + ["-vf", "format=rgba,showinfo@atme_media", "-fps_mode",
                                          "passthrough", "-f", "rawvideo", "-pix_fmt", "rgba", "pipe:1"]
    with pytest.raises(ValueError, match="bounded operation"):
        decoder._run(encoded_vfr, tool, args, 16)


def test_real_decoder_deadline_terminates_child(decoder, encoded_vfr, monkeypatch):
    tool = decoder._decoder_identity()
    monkeypatch.setattr(decoder, "DECODE_TIMEOUT_SECONDS", 0.000001)
    args = decoder._input_arguments(0) + ["-vf", "showinfo@atme_media", "-f", "null", "-"]
    with pytest.raises(ValueError, match="deadline"):
        decoder._run(encoded_vfr, tool, args, 16)


def test_decoder_identity_changes_for_same_path_same_metadata_new_bytes(decoder, tmp_path, monkeypatch):
    # A generated file tests tool identity only: never alter the installed binary
    # or use a fake decoder to claim actual media acceptance.
    executable = tmp_path / "identity-only-ffmpeg.exe"
    executable.write_bytes(b"decoderA")
    monkeypatch.setenv("ATME_FFMPEG", str(executable))
    before_stat = executable.stat()
    before = decoder._decoder_identity()
    executable.write_bytes(b"decoderB")
    os.utime(executable, ns=(before_stat.st_atime_ns, before_stat.st_mtime_ns))
    after_stat = executable.stat()
    if after_stat.st_ctime_ns != before_stat.st_ctime_ns:
        # POSIX ctime cannot be restored. Model the same restored metadata that
        # Windows actually exposes, while still hashing different real bytes.
        original_stat = decoder.Path.stat

        def restored_stat(path, *args, **kwargs):
            return before_stat if path == executable else original_stat(path, *args, **kwargs)

        monkeypatch.setattr(decoder.Path, "stat", restored_stat)
    assert decoder._decoder_identity() != before
    with pytest.raises(ValueError, match="decoder changed"):
        decoder._assert_decoder(before)


def test_decoder_source_ceiling_preserves_existing_video_ingest(decoder):
    from atme.project_media import MAX_VIDEO_BYTES
    assert decoder.MAX_MEDIA_BYTES == MAX_VIDEO_BYTES


def test_checked_caches_do_not_retain_original_encoded_source_bytes(decoder, encoded_vfr):
    # A valid MP4 free atom makes this a distinct admitted source, while preserving
    # the exact existing encoded frames. No original file is changed.
    source = encoded_vfr + struct.pack(">I4s", 24, b"free") + bytes(range(16))
    gc.collect()
    before = sys.getrefcount(source)
    checked = decoder.inspect_media(source, 0)
    playback = playback_for(checked, source)
    frame = decoder.media_frame(source, playback, 200)
    assert frame.width == 80
    gc.collect()
    assert sys.getrefcount(source) == before, "cache keys/values retain the original media bytes"
