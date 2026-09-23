# Phase 3 v2 runtime semantics — kernel contract

Status: Slice 3A in progress; not a production-renderer capability declaration

This document fixes the meanings implemented by the first deterministic frame-state kernel. It
does not replace the v2 JSON contracts or authorize the v1 renderer to consume them. Real pixels,
asset resolution, the full action vocabulary, and project preview/export wiring remain later
Phase 3 slices. Until then, the desktop and MCP capability must continue reporting renderer v1.

## Input and time authority

- Evaluate the exact stored layout and resolved-timeline JSON. The timeline's layout SHA-256 must
  match the canonical stored layout bytes; IDs, plan reference, profile, style, registry, and initial
  object inventory must agree. Non-finite coordinates or timing inputs are rejected.
- Frame requests use integer milliseconds in the half-open interval `[0, duration_ms)`. Action
  intervals are `[start_ms, end_ms)`; at `end_ms`, the action has completed. Board activations are
  also half-open. A gap has no active board and displays no board objects.
- Every frame is reconstructed from the immutable initial state and ordered resolved actions.
  Seeking backward, random access, sequential playback, and export must therefore agree. A cache
  may only memoize this pure result; it may not become the source of truth.
- The current slice rejects overlapping actions on the same object, including otherwise
  independent channels. Later support requires an explicit, tested composition rule. Unsupported
  authored verbs fail before any frame is returned, even when their start time lies in the future.

## Object state and interpolation

- Frame objects are deeply immutable records. Stable paint order is ascending `(z_index,
  object_id)`; the latter is a deterministic tie-breaker, not an authored layer change.
- Initial visibility and semantic state must agree between layout and resolved timeline. A board
  gap hides objects without resetting their underlying state; returning to a board restores its
  developed state.
- `reveal`, `write`, `draw`, and `progressive_reveal` expose a scalar reveal fraction from 0 to 1.
  This fraction is a timing instruction, not yet a rendered stroke, text-glyph, or ordered-child
  effect. The compositor must implement those distinct effects before claiming verb coverage.
- `enter` fades from zero to the authored object opacity; it does not invent a slide direction.
  `exit` fades to zero, ends invisible, and has the canonical permanent `removed` post-state.
  Re-entry after removal is invalid in the v2 timeline; a returning board should retain its
  object rather than exit it. Migrated v1 `remove` maps explicitly to this `exit` state.
- `fade` changes opacity only and may not carry a transform destination. `move` changes position
  only; `scale` changes scale and transform origin only; `rotate` changes rotation and origin only.
  Destinations changing unrelated channels fail validation instead of being silently ignored.
  A completed transform is the baseline for a subsequent non-overlapping transform.
- Easing is exact and deterministic: linear `p`, ease-in `p²`, ease-out `1-(1-p)²`, ease-in-out
  `p²(3-2p)`, and step `0` until completion then `1`, where `p` is clamped interval progress.

## Still to define and implement before Phase 3 exit

The remaining verbs are deliberately rejected by Slice 3A. Their executable semantics must be
fixed before their first runtime implementation: `highlight`, `dim`, `isolate`, `connect`,
`disconnect`, `replace`, `morph`, `cross_out`, `annotate`, `group`, `ungroup`, `split`, `count`,
`insert_evidence`, `return_board`, all five camera verbs, and sound state/events. In particular,
the contract needs explicit rules for morph compatibility, dynamic group ownership, split result
mapping, isolate restoration, and ordered progressive disclosure. Audible mixing remains Phase 7;
Phase 3 must at least expose deterministic sound events at the correct resolved times.

No v2 layout may be routed to project preview or export until the full primitive/action matrix,
asset integrity, board/camera behavior, real-project preview/export parity, and frozen/offline
regressions pass. The existing v1 renderer and Caleb-derived behavior remain unchanged.
