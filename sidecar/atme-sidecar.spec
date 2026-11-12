# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for the ATME sidecar server (onedir).
# Build:  cd sidecar && ..\.sidecar\.venv\Scripts\pyinstaller.exe --noconfirm atme-sidecar.spec

import sys
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files

block_cipher = None
ROOT = Path(SPECPATH).resolve().parent
SRC = ROOT / "sidecar" / "src"
sys.path.insert(0, str(SRC))
from atme.ffmpeg import find_ffmpeg

ffmpeg = find_ffmpeg()
if not ffmpeg or not Path(ffmpeg).is_file():
    raise SystemExit("A standalone FFmpeg executable is required to build the installer")
ffmpeg_dir = Path(ffmpeg).parent
if ffmpeg_dir.name.lower() == "bin":
    ffmpeg_dir = ffmpeg_dir.parent
notices = [(str(ffmpeg_dir / name), "ffmpeg") for name in ("LICENSE", "README.txt")
           if (ffmpeg_dir / name).is_file()]

a = Analysis(
    [str(ROOT / "sidecar" / "launcher.py")],
    pathex=[str(SRC)],
    binaries=[(ffmpeg, "ffmpeg")],
    datas=[(str(ROOT / "schemas"), "schemas"),
           (str(ROOT / "prompts"), "prompts"),
           (str(ROOT / "production-assets"), "production-assets")]
           + collect_data_files("faster_whisper", includes=["assets/*.onnx"]) + notices,
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
