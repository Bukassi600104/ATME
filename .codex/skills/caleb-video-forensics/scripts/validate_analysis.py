"""Validate one or more reference-video analysis JSON documents."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from jsonschema import Draft202012Validator


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("files", nargs="+")
    parser.add_argument("--schema", default=None)
    args = parser.parse_args(argv)

    root = Path(__file__).resolve().parents[4]
    schema_path = Path(args.schema) if args.schema else root / "schemas" / "reference-video-analysis.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema)
    failed = False
    for raw_path in args.files:
        path = Path(raw_path)
        doc = json.loads(path.read_text(encoding="utf-8"))
        errors = sorted(validator.iter_errors(doc), key=lambda e: list(e.path))
        if errors:
            failed = True
            for error in errors:
                where = ".".join(str(part) for part in error.path) or "<root>"
                print(f"{path}:{where}: {error.message}", file=sys.stderr)
        else:
            print(f"OK {path}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
