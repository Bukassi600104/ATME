"""Capture independent pre-replay frame/pixel goldens from frozen commit 965d27c.

Run once deliberately: sidecar/.venv/Scripts/python.exe bench/verify_v2_replay_parity.py --record
This mechanically generated test evidence does not certify creative acceptance.
The retained JSON is verified by tests without Git or a duplicate legacy sampler.
"""

from __future__ import annotations

import json
import subprocess
import sys
import types
from dataclasses import asdict
from hashlib import sha256
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "sidecar/src"), str(ROOT / "sidecar/tests")]

from test_v2_timeline_replay import legacy_parity_documents, parity_moments

from atme.render import v2_svg


def main():
    if sys.argv[1:] != ["--record"]:
        raise SystemExit("Use --record only to deliberately regenerate the frozen-commit oracle")
    source = subprocess.run(["git", "show", "965d27c:sidecar/src/atme/render/v2_state.py"],
                            cwd=ROOT, capture_output=True, check=True).stdout
    if (sha256(source).hexdigest() != "edd2fa7ef50faa4d54adc65efe3ee27c78121c02dd6b0e1c6a4d7e126987a8c5"
            or b"replay_chronology" in source):
        raise AssertionError("Oracle must be the independent pre-route evaluator, never the new kernel")
    legacy = types.ModuleType("atme.render._legacy_replay_oracle")
    sys.modules[legacy.__name__] = legacy
    exec(compile(source, "965d27c/v2_state.py", "exec"), legacy.__dict__)  # noqa: S102 -- exact hash-pinned repository oracle
    evidence = {"source_commit": "965d27c", "evaluator_sha256": sha256(source).hexdigest(),
                "scope": "immutable source-runtime parity; not creative/installed acceptance", "cases": {}}
    for case in ("reveal", "write", "draw", "enter", "exit", "move", "scale", "rotate", "fade",
                 "replace", "morph", "highlight", "cross_out", "dim", "isolate", "connect",
                 "annotation", "leader", "list", "static_group", "camera_cut", "camera_hold", "camera_zoom",
                 "camera_pan", "camera_reframe", "insert_evidence", "return_board"):
        layout, timeline = legacy_parity_documents(case)
        hashes = {}
        for at in parity_moments(timeline):
            snapshot = asdict(legacy.evaluate_frame(layout, timeline, at))
            normalized = json.dumps(snapshot, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
            hashes[str(at)] = sha256(normalized).hexdigest()
        record = {"frames": hashes, "layout": layout, "timeline": timeline,
                  "layout_sha256": sha256(json.dumps(layout, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest(),
                  "timeline_sha256": sha256(json.dumps(timeline, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()}
        if case in {"replace", "morph", "isolate", "leader", "camera_cut", "camera_zoom"}:
            last = timeline["actions"][-1]
            pixels = {}
            with patch.object(v2_svg, "evaluate_frame", legacy.evaluate_frame):
                for at in (last["start_ms"], (last["start_ms"] + last["end_ms"]) // 2, last["end_ms"] + 1):
                    pixels[str(at)] = {"svg": sha256(v2_svg.compose_svg_frame(layout, timeline, at).svg.encode()).hexdigest(),
                                       "png": sha256(v2_svg.compose_png_frame(layout, timeline, at).png).hexdigest()}
            record["pixels"] = pixels
        evidence["cases"][case] = record
    path = ROOT / "sidecar/tests/fixtures/v2-replay-legacy-goldens.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
    print(f"Recorded {len(evidence['cases'])} independent pre-route operator cases at {path}")


if __name__ == "__main__":
    main()
