# Calibration harness

Run after any hardware/driver change and at every milestone gate:

    sidecar\.venv\Scripts\python.exe bench\calibrate.py --seconds 10

Appends a timestamped section to docs/CALIBRATION.md. Encoder numbers use synthetic dense-motion
frames, so treat them as a worst-case floor; real whiteboard content compresses easier.
ML benches activate as their pip extras land (M1); until then they print SKIPPED.
