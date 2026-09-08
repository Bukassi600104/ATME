"""Isolate: does sapi_synthesize hang when a uvicorn server runs in this process?"""

import sys
import tempfile
import threading
import time
from pathlib import Path

sys.path.insert(0, "sidecar/src")

mode = sys.argv[1] if len(sys.argv) > 1 else "with-uvicorn"

if mode == "with-uvicorn":
    import uvicorn
    from atme.server.app import create_app
    app = create_app(token="T")
    config = uvicorn.Config(app, host="127.0.0.1", port=0, log_level="error")
    server = uvicorn.Server(config)
    threading.Thread(target=server.run, daemon=True).start()
    while not server.started:
        time.sleep(0.05)
    print("uvicorn started", flush=True)

from atme.audio.tts_sapi import sapi_synthesize

out = Path(tempfile.mkdtemp()) / "probe.wav"
print("synthesizing...", flush=True)
t0 = time.time()
sapi_synthesize("Quick probe sentence for the draft voice.", out, rate=1)
print("DONE in %.2fs ->" % (time.time() - t0), out, out.stat().st_size, "bytes", flush=True)