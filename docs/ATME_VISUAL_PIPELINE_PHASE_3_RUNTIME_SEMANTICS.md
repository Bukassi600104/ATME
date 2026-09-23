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
  In Slice 3D, the limited compositor consumes that fraction for `draw` on the five supported
  mark paths by progressively exposing the stroke, with authored fill appearing at completion.
  `write` on supported text/list objects reveals complete Unicode grapheme clusters while
  retaining authored line breaks and measured font bounds. `progressive_reveal` still lacks
  ordered-child semantics and fails closed; generic `reveal` remains a clipped reveal. Other
  object and action combinations must not silently substitute one of these effects.
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

## Bounded freehand geometry

Slice 3E accepts a `freehand` mark as either a polyline with two or more authored geometry
points or one continuous absolute M/L/Q/C path in `path_data`, never both. The M/L/Q/C grammar
does not allow arbitrary SVG tags, attributes, relative commands, arcs, closures, or compound
subpaths. Both forms are capped at 256 stroke segments. Quadratic/cubic strokes use
fixed-segment deterministic length approximation for
`draw` timing. Every authored point/control point must remain inside the object's bounds;
unsupported/degenerate geometry blocks the entire layout even when hidden. This is a bounded
hand-drawn shape, not a general vector import or a full path editor.

## Bounded relationship arrows

Slice 3F represents one authored semantic relationship with an `arrow` connector. Both source
and destination must be existing non-connector objects on the same board with named normalized
anchors; their current frame transforms determine connector endpoints. Its own authored bounds
must contain the route and arrowhead. Its stroke token is consumed, while separate points,
fill/text/effect styling, and independent motion that could detach it are rejected. Straight,
right-angle elbow, and
quadratic curve routes are deterministic. `draw` progressively exposes the shaft, then places
the arrowhead at completion. A visible arrow with a hidden endpoint blocks the frame rather
than floating unbound. Unsupported free-source pointers, network objects, self-loops, and the
canonical `connect`/`disconnect` actions remain unavailable.

## Bundled original-illustration slice

The bounded Slice 3C compositor may select an ATME-original Paper & Ink illustration by the
executable visual object's `variant`, matching an ID in the pinned v2 asset registry. It is not a
project-imported `asset_id`; arbitrary images, video, evidence, data charts, and generated art
remain unsupported. The exact registry bytes are checksum-verified again before composition,
parsed into a narrow static SVG subset, and serialized from the validated tree. The authored
geometry bounds the illustration, preserving its aspect ratio. Type/family matching is explicit:
characters use people; devices use devices; documents use documents; static chart illustrations
use charts; terminal illustrations use technical frames. Icon and pictogram may use any original
registry family. Project-asset substitution, style overrides, and unsupported types block the
entire layout even when the object is hidden at the sampled frame. This does not make the
illustrations a director-selected, data-driven, or complete production asset system.

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
