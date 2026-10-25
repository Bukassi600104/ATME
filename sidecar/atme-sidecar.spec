# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for the ATME sidecar server (onedir).
# Build:  cd sidecar && ..\.sidecar\.venv\Scripts\pyinstaller.exe --noconfirm atme-sidecar.spec

import os
import shutil
from pathlib import Path

block_cipher = None
ROOT = Path(SPECPATH).parent                      # repo root
VENV = ROOT / "sidecar" / ".venv"


def find_ffmpeg():
    cand = os.environ.get("ATME_FFMPEG")
    if cand and Path(cand).exists():
        return cand
    import shutil as _sh
    w = _sh.which("ffmpeg")
    if w:
        return w
    local = os.environ.get("LOCALAPPDATA", "")
    if local:
        for d in sorted(Path(local).glob("Microsoft/WinGet/Packages/Gyan.FFmpeg*")):
            hits = list(d.rglob("bin/ffmpeg.exe")) or list(d.rglob("ffmpeg.exe"))
            if hits:
                return str(hits[0])
    raise SystemExit("ffmpeg not found - required to bundle")


a = Analysis(
    ["launcher.py"],
    pathex=["src"],
    binaries=[(find_ffmpeg(), "ffmpeg")],
    datas=[(str(ROOT / "schemas"), "schemas"),
           (str(ROOT / "prompts"), "prompts"),
           (str(ROOT / "production-assets"), "production-assets")],
    hiddenimports=[
        "uvicorn.logging",
        "uvicorn.loops",
        "uvicorn.loops.auto",
        "uvicorn.protocols",
        "uvicorn.protocols.http",
        "uvicorn.protocols.http.auto",
        "uvicorn.protocols.websockets",
        "uvicorn.protocols.websockets.auto",
        "uvicorn.lifespan",
        "uvicorn.lifespan.on",
        "kokoro_onnx",
        "resvg_py",
        "atme.render.style_bundle",
        "atme.render.style_contracts",
    ],
    hookspath=[],
    runtime_hooks=[],
    # Internal model routing is retired in V4. Keep the old source adapter for
    # migration tests, but never ship LiteLLM or provider integrations.
    excludes=["litellm", "tkinter", "matplotlib.tests", "pytest"],
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="atme-sidecar",
    debug=False,
    strip=False,
    upx=False,
    console=True,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    name="atme-sidecar",
)
