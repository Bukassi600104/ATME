# Phase 3 v2 runtime semantics — kernel contract

Status: Slices 3A–3U independent PASS; bounded 3V compositor under final audit;
not a production-renderer capability declaration

This document records the deterministic frame-state kernel and subsequent bounded source-only
SVG/PNG slices. It does not replace the v2 JSON contracts or authorize the v1 renderer to consume
them. The full action vocabulary, installed-app asset routing, and project preview/export wiring
remain later Phase 3 work. Until then, desktop and MCP capability must continue reporting renderer v1.

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
project-imported `asset_id`; that 3C slice does not handle arbitrary images, video,
evidence, data charts, or generated art. Slice 3U separately adds the bounded
project-owned PNG path below. The exact registry bytes are checksum-verified again before composition,
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

## Static group hierarchy and nested layers

Slice 3O permits authored `group` containers as non-painting stacking contexts.
Object geometry remains in board/canvas coordinates. A child's own transform is
applied around its authored bounds, then each ancestor group's transform is
applied around that group's authored bounds, from immediate parent outward.
Initial root/child order derives from `(z_index, object_id)` locally. The shared
hierarchy stores unique sibling ordinals, and SVG uses those ordinals directly.
Authored `z_index` remains unchanged: replacement/morph objects may share a
layer even though their sibling positions differ. A group subtree paints contiguously and cannot interleave
with an external sibling. Every child paints exactly once. Parent visibility
gates all descendants; nested group opacity multiplies descendant visual
opacity. Group position, scale, rotation, and fade use the existing ordinary
transform semantics. Group geometry supplies its pivot and does not paint a box.
`FrameObject.visible` is effective after active-board and ancestor visibility
gates. `FrameObject.opacity` and `transform` are local to that object; SVG
composes ancestor values through nested wrappers. The snapshot does not expose
world-space geometry or effective opacity, so downstream consumers must not
interpret those local fields as final visual values.

Group membership is static for this slice: children and groups must share a
board; `parent_id` and `child_ids` must agree; cycles, duplicate membership,
and excessive nesting fail. Groups cannot carry independent paint, media,
anchors, effects, or clipping payloads. No target attention/reveal action may
address a group until descendant-action semantics are fixed. `group`,
`ungroup`, and `split` remain unsupported, including when their action is
future or hidden. External `clip_id` remains unsupported; masks have the
separate bounded semantics below.
The frame evaluator and SVG compositor share this fail-closed hierarchy gate.
When a dynamic group action names a container, the ID must exist and resolve
to a same-board group, although execution of that action remains unsupported.
Slice 3P uses one affine resolver for nested SVG transforms, camera focus
rectangles, and connector anchor positions. Authored transform components are
quantized to the emitted four-decimal SVG factors before matrix composition;
intermediate matrix products are not rounded. Quantized local components, each composed affine matrix, and
all sampled world-bounds corners must be finite and within an absolute
1,000,000-unit bound; otherwise frame evaluation fails before SVG output. A
grouped visual leaf can be a
camera focus, with every ancestor's completed transform, visibility, and
opacity participating. A camera window cannot overlap a target or ancestor
geometry/visibility edit. A root connector can anchor to grouped objects, and
its route and authored bounds remain in world/board coordinates. An ancestor
that is hidden or fully transparent makes the endpoint unavailable. A connector
object inside a group still fails closed because it would require mapping the
world route back into its own parent space. Groups themselves are non-painting
and cannot be camera focus or connector endpoints. This is a bounded v2
compositor capability, not preview/export integration.

## Static clip containers

Slice 3Q gives authored `clip` containers a hard-edge rectangular meaning. The
container's `geometry.bounds` is a rectangle in its own local authored
coordinate system; its `child_ids` are its clipped subtree. The container
paints no shape. SVG applies the container's local transform and opacity once
to a `<g>` and applies a `clipPathUnits="userSpaceOnUse"` rectangle to that
group. Parent groups/clips transform the entire subtree outside it. Nested
clips therefore intersect. Clip IDs use a deterministic namespace distinct
from per-object reveal clips. The rectangle uses the same four-decimal
serialization as the v2 compositor; a rectangle whose serialized width or
height collapses to zero fails before output. Ordinary completed and animated
move/scale/rotate/fade of the clip container share group transform semantics.
Hidden or zero-opacity clips gate their descendants.

Target attention/reveal actions on a clip container, dynamic membership,
and all `clip_id` cross-references remain unsupported even
when future or hidden. Root connectors cannot bind to endpoints under a clip,
and camera focus cannot target a clipped leaf: their current world geometry
does not compute the post-clip visible region. A connector object cannot itself
be a clip child. These cases fail closed rather than showing untrimmed geometry.
## Bounded static-alpha mask containers

Slice 3R defines the explicit mask-source contract in plan/layout. Slice 3S
executes only that form in v2 frame state and SVG/PNG: one same-parent,
initially visible, static, non-painted geometry source provides a white alpha
aperture. Supported source shapes are filled rectangle, rounded rectangle,
ellipse, and polygon. The source's own transform positions the aperture in
its parent's local coordinates. The mask container's transform moves its
content beneath that stationary parent-local aperture; its opacity and
visibility gate the masked result. Nested groups, clips, and masks compose
in their existing local stacking order. The geometry source is not also
painted as an ordinary sibling. Seeking any frame uses the same deterministic
state evaluation and aperture bounds checks before SVG output.

Old `2.0.0` masks without policy fields remain loadable and round-trippable,
but are ambiguous and non-executable. Painted, animated, degenerate, or
non-sibling mask sources fail closed, including future source actions. Inverted,
feathered, media-derived, and dynamic masks are not supported. A camera focus
or connector endpoint beneath a mask remains unsupported because its world
geometry does not compute the post-mask visible region. Target attention or
reveal actions on a mask container, dynamic membership, and external
`clip_id` references also remain unsupported. This bounded compositor path
is not desktop preview/export integration or a full Phase 3 capability gate.

## Bounded authored-object replacement

Slice 3T defines `replace` only as a deterministic crossfade between two
distinct, already-authored, compositor-supported paintable leaves. The source
and destination must share board, parent stacking context, z-index, bounds,
and completed transform. The source must be fully visible, revealed, and
non-transparent at action start, including every ancestor. The destination
must be an untouched hidden object with positive authored opacity. Its
`post_state` is `visible`, while the source becomes permanently `removed`.
Both participants enter the action-conflict ledger. An overlapping edit of
their shared ancestor also fails. Replacement requires a complete board
activation and cannot silently rebind a connector endpoint or use a mask-only
source.

During the half-open action interval, eased progress attenuates the source
opacity and reveals the destination at authored opacity times progress; no
shape or geometry interpolation occurs. At the exact end only the destination
paints. A later action may edit the destination, and a later replacement may
use it as a new source. A replaced source cannot be revived. Camera focus on
either replacement participant cannot overlap replacement; before/after focus
liveness follows the replaced states. Frame evaluation, SVG, and PNG use the
same random-access state.
`morph`, dynamic grouping, arbitrary media substitution, and preview/export
integration remain unsupported.

## Bounded project-owned raster images

Slice 3U permits an authored `image` visual object backed by an immutable PNG
attachment owned by the same project. The project service verifies the asset
row, revision, canonical project URI, managed-path confinement, role, media
type, byte length, SHA-256, decoded dimensions, and upright orientation, then
passes the exact verified bytes to the pure v2 compositor. No compositor path,
URL, implicit file lookup, or network fetch is allowed. The decoder accepts
only bounded, noninterlaced RGB/RGBA 8-bit PNG with optional sRGB metadata;
unsupported metadata, animation, palette, external color profiles, and
malformed chunks fail closed. The resulting deterministic RGBA pixels are
contained within authored bounds, and the existing transform/opacity/reveal
state applies. Rotation remains blocked until permission can be bound to the
stored creative plan. An ordinary supporting image does not claim verified
external evidence provenance. Supporting images inside alpha masks, arbitrary
media, crop, and external assets remain unsupported on the ordinary-image path.
Bounded semantic evidence uses the separate attested path below. This does not
promote v2 to desktop preview/export.

## Bounded 3V evidence execution

An evidence object is distinct from a supporting image. It requires a plan-bound
evidence treatment, project-owned attested PNG bytes, exact asset revision and
checksum, declared provenance and rights, and matching transformations. The
compositor draws the exact source-pixel crop without invented replacement imagery,
then an authored focus outline, optional outside-focus darkening, source label,
and optional self-anchored annotation. Rounded card geometry clips its contents.
Unsupported annotation targets and masks that cannot preserve the entire card
fail closed. The source label is attribution supplied by the external AI/user;
ATME does not research or independently verify its semantic claim.

`insert_evidence` requires an untouched hidden object and a visible, fully
opaque ancestor chain. It fades the complete card into the authored destination
state. The board must remain active through the readable hold, with no other
same-board visual action during insertion/hold. World-size, minimum focus size,
retained camera framing, and rectangular mask/clip containment are checked
before frames can be returned. Rotation without declared evidence permission
is rejected throughout the resolved timeline. Mask apertures that are not
axis-aligned rectangles remain unsupported for evidence. This is only the pure
source SVG/PNG path, not installed-app preview/export or MCP production routing.

## Bounded board return continuity

`return_board` is a cut at the start of an authored destination-board activation.
It does not recreate, reset, or synthesize board objects. Its contract names the
immediately preceding source activation and board, the most recent prior
activation of the destination board, and the destination activation. It also
declares the complete destination-board object-state and state-version snapshot
as it stood when that prior activation ended. The runtime recomputes that
snapshot from initial states and completed state-bearing actions; a mismatch,
missing board object, stale version, off-board action, wrong activation lineage,
or non-step return fails before a frame is produced. A return after an activation
gap is valid, as is A→B→A. The destination board's prior semantic state and
developed-return state must match the plan's board/beat continuity declarations.
Subsequent authored actions may further develop the returned board. Older 2.0.0
return actions without this provenance remain parseable but non-executable.
This does not itself complete the claim-to-evidence-to-developed-abstraction
golden cycle, nor does it enable installed preview/export.

## Bounded 3Y geometry morph execution

`morph` now requires an explicit `morph_policy` on every newly written plan.
The mapping is one of: exact canonical outlines for rectangle/rounded rectangle/
ellipse; ordered equal-count vertices for polygons, two-point lines, and
point-authored freehand; or identical M/L/Q/C command sequences for freehand
curves. No automatic vertex matching, asset substitution, topology conversion,
or crossfade is used. Correspondence that collapses the entire stroke is rejected.

The two authored marks share style tokens, board, parent, and stacking position.
They may have different bounds and transforms. During the interval only the
source identity paints one interpolated path; all transform channels, opacity,
and geometry bounds use the same eased progress and pivot. At exact completion
the source becomes removed and the destination becomes visible. Later actions,
replacement/morph chains, and developed-board returns retain that identity and
state-version history. Random seeking reconstructs the same immutable result.
Static group, clip, and alpha-mask parents are supported and pixel-tested.
Morphing a mask source or connector endpoint, changing ownership, overlapping
participant/ancestor actions, concurrent camera focus, ignored geometry fields,
step easing, or incompatible correspondence fails before rendering. Camera
focus after completion may follow the destination. Legacy `2.0.0` morphs without
correspondence remain loadable but non-executable.

Stored resolved timelines additionally require the exact plan/layout initial
object inventory, states and visibility; exact beat-anchor inventory; and a
positive duration equal to the authoritative cleaned source timeline. These
structural checks are separate from action capability checks, so storage does
not incorrectly claim all remaining verbs are executable. Generated plan and
resolved-timeline schemas include the additive morph policy.

The reproducible offline proof is `bench/verify_v2_morph.py` and its retained
`docs/visual-acceptance/phase-3y-morph.png`/JSON. It exercises actual source
compositor pixels and byte-identical re-seeking with socket connections denied;
it is neither final creative-quality acceptance nor installed-app acceptance.

## Still to define and implement before Phase 3 exit

The remaining verbs are deliberately rejected by Slice 3A. Their executable semantics must be
fixed before their first runtime implementation:
`group`, `ungroup`, `split`, `count`,
sound state/events. `insert_evidence` and `return_board` have only the bounded
semantics above. In particular,
dynamic group ownership/initial receipts and standalone replay are now defined
below, but chronological execution remains required. Split result mapping and
non-list progressive disclosure still need executable contracts. Audible mixing remains Phase 7;
Phase 3 must at least expose deterministic sound events at the correct resolved times.

No v2 layout may be routed to project preview or export until the full primitive/action matrix,
asset integrity, board/camera behavior, real-project preview/export parity, and frozen/offline
regressions pass. The existing v1 renderer and Caleb-derived behavior remain unchanged.
Slice 3X's `preview_v2_source` is a private source-level integration verifier for an exact
stored layout/resolved-timeline pair. It does not change the public preview dispatcher,
advertised renderer capability, installed desktop behavior, or export availability.

## Bounded 3Z authored general annotation

An explicit `annotation_policy` binds one already visible, unchanged target to
preauthored hidden text/mark leaves and an optional exact annotation-to-target
pointer. Evidence is excluded from this general path; its attested treatment
remains separate. New writes require exact beat/action coverage, same-board
ownership, phase/type compatibility, and named pointer anchors. A bare legacy
`annotate` remains readable but non-executable. No annotation text, mark geometry,
asset, or anchor is invented by the renderer.

Positive integer phase weights divide the resolved construction window using
cumulative integer boundaries, so proportional weights have identical timing.
Collapsed sub-millisecond phases reject. Every phase uses local authored easing:
text is grapheme-written and marks/pointers are stroke-drawn. A pointer phase
follows its fully constructed source note. At completion the notes/leader persist;
the referenced target's state, paint and version do not change. Board return
increments only constructed-note/leader versions, never the read-only target.

Construction and the declared reading hold must fit one board activation.
Participants and ancestors must be effectively visible/revealed as appropriate
and fully opaque. Target, note, ancestor, isolation and camera edits cannot
interrupt that interval. Static group ancestry is supported; clipped/masked
annotation participants reject in this bounded treatment. Effective recursive
paint order, world bounds, transformed anchors and pinned text screen size are
checked; complete pointer route/head paint is preflighted even for earlier frames.
After the hold, a note without a pointer may be exited and camera focus may move.
A retained pointer reserves its own geometry and endpoint/ancestor dependencies
until a solo explicit pointer exit has fully completed; endpoint edits cannot
overlap that removal. This prevents early-valid timelines failing on later seeks.

`bench/verify_v2_annotation.py` retains ten source SVG-to-PNG phase frames across
both profiles with network calls denied and byte-identical re-seeks. These are
mechanical fixtures, not final Caleb-informed composition or creative-quality
acceptance. The fixed text-size floor and explicit reading duration do not replace
Phase 5's final attention/readability rubric. Private stored-project parity is
tested; public preview/export, compiler integration and installed acceptance are
still closed. The bounded independent runtime re-audit passed, including actual
offline frames and public v1 preview isolation. Full 3Z regression passed:
980 passed, 5 preexisting Windows symlink skips, exit code 0 in 1340.67 seconds.

## Bounded 3AA owned hierarchy and standalone step replay

Initial empty groups must be visible, opaque, nonpainting and `ungrouped`, with
one layout ownership row binding the real first group action and its exact full
source-basis hash. Empty clips/masks and orphan/duplicate/swapped owners reject.
Plan pairing binds action, shell and empty source membership; resolved pairing
requires that owner to be the earliest completion on that shell. This is not a
global earliest-action rule and does not prohibit prior unrelated work.

Resolved policy-bearing hierarchy actions require the exact initial layout
parent/order/local-transform basis plus canonical hash. The shared project/frame
preflight validates that identity. A basis with no GroupAction is allowed as
pair-validated structural provenance for static/return continuity, not executable
data that may be ignored. Absent receipts preserve the legacy serialized shape.
Group expected/post state affects the shell only, never the members' semantic
strings. The standalone replay kernel binds the current completed source basis,
applies only authored root locals and shell state, and increments every declared
structural version. Hidden staged descendants retain their exact paint/state.
Moved connector closures reject at plan/layout validation pending faithful
inverse-parent connector semantics.

The structural step is not enabled in frame execution. Ordinary frame sampling
now uses the shared chronology kernel described below. Remaining: dynamic
Group consumer/conflict and lifetime guards, FrameSnapshot production
routing, public Group camera acceptance, annotation/connector lifetime consumers, board-return
hierarchy receipts, stored SVG/PNG integration and public/installed acceptance.
Group/ungroup/split remain rejected by the current frame evaluator.

### Shared immutable chronology kernel

`v2_timeline_replay.py` retains committed local FrameObjects, current hierarchy,
state versions, and active actions with immutable serialized contracts and start
baselines. Each timestamp applies ordinary completions, structural completions
in resolved-index order, then starts. Intervals remain half-open. Random seeks
sample the appropriate immutable checkpoint rather than previous playback state.
Group reads the full sampled boundary (including unrelated still-active motion)
and commits only member-root local transforms, shell state, hierarchy and exact
structural versions. Do not persist unrelated partial poses or rebase an active
operator. Shifted-sibling version IDs are not automatically geometry conflicts.
Owned-write overlaps reject. Positive completed fades and dim/isolate legacy
version increments remain intact. Group requires an active visible destination
sample and cannot end at activation/project exhaustion under this bounded rule.

Ordinary `evaluate_frame` uses this kernel after pair validation and an
explicit unsupported/Group gate. The captured-start consumer slice now supplies
camera planning and temporal validation with this same replay; Group+annotation and Group+return
combinations reject in the standalone clock until their complete lifetime and
hierarchy receipts are implemented. This is not public Group, compiler, installed
preview/export or phase completion. The independent bounded source/docs audit
passed 76 replay tests and Ruff; the finalized combined renderer run passed 274
tests. Frozen pre-route full regression and the independent hash-pinned pre-route
oracle (27 families, 669 snapshots, 18 SVG/PNG pairs) prove separate scopes;
the changed ordinary route's full suite passed against source `37b0504`:
1,175 tests, five preexisting skips, exit 0 in 1472.35 seconds. Later consumer
integration requires its own final source verification.

### Captured-start validation and camera consumption

At `58947e9`, static identity, inventory, bindings, supported forms and ignored
field checks precede construction of one replay. Temporal validation then reads
`before_action(action_id)`: the immutable captured baseline before the action's
own zero-progress paint. Sampling `at(start_ms)` is not a substitute; evidence
insertion intentionally has zero opacity but a revealed paint state at that time.
Transform move/scale/rotate channel guards use the actual sampled local pose.

Camera planning uses the same pre-action hierarchy, transforms and readiness,
not an independent completion ledger. Focus conflict checks still precede
readiness, previous viewport inheritance remains exact, and public errors retain
the V2FrameError boundary. Private group-camera consumer tests do not authorize
public Group frames. Dynamic retained-pointer/evidence conflicts, full return
hierarchy receipts and replacement/morph effective paint order remain required.

Bounded combined tests passed 282; independent main verification passed 84 and
Ruff. Ten offline annotation frames and their contact sheet retained exact hashes.
Finalized full session `91184` FAILED: 9 failed, 1,170 passed, 9 skipped,
1298.45 seconds, exit 1 (`test-artifacts/phase-3aa-consumers-final-full-sidecar.log`).
Repair `365c3a0` restores six history-independent readiness diagnostic boundaries
without moving temporal checks, and updates three obsolete camera spies to prove
one shared replay/plan. Combined verification passes 399; independent verification
passes 117 and scoped Ruff. Four missing-VO-fixture skips in the isolated checkout
are not baseline symlink skips. Fresh full session `83170` PASSED frozen repaired
main source `365c3a0`: 1,187 passed, five preexisting symlink skips, 1399.88 seconds,
exit 0, with those VO cases run. Log:
`test-artifacts/phase-3aa-consumer-repair-full-sidecar.log`; imported source/tests
remained frozen throughout. Return receipt work remains separate and open.
No schema,
v1/Caleb renderer or installed application changes are claimed.

The initial attempt `34056` stopped after a reproduced missing isolated
`sidecar/.venv/Scripts/python.exe` resource-generator failure. Adding a local
junction to the existing environment restored all 30 resource tests (9.34s).
The restarted frozen `9ec3bb4` source/tests are Git-identical to main
`58947e9`; no assertions were weakened and no earlier partial run is a PASS.
