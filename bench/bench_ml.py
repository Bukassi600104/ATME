"""ATME ML kill-switch benchmark (M0 gate).

Downloads (once) the Kokoro-82M int8 ONNX model + voice bank, then measures on THIS machine:
  - Kokoro synthesis RTF = wall_time / audio_duration   (gate: <= 3.0)
  - faster-whisper base.en int8 word-alignment RTF      (gate: <= 1.5)

Appends a timestamped section to docs/CALIBRATION.md and prints the verdict.
Usage:
    python bench/bench_ml.py [--skip-download]
"""

from __future__ import annotations

import argparse
import datetime as dt
import tempfile
import time
from pathlib import Path

import numpy as np
import soundfile as sf

REPO = Path(__file__).resolve().parents[1]
DOC = REPO / "docs" / "CALIBRATION.md"
MODELS = REPO / "data" / "models"

TEXTS = [
    "Scaling large language models pushes infrastructure into a corner.",
    "You are fighting a trilemma: throughput against latency against cost.",
    "The memory wall is the tax you pay every single time a token moves.",
    "PagedAttention treats the KV cache like virtual memory pages.",
    "Continuous batching keeps the GPU fed without waiting for a whole batch to finish.",
    "That is roughly double the serving throughput on identical hardware.",
]
VOICE = "af_heart"
KOKORO_REPO = "xybrid-ai/Kokoro-82M-v1.0-ONNX"
MODEL_CANDIDATES = ["kokoro-v1.0.int8.onnx"]
VOICES_CANDIDATES = ["voices.bin"]


def download():
    from huggingface_hub import hf_hub_download

    MODELS.mkdir(parents=True, exist_ok=True)
    model_path = voices_path = None
    for name in MODEL_CANDIDATES:
        try:
            model_path = Path(hf_hub_download(KOKORO_REPO, name))
            break
        except Exception:
            continue
    for name in VOICES_CANDIDATES:
        try:
            voices_path = Path(hf_hub_download(KOKORO_REPO, name))
            break
        except Exception:
            continue
    if not model_path or not voices_path:
        raise SystemExit("could not download Kokoro model/voices from HuggingFace")
    # materialize into data/models so tts_kokoro defaults (and later milestones) find them
    import shutil

    MODELS.mkdir(parents=True, exist_ok=True)
    dst_m = MODELS / "kokoro-v1.0.int8.onnx"
    dst_v = MODELS / "voices.bin"
    if not dst_m.exists():
        shutil.copyfile(model_path, dst_m)
    if not dst_v.exists():
        shutil.copyfile(voices_path, dst_v)
    return dst_m, dst_v


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-download", action="store_true")
    args = parser.parse_args()

    local_model = MODELS / "kokoro-v1.0.int8.onnx"
    local_voices = MODELS / "voices.bin"
    if args.skip_download and local_model.exists() and local_voices.exists():
        mp, vp = local_model, local_voices
    else:
        print("downloading models (first run only)...")
        mp, vp = download()

    # ---- Kokoro synthesis RTF ----
    from atme.audio import tts_kokoro

    t0 = time.perf_counter()
    engine = tts_kokoro.get_engine(mp, vp)
    load_s = time.perf_counter() - t0
    engine.create(TEXTS[0], voice=VOICE, lang="en-us")  # warm-up incl. espeak init

    chunks = []
    scratch = tempfile.mkdtemp()
    t0 = time.perf_counter()
    for text in TEXTS:
        samples, sr = tts_kokoro.synthesize(text, voice=VOICE, use_cache=False, cache_dir=scratch)
        chunks.append((samples, sr))
    synth_wall = time.perf_counter() - t0
    audio_s = sum(len(s) / sr for s, sr in chunks)
    kokoro_rtf = synth_wall / audio_s if audio_s else float("inf")

    wav = np.concatenate([s for s, _sr in chunks])
    sr = chunks[0][1]

    # ---- faster-whisper alignment RTF ----
    from atme.audio.align import align_words

    t0 = time.perf_counter()
    words = align_words(wav, sr, scene_starts_ms=[1])
    align_wall = time.perf_counter() - t0
    align_rtf = align_wall / audio_s if audio_s else float("inf")

    stamp = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    total_words = sum(len(t.split()) for t in TEXTS)
    kokoro_pass = kokoro_rtf <= 3.0
    align_pass = align_rtf <= 1.5
    nl = chr(10)
    lines = [
        "", "## Run " + stamp + " (ML kill-switch)", "",
        "| Metric | Result | Gate | Verdict |", "|---|---|---|---|",
        "| Kokoro-82M int8 load time | %.1f s | - | - |" % load_s,
        "| Kokoro synthesis RTF (%.1fs audio, %d phrases) | %.2f x realtime | <= 3.0 | %s |"
        % (audio_s, len(TEXTS), kokoro_rtf, "PASS" if kokoro_pass else "FAIL -> pivot VO-first"),
        "| Kokoro throughput | %.1f words/s | - | - |" % (total_words / synth_wall),
        "| whisper base.en int8 align RTF (%d words) | %.2f x realtime | <= 1.5 | %s |"
        % (len(words), align_rtf, "PASS" if align_pass else "FAIL -> try tiny.en"),
        "| Alignment sanity | %d/%d words | - | %s |"
        % (len(words), total_words,
           "plausible" if len(words) >= total_words * 0.6 else "review manually"),
    ]
    with DOC.open("a", encoding="utf-8") as fh:
        fh.write(nl.join(lines) + nl)
    print(nl.join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
