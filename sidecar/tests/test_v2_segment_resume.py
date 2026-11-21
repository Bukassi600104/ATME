import json
import pytest


def test_interrupted_encode_resumes_valid_segments_and_replaces_corruption(tmp_path):
    from atme.render.v2_segments import encode_segments

    calls = []
    def encoder(path, start, stop):
        calls.append(start)
        if start == 10 and len(calls) == 2:
            raise RuntimeError("interrupted")
        path.write_bytes(bytes(range(start, stop)))
    with pytest.raises(RuntimeError, match="interrupted"):
        encode_segments(tmp_path, "same", 24, 10, encoder)
    parts = encode_segments(tmp_path, "same", 24, 10, encoder)
    assert calls == [0,10,10,20] and [part["resumed"] for part in parts] == [True,False,False]
    from pathlib import Path
    Path(parts[1]["path"]).write_bytes(b"corruption")
    calls.clear()
    encode_segments(tmp_path, "same", 24, 10, encoder)
    assert calls == [10]
    progress = json.loads((tmp_path/"progress.json").read_text())
    assert progress["frames_done"] == progress["total_frames"] == 24 and progress["reused_segments"] == 2
