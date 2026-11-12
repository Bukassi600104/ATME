import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def test_nsis_uses_path_scoped_process_check():
    config = json.loads((ROOT / "app" / "src-tauri" / "tauri.conf.json").read_text(encoding="utf-8"))
    hook_relative = config["bundle"]["windows"]["nsis"]["installerHooks"]
    hook_path = (ROOT / "app" / "src-tauri" / hook_relative).resolve()
    assert hook_path.is_relative_to((ROOT / "app" / "src-tauri").resolve())

    hooks = hook_path.read_text(encoding="utf-8")
    assert "!macroundef CheckIfAppIsRunning" in hooks
    assert 'close-installed-atme.ps1" -InstallDir "$INSTDIR"' in hooks
    assert "/IM " not in hooks


@pytest.mark.skipif(os.name != "nt", reason="Windows installer")
def test_installer_leaves_other_copy_running(tmp_path):
    processes = []
    paths = [tmp_path / "install target", tmp_path / "other copy"]
    try:
        for directory in paths:
            directory.mkdir()
            executable = directory / "atme-sidecar.exe"
            shutil.copyfile(Path(os.environ["SystemRoot"]) / "System32" / "ping.exe", executable)
            processes.append(subprocess.Popen([str(executable), "-t", "127.0.0.1"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW))
        helper = ROOT / "app" / "src-tauri" / "windows" / "close-installed-atme.ps1"
        subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                        "-File", str(helper), "-InstallDir", str(paths[0])], check=True, timeout=45)
        assert processes[0].poll() is not None
        assert processes[1].poll() is None
    finally:
        for process in processes:
            if process.poll() is None:
                process.terminate()
            process.wait(timeout=5)
