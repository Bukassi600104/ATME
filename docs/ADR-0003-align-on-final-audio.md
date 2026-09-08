# ADR-0003: Word alignment runs on the FINAL polished audio track

Date: M0. Status: accepted.

## Context
The polish chain includes silence slicing (>100 ms below threshold), which shifts the timeline.
Aligning on the raw recording (the order implied by the source document) would desync every cue
after the first cut.

## Decision
Pipeline order is: voice source -> noise reduction -> VAD silence slicing -> pedalboard polish ->
loudness normalize -> THEN faster-whisper word alignment on the final WAV. The slicer emits an
edit-decision list mapping original<->final timeline (used for subtitle export and debugging).
Confidence-gated words are flagged for optional manual correction in the Review screen.

## Consequences
Cue timeline is correct by construction against the audio actually muxed into the MP4.
