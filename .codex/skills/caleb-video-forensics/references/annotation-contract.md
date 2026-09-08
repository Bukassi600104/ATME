# Reference video annotation contract

Use the repository schema `schemas/reference-video-analysis.schema.json` as the source of truth.

## Required evidence model

- `video`: stable identity, URL, title, duration, and access date.
- `evidence`: transcript provenance and the visual inspection method.
- `narrative_beats`: chronological argument movements. `summary` must be a paraphrase.
- `visual_events`: meaningful state changes, not every frame. Use `trigger_phrase` only when supported by timestamped narration.
- `metrics`: values calculated from the available evidence. Omit optional metrics rather than guessing.
- `observations`: directly visible or audible facts.
- `interpretations`: conclusions derived from observations, each referencing evidence IDs.

## Timing conventions

All times use integer milliseconds from the start of the published video. A beat covers `[start_ms, end_ms]`. A visual event uses its onset in `at_ms`. Camera travel should be recorded at the beginning of movement rather than when it settles.

## Event taxonomy

Use only: `reveal`, `draw`, `connect`, `move`, `replace`, `count`, `cross_out`, `group`, `split`, `highlight`, `remove`, `camera_hold`, `camera_pan`, `camera_zoom`, `camera_reframe`, `cut`, or `other`.

## Corpus aggregation

Do not average incompatible formats together. Partition presenter-led, digital-whiteboard, physical-lightboard, tutorial, and editorial videos. Report median and interquartile range for timing metrics because isolated sponsor sections and long demonstrations distort means.
