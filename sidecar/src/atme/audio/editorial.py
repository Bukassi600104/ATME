"""Measure and decode project-owned editorial sound using the same audio stream."""
from __future__ import annotations

from contextlib import nullcontext

AUDIO_FORMATS = {".wav": "wav", ".mp3": "mp3", ".m4a": "mov", ".aac": "aac", ".flac": "flac"}


def decode_sound(path, *, file_format=None, destination=None, sample_rate=None):
    """Return decoded duration. When requested, spool resampled samples to a seekable WAV."""
    import av
    import soundfile as sf

    options = {"format_whitelist": ",".join(AUDIO_FORMATS.values()), "enable_drefs": "0"}
    with path.open("rb") as src, av.open(src, format=file_format, options=options) as container:
        streams = container.streams.audio
        if len(streams) != 1:
            raise ValueError("Editorial sound requires one audio stream")
        stream = streams[0]
        rate = stream.codec_context.sample_rate
        if not rate or not stream.codec_context.channels:
            raise ValueError("Editorial sound has no sample rate or channels")
        channels = min(stream.codec_context.channels, 2)
        samples = 0
        if destination is not None:
            converter = av.AudioResampler(format="fltp", layout="mono" if channels == 1 else "stereo", rate=sample_rate)
            sink = sf.SoundFile(destination, mode="w", samplerate=sample_rate, channels=channels, subtype="FLOAT")
        else:
            sink = nullcontext()
        with sink as target:
            for frame in container.decode(stream):
                if frame.sample_rate != rate:
                    raise ValueError("Editorial sound changes sample rate within a stream")
                samples += frame.samples
                if target is not None:
                    for chunk in converter.resample(frame):
                        target.write(chunk.to_ndarray().T)
            if target is not None:
                for chunk in converter.resample(None):
                    target.write(chunk.to_ndarray().T)
        duration_ms = round(samples * 1000 / rate)
        if duration_ms <= 0:
            raise ValueError("Editorial sound has no playable samples")
        return duration_ms
