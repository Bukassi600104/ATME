# ADR-0001: Custom "Layered SVG Animator" instead of full Manim

Date: M0. Status: accepted.

## Context
The spec (Automated AI Pipeline doc, Phase IV) describes SVG path tracing with
stroke-dasharray/dashoffset animation keyed to word timestamps, naming Manim as an example
library. Target hardware is a 2-core/4-thread i3-7100U with a 5400 RPM HDD.

## Decision
Implement a purpose-built renderer ("Layered SVG Animator") that realizes exactly the specified
technique: Excalidraw JSON -> SVG paths -> draw-on animation keyed to cue timestamps -> camera pans.
It composites in layers: static elements are cached rasters; only the currently-drawing stroke is
re-rasterized per frame. Frames stream to FFmpeg over stdio (no temp frame files on HDD).

## Consequences
- Full Manim scene machinery (per-frame full-scene rasterization, heavy startup) is avoided;
  expected several-fold throughput gain on 2 cores, deterministic timing we control.
- The renderer sits behind an interface; a Manim backend can be added later without touching
  pipeline code if ever needed.
- We own camera easing, roughness perturbation, and segment checkpointing logic (small, testable).
