"""Per-user ATME settings with Windows DPAPI protection for provider secrets."""

from __future__ import annotations

import base64
import ctypes
import json
import os
import threading
from ctypes import wintypes
from pathlib import Path

ROLES = ("researcher", "reasoner", "writer", "layouter")

DEFAULT_ROLES = {
    "researcher": {
        "model": "openrouter/perplexity/sonar-pro",
        "api_base": "",
        "web_grounded": True,
    },
    "reasoner": {
        "model": "openrouter/openai/gpt-5.6-terra",
        "api_base": "",
        "web_grounded": False,
    },
    "writer": {
        "model": "openrouter/openai/gpt-5.6-terra",
        "api_base": "",
        "web_grounded": False,
    },
    "layouter": {
        "model": "openrouter/openai/gpt-5.6-luna",
        "api_base": "",
        "web_grounded": False,
    },
}


class SettingsError(ValueError):
    pass


class _Blob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD),
                ("pbData", ctypes.POINTER(ctypes.c_ubyte))]


def _blob(data: bytes) -> tuple[_Blob, ctypes.Array]:
    buffer = ctypes.create_string_buffer(data)
    value = _Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    return value, buffer


def _dpapi(data: bytes, protect: bool) -> bytes:
    if os.name != "nt":
        raise SettingsError("secure provider-key storage requires Windows")
    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    crypt32.CryptProtectData.restype = wintypes.BOOL
    crypt32.CryptUnprotectData.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = [wintypes.HLOCAL]
    kernel32.LocalFree.restype = wintypes.HLOCAL
    input_blob, keepalive = _blob(data)
    output_blob = _Blob()
    if protect:
        ok = crypt32.CryptProtectData(
            ctypes.byref(input_blob), "ATME provider key", None, None, None, 0,
            ctypes.byref(output_blob))
    else:
        ok = crypt32.CryptUnprotectData(
            ctypes.byref(input_blob), None, None, None, None, 0,
            ctypes.byref(output_blob))
    del keepalive
    if not ok:
        raise OSError(ctypes.get_last_error(), "Windows DPAPI operation failed")
    try:
        return ctypes.string_at(output_blob.pbData, output_blob.cbData)
    finally:
        kernel32.LocalFree(output_blob.pbData)


def protect_text(value: str) -> str:
    return base64.b64encode(_dpapi(value.encode("utf-8"), True)).decode("ascii")


def unprotect_text(value: str) -> str:
    return _dpapi(base64.b64decode(value), False).decode("utf-8")


class SettingsStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    def _read(self) -> dict:
        with self._lock:
            if not self.path.exists():
                return {"version": 1, "roles": {}}
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise SettingsError("provider settings are unreadable") from exc
            if data.get("version") != 1 or not isinstance(data.get("roles"), dict):
                raise SettingsError("unsupported provider settings format")
            return data

    def public(self) -> dict:
        data = self._read()
        roles = {}
        for role in ROLES:
            config = data["roles"].get(role, {})
            defaults = DEFAULT_ROLES[role]
            roles[role] = {
                "model": config.get("model") or defaults["model"],
                "api_base": config.get("api_base", defaults["api_base"]),
                "has_api_key": bool(config.get("api_key_dpapi")),
                "web_grounded": bool(config.get("web_grounded", defaults["web_grounded"])),
            }
        return {"configured": self.configured(), "roles": roles}

    def configured(self) -> bool:
        data = self._read()
        return all(data["roles"].get(role, {}).get("model") and
                   data["roles"].get(role, {}).get("api_key_dpapi") for role in ROLES)

    def save(self, payload: dict) -> dict:
        incoming = payload.get("roles")
        if not isinstance(incoming, dict):
            raise SettingsError("roles object is required")
        current = self._read()
        saved = {"version": 1, "roles": {}}
        for role in ROLES:
            raw = incoming.get(role)
            if not isinstance(raw, dict):
                raise SettingsError("missing provider role: %s" % role)
            model = str(raw.get("model") or "").strip()
            if not model:
                raise SettingsError("%s model is required" % role)
            key = str(raw.get("api_key") or "").strip()
            encrypted = (protect_text(key) if key else
                         current["roles"].get(role, {}).get("api_key_dpapi"))
            if not encrypted:
                raise SettingsError("%s API key is required" % role)
            saved["roles"][role] = {
                "model": model,
                "api_base": str(raw.get("api_base") or "").strip(),
                "api_key_dpapi": encrypted,
                "web_grounded": bool(raw.get("web_grounded", role != "researcher")),
            }
        if not saved["roles"]["researcher"]["web_grounded"]:
            raise SettingsError("researcher must use a web-grounded endpoint")
        temp = self.path.with_suffix(self.path.suffix + ".tmp")
        with self._lock:
            temp.write_text(json.dumps(saved, indent=2), encoding="utf-8")
            os.replace(temp, self.path)
        return self.public()

    def runtime_roles(self) -> dict:
        data = self._read()
        if not self.configured():
            raise SettingsError("AI providers are not configured")
        return {
            role: {
                "model": data["roles"][role]["model"],
                "api_base": data["roles"][role].get("api_base") or None,
                "api_key": unprotect_text(data["roles"][role]["api_key_dpapi"]),
                "web_grounded": bool(data["roles"][role].get("web_grounded")),
            }
            for role in ROLES
        }
