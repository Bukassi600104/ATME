from __future__ import annotations

import json

from atme.settings import ROLES, SettingsStore, protect_text, unprotect_text


def test_dpapi_round_trip():
    protected = protect_text("secret-provider-key")
    assert protected != "secret-provider-key"
    assert unprotect_text(protected) == "secret-provider-key"


def test_settings_store_never_persists_plaintext(tmp_path):
    path = tmp_path / "settings.json"
    store = SettingsStore(path)
    payload = {"roles": {
        role: {"model": "perplexity/sonar-pro" if role == "researcher" else "openai/gpt-5",
               "api_base": "", "api_key": "key-for-%s" % role,
               "web_grounded": role == "researcher"}
        for role in ROLES
    }}
    public = store.save(payload)
    assert public["configured"] is True
    raw = path.read_text(encoding="utf-8")
    assert "key-for-" not in raw
    runtime = store.runtime_roles()
    assert runtime["writer"]["api_key"] == "key-for-writer"
    assert json.loads(raw)["version"] == 1


def test_blank_key_preserves_existing_secret(tmp_path):
    store = SettingsStore(tmp_path / "settings.json")
    roles = {role: {"model": "search/model" if role == "researcher" else "model",
                    "api_key": "first", "web_grounded": role == "researcher"}
             for role in ROLES}
    store.save({"roles": roles})
    for role in ROLES:
        roles[role]["api_key"] = ""
        roles[role]["model"] += "-updated"
    store.save({"roles": roles})
    assert store.runtime_roles()["writer"]["api_key"] == "first"


def test_new_store_exposes_saveable_openrouter_defaults(tmp_path):
    store = SettingsStore(tmp_path / "settings.json")
    public = store.public()

    assert public["configured"] is False
    assert public["roles"]["researcher"] == {
        "model": "openrouter/perplexity/sonar-pro",
        "api_base": "",
        "has_api_key": False,
        "web_grounded": True,
    }
    assert public["roles"]["reasoner"]["model"] == "openrouter/openai/gpt-5.6-terra"
    assert public["roles"]["writer"]["model"] == "openrouter/openai/gpt-5.6-terra"
    assert public["roles"]["layouter"]["model"] == "openrouter/openai/gpt-5.6-luna"

    roles = public["roles"]
    for config in roles.values():
        config["api_key"] = "one-openrouter-key"
    assert store.save({"roles": roles})["configured"] is True
