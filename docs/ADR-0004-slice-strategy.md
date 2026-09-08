# ADR-0004: Silence-slicing uses a deterministic energy-RMS slicer first

Date: M1. Status: accepted.

## Context
The plan names Silero VAD for silence slicing. Tight pacing cuts must be predictable and
unit-testable offline; VAD models add a nondeterministic dependency to the most timing-critical
transform in the chain.

## Decision
Default slicing is a deterministic energy-RMS frame classifier (configurable threshold/min-silence/
padding) in atme.audio.polish.slice_silences. A Silero-backed strategy remains available behind
the same interface and may become default only after A/B validation against real recordings.
Word-level alignment still uses faster-whisper's internal Silero VAD exactly as specified.

## Consequences
Pure breathy pauses below threshold are treated as silence regardless of phonetic content -
acceptable for narration VO; revisit only if real-world review shows clipped trailing phonemes
(would surface immediately in Review-screen sync checks).
