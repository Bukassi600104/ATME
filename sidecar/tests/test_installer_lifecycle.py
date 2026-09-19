import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_nsis_stops_atme_processes_before_install_and_uninstall():
    config = json.loads((ROOT / "app" / "src-tauri" / "tauri.conf.json").read_text(encoding="utf-8"))
    hook_relative = config["bundle"]["windows"]["nsis"]["installerHooks"]
    hook_path = (ROOT / "app" / "src-tauri" / hook_relative).resolve()
    assert hook_path.is_relative_to((ROOT / "app" / "src-tauri").resolve())

    hooks = hook_path.read_text(encoding="utf-8")
    assert "!macro NSIS_HOOK_PREINSTALL" in hooks
    assert "!macro NSIS_HOOK_PREUNINSTALL" in hooks
    for process_name in ("atme-app.exe", "atme-sidecar.exe"):
        assert hooks.count(f'/IM "{process_name}"') == 2
    assert hooks.count("/T /F") == 4
