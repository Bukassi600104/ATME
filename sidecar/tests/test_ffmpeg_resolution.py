import sys

import pytest

from atme.ffmpeg import find_ffmpeg


def test_scoop_launcher_resolves_to_standalone_binary(tmp_path, monkeypatch):
    command = tmp_path / "shims" / "ffmpeg.exe"
    command.parent.mkdir()
    command.touch()
    real = tmp_path / "bin" / "ffmpeg.exe"
    real.parent.mkdir()
    real.touch()
    command.with_suffix(".shim").write_text(f'path = "{real}"\n', encoding="utf-8")
    monkeypatch.delenv("ATME_FFMPEG", raising=False)
    monkeypatch.setattr("shutil.which", lambda name: str(command))
    assert find_ffmpeg() == str(real.resolve())
    command.with_suffix(".shim").write_text('path = "missing.exe"', encoding="utf-8")
    with pytest.raises(ValueError, match="standalone target"):
        find_ffmpeg()


def test_packaged_binary_precedes_host_path(tmp_path, monkeypatch):
    hosted = tmp_path / "unrelated.exe"
    bundled = tmp_path / "_internal" / "ffmpeg" / "ffmpeg.exe"
    bundled.parent.mkdir(parents=True)
    bundled.touch()
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "atme-sidecar.exe"))
    monkeypatch.setattr("shutil.which", lambda command: str(hosted))
    monkeypatch.delenv("ATME_FFMPEG", raising=False)
    assert find_ffmpeg() == str(bundled.resolve())
