import hashlib
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from atme.project_service import ProjectError
from atme.render.v2_sound_mix import _read_region, freeze_sources, mix_master, validate_plan
from test_v2_sound_events_project import stored_sound


def test_frozen_editorial_audio_preserves_narration_and_authored_intervals(tmp_path):
    service, project, plan, _, timeline = stored_sound(tmp_path)
    try:
        inputs = tmp_path / "inputs"
        inputs.mkdir()
        freeze_sources(service, project["project_id"], timeline, plan, inputs)
        original, _ = service.asset(project["project_id"], plan["assets"][-1]["asset_id"])
        original.unlink()  # The immutable snapshot outlives its original.
        audio_dir = tmp_path / "audio"
        audio_dir.mkdir()
        voice = audio_dir / "voice.wav"
        samples = np.sin(np.arange(160000) * (2 * np.pi * 100 / 16000)) / 2
        sf.write(voice, samples, 16000, subtype="PCM_16")
        master = {"final_wav": str(voice), "sha256": hashlib.sha256(voice.read_bytes()).hexdigest(),
                  "duration_ms": 10000}
        output = mix_master(inputs, tmp_path, plan, timeline, master)
        mixed, _ = sf.read(output["final_wav"])
        narration, _ = sf.read(voice)
        delta = mixed - narration
        level = .125 * 10 ** (-12 / 20)
        assert abs(delta[800] - .5 * level) < .0001
        assert np.allclose(delta[1600:15999], level, atol=.0001)
        assert np.allclose(delta[16000:32000], 0, atol=.0001)
        assert np.allclose(delta[32000:45000], level, atol=.0001)
        assert np.allclose(delta[48000:96000], 0, atol=.0001)
        assert np.allclose(delta[98000:108000], level, atol=.0001)
        assert output["sha256"] == hashlib.sha256(Path(output["final_wav"]).read_bytes()).hexdigest()
        source = next(inputs.glob("sound-*"))
        source.write_bytes(b"changed")
        with pytest.raises(ValueError, match="integrity"):
            mix_master(inputs, tmp_path, plan, timeline, master)
    finally:
        service.store.close()


def test_sound_requires_executable_policy_and_decodable_owned_bytes(tmp_path):
    with pytest.raises(ValueError, match="explicit playback"):
        validate_plan({"actions": [{"verb": "sound_cue", "action_id": "cue"}]})
    with pytest.raises(ValueError, match="executable action"):
        validate_plan({"actions": [], "beats": [{"beat_id": "opening", "action_ids": [],
                        "sound_intent": {"role": "music", "asset_id": "score"}}]})
    service, project, *_ = stored_sound(tmp_path)
    try:
        bad = tmp_path / "invalid.wav"
        bad.write_bytes(b"not an audio stream")
        with pytest.raises(ProjectError, match="decodable"):
            service.attach_asset_file(project["project_id"], bad, bad.name, project["revision"])
        assert service.open(project["project_id"])["revision"] == project["revision"]
    finally:
        service.store.close()


def test_stereo_source_cursor_wraps_only_inside_authored_region(tmp_path):
    left = np.arange(10, dtype=np.float32) / 10
    stereo = np.stack([left, -left], axis=1)
    source = tmp_path / "stereo.wav"
    sf.write(source, stereo, 8000, subtype="FLOAT")
    with sf.SoundFile(source) as track:
        samples = _read_region(track, 2, 5, 1, 8)
        np.testing.assert_array_equal(samples, stereo[[3, 4, 2, 3, 4, 2, 3, 4]])
