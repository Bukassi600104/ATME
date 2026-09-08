---
name: caleb-video-forensics
description: Analyze Caleb Writes Code reference videos into timestamped, evidence-backed narrative, visual, camera, and synchronization measurements for ATME. Use when studying reference videos, comparing an ATME render with the reference corpus, or revising ATME production rules from observed evidence. Do not use this skill to copy wording, artwork, branding, or creator identity.
---

# Caleb video forensics

Measure the production mechanics that make a technical explainer clear and engaging. Preserve observations and derived statistics, not copyrighted transcripts or frames.

## Evidence requirements

- Identify the exact video URL, title, duration, publication date when available, and access date.
- Record how transcript evidence was obtained: creator captions, automatic captions, local transcription of an authorized file, or manual observation.
- Mark unavailable evidence as unavailable. Never infer an exact timestamp, wording, or visual event from a title or summary.
- Keep verbatim transcript excerpts short and only when needed to identify a trigger phrase. Store paraphrases for analysis.
- Separate observable facts from interpretations.

## Analysis workflow

1. Obtain the transcript or locally transcribe an authorized audio/video file. If neither is available, continue with visual-only observations and mark narration metrics incomplete.
2. Sample the video at scene changes and at a regular interval suitable for its pace. Add denser samples around drawing, camera, or argument transitions.
3. Segment the narration into hook, stakes, causal movements, evidence, pivots, and resolution.
4. Annotate meaningful visual events: reveal, draw, connect, move, replace, count, cross-out, group, split, highlight, remove, and camera changes.
5. Associate each visual event with a short unique spoken trigger phrase when transcript timing supports it.
6. Calculate measurable pacing, persistence, camera, and synchronization statistics.
7. Validate the result against `schemas/reference-video-analysis.schema.json` with `scripts/validate_analysis.py`.
8. Only after validation, update aggregate ATME rules. Require support from at least three videos before treating an observed pattern as a default; otherwise label it a candidate pattern.

Read [references/annotation-contract.md](references/annotation-contract.md) before producing or reviewing an analysis JSON file.

## ATME boundary

Convert corpus findings into original functional rules: information density, causal structure, persistent-board continuity, visual cadence, trigger timing, and camera behavior. Never reproduce distinctive phrases, logos, thumbnails, drawings, character likeness, or channel branding. ATME must keep its own Paper & Ink identity.

## Completion check

- Source and evidence provenance are explicit.
- Events are chronological and timestamps fit the video duration.
- Observations and interpretations are distinguishable.
- Aggregate claims cite supporting analysis IDs.
- Validation passes without warnings.
