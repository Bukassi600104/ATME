"""One-shot bottleneck diagnostics for the three measured failures.

A) resvg: trivial vs full vs <text> cost; skip_system_fonts + explicit font file variant.
B) Kokoro: kokoro_onnx.Kokoro signature introspection + RTF at intra_op threads {1,2,4}.
C) faster-whisper: tiny.en vs base.en RTF with cpu_threads=4 on a cached sample wav.
"""

from __future__ import annotations

import inspect
import io
import time
from pathlib import Path

import numpy as np
from PIL import Image

MODELS = Path("data/models")
SR = 24000


def png_ms(svg: str, width: int = 1280, height: int = 720, n: int = 5, **kw) -> float:
    from atme.render.animator import resvg_bytes

    t0 = time.perf_counter()
    for _ in range(n):
        Image.open(io.BytesIO(resvg_bytes(svg, width, height))).convert("RGBA")
    return (time.perf_counter() - t0) / n * 1000


def section_a() -> None:
    print("--- A: resvg ---")
    flat = '<svg xmlns="http://www.w3.org/2000/svg" width="1920" height="1080"><rect width="1920" height="1080" fill="#FAF9F5"/></svg>'
    txt = ('<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="720">'
           '<rect width="1280" height="720" fill="#FAF9F5"/>'
           '<text x="100" y="200" font-family="Segoe Print" font-size="44" fill="#191917">Hello renderer</text></svg>')
    txt2 = txt.replace('font-family="Segoe Print"', 'font-family="Segoe Print" ')
    print("flat bg          : %6.1f ms" % png_ms(flat))
    print("with <text>      : %6.1f ms" % png_ms(txt))
    import resvg_py
    print("svg_to_bytes params:", [p for p in inspect.signature(resvg_py.svg_to_bytes).parameters])
    font = Path(r"C:\Windows\Fonts\segoepr.ttf")
    if font.exists():
        t0 = time.perf_counter()
        for _ in range(5):
            b = bytes(resvg_py.svg_to_bytes(svg_string=txt2.replace(' ', ' ', 1),
                                           width=1280, height=720,
                                           skip_system_fonts=True,
                                           font_files=[str(font)]))
        print("text+explicit font file (skip sys): %6.1f ms" % ((time.perf_counter() - t0) / 5 * 1000))


def _sample_wav_seconds() -> tuple[np.ndarray, int]:
    import soundfile as sf

    p = Path("data/bench-sample.wav")
    if p.exists():
        data, sr = sf.read(str(p), dtype="float32")
        return np.asarray(data, dtype=np.float32).reshape(-1), sr
    texts = [
        "Scaling large language models pushes infrastructure into a corner.",
        "You are fighting a trilemma: throughput against latency against cost.",
        "The memory wall is the tax you pay every single time a token moves.",
        "PagedAttention treats the KV cache like virtual memory pages.",
        "Continuous batching keeps the GPU fed without waiting for a whole batch to finish.",
        "That is roughly double the serving throughput on identical hardware.",
    ]
    from atme.audio import tts_kokoro

    chunks = [tts_kokoro.synthesize(t, use_cache=False, cache_dir=str(p.parent)) for t in texts]
    wav = np.concatenate([c[0] for c in chunks])
    sf.write(str(p), wav, chunks[0][1], subtype="PCM_16")
    return wav, chunks[0][1]


def section_b() -> None:
    print("--- B: kokoro threads ---")
    from kokoro_onnx import Kokoro

    sig = inspect.signature(Kokoro.__init__)
    print("Kokoro.__init__:", list(sig.parameters))
    try:
        import onnxruntime as ort
        so = ort.SessionOptions()
        print("default intra_op threads:", so.intra_op_num_threads)
    except Exception as e:
        print("ort probe err:", e)


def section_c(wav: np.ndarray, sr: int) -> None:
    print("--- C: whisper variants ---")
    from faster_whisper import WhisperModel

    for size in ("base.en", "tiny.en"):
        try:
            m = WhisperModel(size, device="cpu", compute_type="int8", cpu_threads=4)
            t0 = time.perf_counter()
            segs, info = m.transcribe(wav, language="en", vad_filter=True,
                                      word_timestamps=True, beam_size=1)
            nwords = sum(len(s.words or []) for s in segs)
            wall = time.perf_counter() - t0
            audio_s = len(wav) / sr
            print("%-8s rtf=%.2f (%.1fs wall / %.1fs audio, %d words)"
                  % (size, wall / audio_s, wall, audio_s, nwords))
        except Exception as e:
            print(size, "ERR", type(e).__name__, str(e)[:160])


def main() -> None:
    section_a()
    section_b()
    try:
        wav, sr = _sample_wav_seconds()
        section_c((wav * 32767).astype(np.float32) / 32767.0, sr)
    except Exception as e:
        print("sample wav unavailable:", type(e).__name__, str(e)[:160])


if __name__ == "__main__":
    main()
