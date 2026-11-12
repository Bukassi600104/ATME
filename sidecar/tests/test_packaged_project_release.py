"""Release acceptance using a frozen sidecar and genuine speech recognition.

Set ATME_FROZEN_MCP to the packaged executable. The test uses Windows speech
synthesis solely to supply a known QA recording, creates its own database,
and expects the normal English recognition model to be available offline.
"""
import asyncio
import hashlib
import io
import json
import os
import secrets
import shutil
import subprocess
import time
import urllib.error
import urllib.request
import wave
from contextlib import contextmanager
from pathlib import Path

import numpy as np
import pytest
from mcp import Client
from mcp.client.stdio import StdioServerParameters
from PIL import Image

from test_external_inputs import external_payload
from test_project_offline_render import compact_layout
from test_project_runner import storyboard

EXE = os.environ.get("ATME_FROZEN_MCP")
pytestmark = pytest.mark.skipif(
    not EXE or os.name != "nt", reason="requires a frozen Windows release and offline speech model")


def speech_recording(folder):
    # The spoken text also supplies the script against which the real aligner is checked.
    sentences = ["The queue stores each request.", "The evidence shows the result."]
    path = folder / "qa-narration.wav"
    command = """
        $ErrorActionPreference='Stop'
        $voice=New-Object -ComObject SAPI.SpVoice
        $audio=New-Object -ComObject SAPI.SpFileStream
        $audio.Format.Type=22
        $audio.Open($env:ATME_QA_WAV,3,$false)
        $voice.AudioOutputStream=$audio
        $voice.Rate=-2
        try { [void]$voice.Speak($env:ATME_QA_SPEECH) } finally { $audio.Close() }
    """
    subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
                   env={**os.environ, "ATME_QA_WAV": str(path), "ATME_QA_SPEECH": " ".join(sentences)},
                   timeout=120, check=True)
    return sentences, path.read_bytes()


@contextmanager
def packaged_server(data, log_file):
    token = secrets.token_urlsafe(32)
    env = {**os.environ, "ATME_DATA_DIR": str(data), "ATME_PORT": "0", "ATME_TOKEN": token,
           "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1"}
    env.pop("ATME_PARENT_PID", None)
    env.pop("ATME_FFMPEG", None)
    with log_file.open("wb") as log:
        started = time.monotonic()
        proc = subprocess.Popen([EXE], stdout=log, stderr=log, env=env, cwd=data.parent)
        try:
            deadline = time.monotonic() + 150
            base = None
            while time.monotonic() < deadline:
                assert proc.poll() is None, log_file.read_text(errors="replace")[-2000:]
                for line in log_file.read_text(errors="replace").splitlines():
                    if line.startswith('{"event": "ready"'):
                        base = f'http://127.0.0.1:{json.loads(line)["PORT"]}'
                        break
                if base:
                    try:
                        with urllib.request.urlopen(base + "/healthz", timeout=2) as response:
                            health = json.load(response)
                            assert health["status"] == "ok" and health["version"] == "0.1.3"
                        log_file.with_suffix(".startup.json").write_text(json.dumps({
                            "seconds_to_health": round(time.monotonic() - started, 3),
                            "sidecar_version": health["version"],
                        }), encoding="utf-8")
                        break
                    except urllib.error.URLError:
                        pass
                time.sleep(.25)
            else:
                pytest.fail(f"Packaged sidecar did not start. See {log_file}")

            def api(path, method="GET", content=None, media_type=None):
                binary = isinstance(content, bytes)
                payload = content if binary or content is None else json.dumps(content).encode()
                request = urllib.request.Request(base + path, method=method, data=payload,
                    headers={"Authorization": "Bearer " + token,
                             "Content-Type": media_type or ("audio/wav" if binary else "application/json")})
                try:
                    with urllib.request.urlopen(request, timeout=120) as response:
                        if response.headers.get_content_type() == "application/json":
                            return json.load(response)
                        return response.read()
                except urllib.error.HTTPError as exc:
                    pytest.fail(f"{method} {path}: {exc.code} {exc.read()[:1000]!r}")

            yield api
            api("/shutdown", "POST")
            assert proc.wait(timeout=30) == 0
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait()


def finished(api, collection, **payload):
    initial = api(collection, "POST", payload)
    endpoint = f'{collection}/{initial["run_id"]}'
    deadline = time.monotonic() + 360
    while time.monotonic() < deadline:
        status = api(endpoint)
        if status["status"] not in {"queued", "running"}:
            assert status["status"] == "done", status
            return status
        time.sleep(1)
    pytest.fail(f"{endpoint} did not finish within six minutes")


def test_packaged_spoken_project_in_both_profiles_and_after_restart(tmp_path):
    sentences, wav = speech_recording(tmp_path)
    script = external_payload()["script"]
    for scene, sentence in zip(script["scenes"], sentences, strict=True):
        scene["spoken_text"] = sentence
    data = tmp_path / "data"
    results = []
    with packaged_server(data, tmp_path / "initial.log") as api:
        for profile, size in [("LONG_FORM_16_9", (1280, 720)), ("SHORT_FORM_9_16", (720, 1280))]:
            state = api("/projects", "POST", {"title": "QA spoken project", "profile": profile,
                                             "input_kind": "script+audio"})
            pid = state["project_id"]
            path = f"/projects/{pid}"
            api(path + "/artifacts/script", "PUT", {"document": script, "expected_revision": 0})
            api(path + "/script-approval", "POST",
                {"expected_revision": 1, "script_revision": 1, "approved": True})
            api(path + "/media/wav?expected_revision=2", "POST", wav)
            timing = finished(api, path + "/timing", expected_revision=3)["timing"]
            context = timing["semantic_structure"]["planning_context"]
            words = [w["word"].lower().strip(".,") for scene in context["scenes"] for w in scene["words"]]
            assert {"stores", "request", "shows", "result"} <= set(words), words
            api(path + "/artifacts/storyboard", "PUT", {"document": storyboard(script), "expected_revision": 3})
            api(path + "/artifacts/layout", "PUT", {"document": compact_layout(profile), "expected_revision": 4})
            assert api(path + "/validate")["ready"]
            png = api(path + "/preview?expected_revision=5&at_ms=750")
            image = Image.open(io.BytesIO(png)).convert("RGB")
            assert image.width * size[1] == image.height * size[0]
            assert np.asarray(image).std() > 1
            (tmp_path / f"{profile}.png").write_bytes(png)
            rendered = finished(api, path + "/renders", expected_revision=5, confirmed=True)
            run_id = rendered["run_id"]
            video = api(path + f"/renders/{run_id}/output")
            digest = hashlib.sha256(video).hexdigest()
            assert rendered["manifest"]["video"] == {"bytes": len(video), "sha256": digest}
            output = tmp_path / f"{profile}.mp4"
            output.write_bytes(video)
            probe = json.loads(subprocess.check_output([shutil.which("ffprobe"), "-v", "error", "-of", "json",
                "-show_entries", "stream=codec_type,codec_name,width,height:format=duration", str(output)]))
            picture, = [s for s in probe["streams"] if s["codec_type"] == "video"]
            sound, = [s for s in probe["streams"] if s["codec_type"] == "audio"]
            assert picture["codec_name"] == "h264" and (picture["width"], picture["height"]) == size
            assert sound["codec_name"] == "aac"
            assert abs(float(probe["format"]["duration"]) - timing["final_audio"]["duration_ms"] / 1000) < .12
            ffmpeg = str(Path(EXE).parent / "_internal" / "ffmpeg" / "ffmpeg.exe")
            pcm = subprocess.check_output([ffmpeg, "-v", "error", "-i", str(output), "-vn",
                                           "-ac", "1", "-f", "f32le", "pipe:1"])
            assert np.mean(np.square(np.frombuffer(pcm, dtype="<f4"))) > .00001
            results.append({"project_id": pid, "profile": profile, "run_id": run_id, "sha256": digest,
                            "bytes": len(video), "probe": probe, "timed_words": words,
                            "timing_status": context["status"]})

    with packaged_server(data, tmp_path / "restart.log") as api:
        for item in results:
            path = f'/projects/{item["project_id"]}'
            assert api(path)["revision"] == 5
            old = api(path + "/renders", "POST", {"expected_revision": 5, "confirmed": True})
            assert old["run_id"] == item["run_id"] and old["status"] == "done"
            assert hashlib.sha256(api(path + f'/renders/{old["run_id"]}/output')).hexdigest() == item["sha256"]

    async def verify_mcp():
        params = StdioServerParameters(command=EXE, args=["mcp"], env={"ATME_DATA_DIR": str(data)})
        async with Client(params, read_timeout_seconds=60) as client:
            names = {tool.name for tool in (await client.list_tools()).tools}
            assert {"atme.preview_project", "atme.render_project", "atme.get_project_state",
                    "atme.get_visual_compilation_context"} <= names
            for item in results:
                state = await client.call_tool("atme.get_project_state", {"project_id": item["project_id"]})
                assert not state.is_error and state.structured_content["result"]["revision"] == 5
    asyncio.run(verify_mcp())
    (tmp_path / "release-evidence.json").write_text(json.dumps(results, indent=2), encoding="utf-8")


def test_packaged_talking_head_keeps_every_mastered_packet(tmp_path):
    sentences, _ = speech_recording(tmp_path)
    ffmpeg = str(Path(EXE).parent / "_internal" / "ffmpeg" / "ffmpeg.exe")
    camera = tmp_path / "camera.mp4"
    subprocess.run([ffmpeg, "-v", "error", "-f", "lavfi", "-i", "color=blue:s=320x180:r=25",
                    "-i", str(tmp_path / "qa-narration.wav"), "-shortest", "-c:v", "libx264",
                    "-pix_fmt", "yuv420p", "-c:a", "aac", str(camera)], check=True, timeout=90)
    script = external_payload()["script"]
    for scene, words in zip(script["scenes"], sentences, strict=True):
        scene["spoken_text"] = words
    data = tmp_path / "data"
    with packaged_server(data, tmp_path / "camera.log") as api:
        state = api("/projects", "POST", {"title": "QA captioned camera", "profile": "LONG_FORM_16_9",
                                         "input_kind": "script+video"})
        pid = state["project_id"]
        path = f"/projects/{pid}"
        api(path + "/artifacts/script", "PUT", {"document": script, "expected_revision": 0})
        api(path + "/script-approval", "POST", {"expected_revision": 1, "script_revision": 1, "approved": True})
        added = api(path + "/media/video?expected_revision=2", "POST", camera.read_bytes(), "video/mp4")
        api(path + "/source-timeline/commands", "POST", {"operation": "insert",
            "arguments": {"media_id": added["media"]["media_id"], "at_ms": 0},
            "expected_revision": 3, "expected_timeline_revision": 0})
        api(path + "/artifacts/storyboard", "PUT", {"document": storyboard(script), "expected_revision": 4})
        api(path + "/artifacts/layout", "PUT", {"document": compact_layout(), "expected_revision": 5})
        result = finished(api, path + "/renders", expected_revision=6, confirmed=True)
        output = tmp_path / "camera-export.mp4"
        output.write_bytes(api(path + f'/renders/{result["run_id"]}/output'))
        assert hashlib.sha256(output.read_bytes()).hexdigest() == result["manifest"]["video"]["sha256"]
        master, = data.rglob("project-runs/*/*/work/audio/final.wav")
        with wave.open(str(master)) as source:
            samples, rate = source.getnframes(), source.getframerate()
        frames = int(subprocess.check_output([shutil.which("ffprobe"), "-v", "error", "-select_streams", "v:0",
            "-show_entries", "stream=nb_frames", "-of", "csv=p=0", str(output)]))
        assert frames == (samples * 30 + rate - 1) // rate
        def packets(file, codec):
            return subprocess.check_output([ffmpeg, "-v", "error", "-i", str(file), "-map", "0:a:0",
                                            "-c:a", *codec, "-f", "adts", "pipe:1"])
        assert packets(output, ["copy"]) == packets(master, ["aac", "-b:a", "160k"])
        (tmp_path / "talking-head-evidence.json").write_text(json.dumps({
            "frames": frames, "mastered_samples": samples, "sample_rate": rate,
            "video": result["manifest"]["video"], "mastered_aac_packets_identical": True,
        }, indent=2), encoding="utf-8")
