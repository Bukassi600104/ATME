"""Durable checkpoints for a single immutable v2 render snapshot."""
import json

from atme.project_assets import _sha256


def _save(path, value):
    pending = path.with_suffix(".pending.json")
    pending.write_text(json.dumps(value), encoding="utf-8")
    pending.replace(path)


def encode_segments(directory, fingerprint, total_frames, segment_frames, encode):
    directory.mkdir(exist_ok=True, parents=True)
    segments = []
    progress = {"total_frames": total_frames, "frames_done": 0, "reused_segments": 0}
    _save(directory / "progress.json", progress)
    for start in range(0, total_frames, segment_frames):
        stop = min(start + segment_frames, total_frames)
        identity = {"fingerprint": fingerprint, "start_frame": start, "end_frame": stop}
        path = directory / f"part-{start:08}.mp4"
        record = path.with_suffix(".json")
        try:
            saved = json.loads(record.read_text(encoding="utf-8"))
            reusable = (saved["identity"] == identity and path.stat().st_size == saved["bytes"]
                        and saved["bytes"] > 0 and _sha256(path) == saved["sha256"])
        except (OSError, KeyError, TypeError, ValueError):
            reusable = False
        if reusable:
            progress["reused_segments"] += 1
        else:
            pending = path.with_suffix(".pending.mp4")
            try:
                encode(pending, start, stop)
                if not pending.stat().st_size:
                    raise ValueError("The encoder returned an empty video segment")
                checksum = _sha256(pending)
                pending.replace(path)
                _save(record, {"identity": identity, "sha256": checksum, "bytes": path.stat().st_size})
            finally:
                pending.unlink(missing_ok=True)
        segments.append({"path": str(path), "frames": stop-start, "resumed": reusable})
        progress["frames_done"] = stop
        _save(directory / "progress.json", progress)
    return segments
