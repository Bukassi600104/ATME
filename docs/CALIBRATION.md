# Calibration — measured performance envelope (i3-7100U, 16 GB, HDD)

All defaults in PROJECT_PLAN.md §6 are provisional until filled by bench/calibrate.py.
Kill-switch gates (M0): Kokoro RTF > 3x real-time OR render < 4 fps @ 720p30 => pivot defaults
to VO-upload-first + 720p24 before building further.

| Metric | Provisional budget | Measured | Date |
|---|---|---|---|
| FFmpeg libx264 encode 720p30 preset fast CRF21 | >= 60 fps | pending | - |
| FFmpeg libx264 encode 1080p30 preset fast CRF21 | >= 20 fps | pending | - |
| Kokoro-82M int8 synthesis RTF (lower is better) | <= 3.0 | pending (needs install) | - |
| faster-whisper base.en int8 alignment RTF | <= 1.5 | pending (needs install) | - |
| Polish chain minutes per minute of audio | <= 1.5 | pending | - |
| Animator frames/sec 720p30 (layered compositor) | >= 8 fps | pending (M1) | - |

Method notes: encoder numbers below come from synthetic lavfi frames piped straight into
libx264 (worst-case dense motion); real whiteboard content compresses easier, so treat them as
a floor. ML benches are appended by the same script once their optional dependencies are installed.

## M0 findings & locked defaults (measured 2026-08-23)

x264 preset sweep @720p30 CRF23, 8 s synthetic clip, this machine:

| preset | fps |
|---|---|
| ultrafast | 131.6 |
| **superfast** | **66.4** |
| veryfast | 55.2 |
| faster | 27.6 |
| fast | 23.2 |
| medium | 21.6 |

Decisions:
- **Assembly preset locks to superfast, CRF 21** (not the provisionally assumed fast):
  encoder throughput ~3x higher and stops being any kind of bottleneck for an 8+ fps animator;
  whiteboard-style content (large static regions) loses almost nothing at superfast.
- The provisional "encode >= 60 fps" floor was mis-set against fast; the meaningful gate is that
  ENCODING must never be slower than the ANIMATOR. Re-checked at M1 against the real bake rate.
- System RAM showed 75% load in a normal desktop state - confirms the commit-charge guardrail (S2).

## Run 2026-08-23 17:33

- ffmpeg: C:\Users\USER\AppData\Local\Microsoft\WinGet\Packages\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-8.1-full_build\bin\ffmpeg.EXE
- system: AMD64 | 4 threads | RAM 16GB (75% load) | 11

| Metric | Result | Note |
|---|---|---|
| libx264 encode 720p30 fast CRF21 | 23.4 fps | floor >= 60 fps: BELOW floor |
| libx264 encode 1080p30 fast CRF21 | 13.1 fps | floor >= 20 fps |
| Kokoro TTS | - | SKIPPED - extra not installed |
| onnxruntime | - | SKIPPED - extra not installed |
| faster-whisper | - | SKIPPED - extra not installed |
| cairosvg | - | SKIPPED - extra not installed |
| noisereduce | - | SKIPPED - extra not installed |
| pedalboard | - | SKIPPED - extra not installed |

## Run 2026-08-23 18:15 (render bake rate)

| Run | Frames | Wall s | Bake fps | Gate >= 8 fps |
|---|---|---|---|---|
| cold | 240 | 110.22 | 2.2 | **FAIL** |
| warm | 240 | 103.61 | 2.3 | **FAIL** |

Verdict: **FAIL** (2.2 fps worst-case)

## Run 2026-08-23 18:22 (render bake rate)

| Run | Frames | Wall s | Bake fps | Gate >= 8 fps |
|---|---|---|---|---|
| cold | 240 | 127.65 | 1.9 | **FAIL** |
| warm | 240 | 97.96 | 2.5 | **FAIL** |

Verdict: **FAIL** (1.9 fps worst-case)

## Run 2026-08-23 18:23 (ML kill-switch)

| Metric | Result | Gate | Verdict |
|---|---|---|---|
| Kokoro-82M int8 load time | 19.1 s | - | - |
| Kokoro synthesis RTF (24.9s audio, 6 phrases) | 15.77 x realtime | <= 3.0 | FAIL -> pivot VO-first |
| Kokoro throughput | 0.2 words/s | - | - |
| whisper base.en int8 align RTF (67 words) | 6.50 x realtime | <= 1.5 | FAIL -> try tiny.en |
| Alignment sanity | 67/66 words | - | plausible |

## Gate decisions after diagnostics (2026-08-23, round 2)

1. **Whisper alignment: SOLVED by configuration.** The 6.50x RTF was a default-threads artifact.
   With `cpu_threads=4` (now wired via ATME_WHISPER_THREADS in atme.audio.align): base.en int8
   **RTF 0.34**, tiny.en 0.13 -> gate <=1.5 PASSES with base.en quality. Keep base.en default.
2. **Kokoro TTS: PIVOT CONFIRMED (kill-switch fired).** 15.77x realtime is structural:
   kokoro_onnx.Kokoro exposes no ONNX session/thread options, so this cannot be tuned without an
   upstream patch or fork. Per the M0 gate, defaults pivot to VO-upload-first; local TTS ships as
   an experimental option (and the phrase cache still helps there). Revisit only if an upstream
   thread knob lands or we vendor the session creation.
3. **Renderer: PASS after architecture fix, not compromise.** Naive full-frame re-rasterization
   measured 2.2 fps (resvg = 83% of frame cost; ~99 ms floor even for a flat rect on this CPU).
   Implemented ADR-0001 properly: epoch-layer caching + static-camera frame cache + RGB pipeline.
   Result: **22.5-23.6 fps baked @720p30** vs >=8 gate. Overlay frames (~120 ms) occur only while
   a stroke is actively drawing.
   Regression-guarded by sidecar/tests/test_render_smoke.py (pixel-level QA incl. determinism).

## M1 end-to-end pipeline timings (fixture: 3 scenes, ~20 s VO -> 14.8 s MP4, 2026-08-23)

Cold-import discovery on this HDD: scipy.signal >30 s, noisereduce ~22 s, pedalboard ~4 s from
cold cache. Fix: atme/warmup.py pre-imports all heavy modules once per process (the long-lived
sidecar design paying off exactly as planned).

| Stage | First run (cold) | Warm run | Note |
|---|---|---|---|
| voice load + concat | 0.01 s | 0.01 s | SAPI segments 24 kHz |
| polish (denoise+slice+dynamics+LUFS) | **59.0 s** | **0.73 s** | cold imports eliminated |
| align (incl. model load) | 29.5 s | 9.7 s | base.en int8; model stays warm in-process |
| autolayout | 0.04 s | 0.00 s | deterministic |
| render 455 frames @720p30 | 36.4 s (13.3 fps) | 33.3 s (13.7 fps) | overlay-heavy fixture |
| assemble (mux AAC) | 3.0 s | 2.0 s | -faststart |
| **Total wall** | **128.1 s** | **45.9 s** | 2.8x faster warm |

Projection for an 8-minute video at these rates: align scales linearly (~4 min), render scales
with frames (~13 min at 13.7 fps), audio stages near-linear (<1 min). Cognitive phase adds the
online LLM time on top. Comfortably within the revised budgets.

## Run 2026-08-23 18:30 (render bake rate)

| Run | Frames | Wall s | Bake fps | Gate >= 8 fps |
|---|---|---|---|---|
| cold | 240 | 10.68 | 22.5 | PASS |
| warm | 240 | 10.16 | 23.6 | PASS |

Verdict: **PASS** (22.5 fps worst-case)
