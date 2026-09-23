# Phase 3 v2 runtime semantics — kernel contract

Status: Slices 3A–3M independent PASS; not a production-renderer capability declaration

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
  retaining authored line breaks and measured font bounds. Slice 3I consumes the fraction for
  whole-item `progressive_reveal` on an authored list only; generic `reveal` remains a clipped reveal. Other
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
than floating unbound. Unsupported free-source pointers, network objects, and self-loops remain
unavailable.

Slice 3G accepts `connect` only on that exact authored arrow binding, with `expected_state`
`disconnected` and `post_state` `connected`; `disconnect` requires the inverse. Source and
destination object IDs/anchors are integrity-checked references, not state transition targets.
Connection actions transition only the connector, must not overlap another connector action,
and preserve endpoint movement. A managed connector begins either connected and visible or
disconnected and hidden; no other action may mutate that connector. Connect progresses the
shaft from source to destination and
places the arrowhead at completion. Disconnect withdraws the shaft toward the source and removes
the arrowhead during withdrawal; at completion the connector is hidden. Every frame is rebuilt
from the initial state and ordered actions, so reverse/random seeking restores the relationship
exactly. This is not general connector rebinding or a network graph runtime.
The state evaluator and SVG compositor use the same static arrow support gate; a connection
cannot be accepted as state while its connector form is unsupported by the bounded compositor.

## Authored emphasis marks

Slice 3H supports two additional static mark object types in the bounded compositor:
`underline` is a single curved accent stroke, and `highlight` is a slightly asymmetric
attention-color ring. Their paths are constructed only from the authored object bounds and
versioned Paper & Ink style tokens; both support the same path-length-based deterministic
`draw` progression as other marks. They do not imply target linking or, by themselves, execute
the separate `highlight` action added in Slice 3J. Extra points, injected path data, fill, text/effect styling, or unknown
color tokens block the layout even when the mark is hidden.

## Ordered list disclosure

Slice 3I gives `progressive_reveal` one bounded meaning: a hidden, previously untouched
`list` text object with an authored heading and nonempty ordered `items`. Its action must declare
`expected_state=hidden` and `post_state=visible`, so completed visibility and semantic state
cannot disagree. The heading appears
once action progress is positive. At eased fraction `p`, exactly `floor(p × item_count)` complete
items are shown; the completed action shows all items. Each heading/item must be one line and
the entire list must fit the authored bounds in the pinned body font before any frame is
composited. No glyph cropping or generic clip is used. Non-list targets, empty or blank
heading/items, line separators including Unicode, already visible or previously touched lists
fail closed in both state evaluation and composition. This does not
implement arbitrary ordered children, groups, camera reveal, or an automatic director.

## Bounded target highlight

Slice 3J gives `highlight` one explicit target-action meaning for the bounded compositor. It
targets an already-visible, nonzero-opacity, previously untouched supported geometric/emphasis
mark or text/list object on the active board, with `expected_state=visible` and
`post_state=highlighted`. The authored action window must fit inside that board activation.
The target's original content remains visible; a slightly asymmetric attention-color ring is
drawn over its bounds by deterministic path-length progression and follows the target's
existing transform. After completion the ring persists and the semantic state is `highlighted`.
The target cannot receive later target or transform actions in this bounded slice. Connectors,
registry illustrations, hidden targets, and unsupported geometry fail closed. This does not
implement dimming, isolation, secondary-context choreography, or automatic direction.

## Bounded target cross-out

Slice 3K gives `cross_out` one explicit, non-destructive target-action meaning. It targets an
already-visible, nonzero-opacity, previously untouched supported mark or text/list object on
the active board, with `expected_state=visible` and `post_state=crossed_out`. The complete
action window must fit inside one board activation. Two separate attention-color diagonal
strokes cross the target's authored bounds, drawn sequentially by deterministic path-length
progression; the target's existing content, opacity, and transform remain unchanged. Both
strokes persist after completion and move with the object's existing transform. The target
cannot receive later target or transform actions in this bounded slice. Unsupported targets,
hidden targets, ignored annotation payloads, and unsupported geometry fail closed. Cross-out
does not erase content, rewrite narrative facts, or automatically select what to correct.

## Bounded transient dim

Slice 3L gives `dim` a temporary secondary-context meaning for initially visible,
nonzero-opacity supported mark and text/list objects. An action must declare
`expected_state=visible` and `post_state=visible`, have unique targets, use non-step easing,
and fit wholly within one activation of its target board. The object may have had only prior
non-overlapping `dim` actions, not content or transform edits. At the action start, the object
keeps its authored opacity. During the first 20% of eased progress it descends to 35% of that
opacity, holds through the middle, and restores over the last 20%. At `end_ms`, original opacity
is restored exactly and no dim state persists. Multiple targets use the same envelope without
compounding; later non-overlapping edits remain possible. This is a versioned bounded action
meaning, not an authored opacity edit, isolation, automatic target selection, or a general
attention director. Unsupported or hidden targets and board-crossing windows fail closed.

## Explicit focus isolation

Slice 3M gives `isolate` a transient board-wide meaning. `target_ids` names one or more visible
focus objects; other currently visible objects on the same active board become secondary context
and use the same 35%-minimum, 20%-ramp dim envelope as Slice 3L. Focus objects keep their
content, opacity, and transform unchanged. At the action end, context returns exactly to its
pre-isolation opacity, with no persistent isolation state. The action must declare
`expected_state=visible` and `post_state=visible`, use non-step easing, have unique focus IDs,
and fit wholly inside one board activation. A focus may have been revealed by an earlier
completed action; it must be effectively visible, fully revealed, and nonzero-opacity at
isolation start. At least one visible, fully revealed, positive-opacity non-focus object must
exist on the board, so an all-focused or empty-context action cannot silently do nothing.
The bounded compositor accepts supported marks, text/lists, and pinned-registry illustrations
as focus. To avoid ambiguous ownership, no other visual action on that board may overlap the
isolation window, even if it names a different object. Sound actions are excluded from this
visual-conflict rule but remain unsupported by the current frame kernel.
Hidden or unrevealed context stays unaffected. Repeated non-overlapping isolations do not
compound opacity.
This is an executable primitive, not automatic focus selection, a reading/listening policy,
or the complete attention choreography validator.

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

## Bounded deterministic camera framing

Slice 3N executes `camera_hold`, `camera_cut`, `camera_pan`, `camera_zoom`, and
`camera_reframe` for fully revealed, visible, nonzero-opacity, supported objects
on one active board. Camera actions observe their targets; they do not change
object semantic state. Authored target geometry, including completed position,
scale, and rotation, is evaluated at the camera action boundary. The union of
target bounds determines a 16:9 or 9:16 aspect-preserving viewport. Pinned
framing occupancy is wide 42%, medium 60%, close 78%, detail 90%, and safe-area
52% preferred. Large targets may force a wider shot, and an edge-constrained
safe-area shot may tighten only while its required inset remains intact. The viewport
must remain within the output canvas and contain its focus at the destination.
The viewport is never narrower than 30% of the canvas, preventing tiny marks
from becoming oversized full-screen graphics. `safe_area` additionally requires
the entire focus to remain inside an 8%-of-viewport inset on all four sides;
edge-constrained focus that cannot meet it fails.

`hold` preserves the current viewport and `cut` switches instantly at its start;
both require step easing. `pan` changes center while keeping zoom fixed, `zoom`
changes size around a fixed center, and `reframe` changes center and size; these
require continuous easing and visible movement. The camera retains its final
viewport after an action, resets at a new board activation, and is reconstructed
from the immutable timeline on every random seek. Camera actions must be
non-overlapping and wholly contained within one board activation. Concurrent
transform, visibility, or reveal changes of a focus object are rejected rather
than guessed. A hold or pan whose declared framing implies a different scale
from the current viewport fails rather than silently ignoring that field.
Unsupported targets or impossible framing fail closed. The SVG
viewBox and PNG raster share this exact viewport.

This implements camera mechanics for the bounded compositor, not automatic
camera direction, final project preview/export wiring, or a complete safe-area
quality gate. `movement_purpose` is preserved in the frame but does not by itself
choose a shot; the external visual director remains responsible for authored
camera decisions.

## Still to define and implement before Phase 3 exit

The remaining verbs are deliberately rejected by Slice 3A. Their executable semantics must be
fixed before their first runtime implementation: `replace`, `morph`, `annotate`,
`group`, `ungroup`, `split`, `count`,
`insert_evidence`, `return_board`, and sound state/events. In particular,
the contract needs explicit rules for morph compatibility, dynamic group ownership, split result
mapping, isolate restoration, and ordered progressive disclosure. Audible mixing remains Phase 7;
Phase 3 must at least expose deterministic sound events at the correct resolved times.

No v2 layout may be routed to project preview or export until the full primitive/action matrix,
asset integrity, board/camera behavior, real-project preview/export parity, and frozen/offline
regressions pass. The existing v1 renderer and Caleb-derived behavior remain unchanged.
