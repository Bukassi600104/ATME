"""ATME sidecar CLI (M1).

    python -m atme.cli run --script tests/fixtures/fixture-script.json --job-dir data/jobs/fixture1
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="atme")
    sub = parser.add_subparsers(dest="cmd", required=True)

    run_p = sub.add_parser("run", help="run the media pipeline on a fixture script")
    run_p.add_argument("--script", default=None)
    run_p.add_argument("--topic", default=None,
                       help="run cognitive phase (research->script->layout) for this topic")
    run_p.add_argument("--provider", default="fake", choices=["fake", "litellm"],
                       help="cognitive backend; litellm needs --providers-json")
    run_p.add_argument("--providers-json", default=None,
                       help='{"researcher": {"model": "perplexity/sonar-pro"}, ...}')
    run_p.add_argument("--job-dir", required=True)
    run_p.add_argument("--width", type=int, default=1280)
    run_p.add_argument("--height", type=int, default=720)
    run_p.add_argument("--fps", type=int, default=30)
    run_p.add_argument("--layout", default=None)
    run_p.add_argument("--no-warm", action="store_true", help="skip pre-importing heavy deps (dev only)")
    run_p.add_argument("-v", "--verbose", action="store_true")

    sub.add_parser("version")

    args = parser.parse_args(argv)
    if args.cmd == "run" and not args.script and not args.topic:
        parser.error("--script or --topic is required")
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    if args.cmd == "version":
        from atme import __version__

        print(__version__)
        return 0

    from atme import warmup

    if not getattr(args, "no_warm", False):
        warmup.warm_heavy_imports()

    script_dict = layout_dict = None
    if args.topic:
        from atme import cognitive

        if args.provider == "litellm":
            if not args.providers_json:
                sys.exit("--provider litellm requires --providers-json")
            cfg = json.loads(Path(args.providers_json).read_text(encoding="utf-8"))
            from atme.gateway.router import RoleConfig, make_litellm_complete

            completes = {role: make_litellm_complete(role, RoleConfig(**cfg[role]))
                         for role in ("reasoner", "researcher", "writer")}
        else:
            completes = None  # FakeCognitiveProvider inside

        cog = cognitive.run_cognitive(args.topic, Path(args.job_dir), completes=completes)
        script_dict = cog["script_doc"]
        layout_dict = cog["layout_doc"]

        from atme.audio.tts_sapi import synthesize_scenes

        seg_dir = Path(args.job_dir) / "segments"
        if not any(seg_dir.glob("scene*.wav")):
            synthesize_scenes(script_dict["scenes"], seg_dir)

    from atme.pipeline import run_pipeline

    manifest = run_pipeline(args.script, args.job_dir, width=args.width, height=args.height,
                            fps=args.fps, layout_path=args.layout,
                            script_dict=script_dict, layout_dict=layout_dict)
    print(json.dumps(manifest, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())