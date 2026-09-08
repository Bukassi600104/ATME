"""Cold-start warmup: pre-import every heavy dependency ONCE per sidecar process.

Measured on the target machine (i3-7100U + 5400 RPM HDD): scipy.signal alone can take >30 s to
import from a cold file cache. Lazy imports inside job stages would silently add minutes to the
first job of every app session. The orchestrator (M3) calls warm_heavy_imports() right after
sidecar spawn, before any job is accepted; stages therefore see warm modules only.
"""

from __future__ import annotations

import logging
import time

log = logging.getLogger(__name__)

HEAVY_MODULES = [
    "numpy",
    "scipy.signal",          # noisereduce backend
    "soundfile",
    "noisereduce",
    "pyloudnorm",
    "pedalboard",
    "PIL",
    "resvg_py",
    # faster_whisper / kokoro_onnx stay lazy: they additionally LOAD MODEL WEIGHTS,
    # which belongs to explicit engine init, not import.
]


def warm_heavy_imports(modules: list[str] | None = None) -> dict[str, float]:
    results: dict[str, float] = {}
    for name in modules or HEAVY_MODULES:
        t0 = time.perf_counter()
        try:
            __import__(name)
            results[name] = round((time.perf_counter() - t0) * 1000)
        except Exception as exc:  # report and continue; the owning stage fails loudly if needed
            results[name] = -1.0
            log.warning("warmup import failed for %s: %s", name, exc)
    slow = {k: v for k, v in results.items() if v > 1000}
    log.info("warmup done; slow imports: %s", slow)
    return results
