"""First-run model fetcher: Kokoro int8 + voices into data/models, verified."""

from __future__ import annotations

import argparse
import hashlib
import shutil
import sys
from pathlib import Path

MODELS = Path("data/models")
REPO = "xybrid-ai/Kokoro-82M-v1.0-ONNX"


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def fetch_kokoro() -> list:
    MODELS.mkdir(parents=True, exist_ok=True)
    from huggingface_hub import hf_hub_download

    out = []
    for name in ("kokoro-v1.0.int8.onnx", "voices.bin"):
        dst = MODELS / name
        if dst.exists() and dst.stat().st_size > 1_000_000:
            print("[skip] " + name + " present")
            out.append(dst)
            continue
        print("[get ] " + REPO + ":" + name)
        cached = Path(hf_hub_download(REPO, name))
        shutil.copyfile(cached, dst)
        digest = _sha256(dst)
        dst.with_suffix(dst.suffix + ".sha256").write_text(digest, encoding="utf-8")
        print("[ok  ] " + name + " sha256=" + digest[:16] + "...")
        out.append(dst)
    return out


def warm_whisper() -> None:
    print("[get ] faster-whisper base.en (int8) via its own cache")
    from faster_whisper import WhisperModel

    WhisperModel("base.en", device="cpu", compute_type="int8", cpu_threads=4)
    print("[ok  ] whisper base.en cached")


def main():
    import argparse
    parser = argparse.ArgumentParser(prog="atme.fetch_models")
    parser.add_argument("--with-whisper", action="store_true")
    args = parser.parse_args(argv=None) if False else parser.parse_args(sys.argv[1:])
    try:
        fetch_kokoro()
        if args.with_whisper:
            warm_whisper()
    except Exception as exc:
        print("FETCH FAILED: %s" % exc, file=sys.stderr)
        return 1
    print("models ready under", MODELS)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())