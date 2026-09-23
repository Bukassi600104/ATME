# Phase 3 — renderer and action runtime progress

Status: Slices 3A–3G independent PASS; Phase 3 remains incomplete

Date: 2026-09-23

## Delivered in Slice 3A

- `sidecar/src/atme/render/v2_state.py` reconstructs immutable object state from exact stored v2
  layout and resolved-timeline JSON at an arbitrary millisecond. It checks the canonical layout
  hash, plan/layout/profile/style/registry identity, initial state inventory, board ownership,
  non-overlapping same-object action windows, and unsupported verbs before returning a frame.
- Supported state operations are reveal, write, draw, progressive reveal, enter, permanent exit,
  move, scale, rotate, and fade. All other canonical actions fail explicitly. The semantic kernel
  contract is in `ATME_VISUAL_PIPELINE_PHASE_3_RUNTIME_SEMANTICS.md`.
- V2 contracts now reject NaN and Infinity. An exit declares `removed`; the v1-to-v2 migration
  records this canonical mapping for legacy remove actions.
- Focused tests exercise random/backward seeking, half-open boundaries, all five easing functions,
  channel-specific and chained transforms, board gaps and returns, immutable frame/caller state,
  malformed pairings, non-finite input, overlap, and unsupported actions.

## Incomplete Phase 3 gates

- Slice 3B now emits SVG and a tested resvg PNG frame for five geometric mark types and
  text/list objects. It measures text against the pinned font, scales style tokens to the
  authored 16:9 or 9:16 output size, keeps the authored canvas origin, and rejects unsupported
  objects, ignored fields, and unsupported semantics. The PNG API
  loads verified packaged font files and disables system-font fallback. This is a
  limited compositor path, not the project's preview/export implementation.
- Slice 3C adds pinned original-registry artwork for explicitly selected icon, pictogram,
  character, device, document, chart, and terminal illustrations. All sixteen bundled assets
  are independently composited and raster-tested inside authored bounds. The bundle checksum
  is rechecked at composition; invalid family/type selection and overridden illustration
  styling fail. Arbitrary project images, video, evidence, and data-driven charts remain
  unsupported.
- Slice 3D implements `draw` as progressive SVG path stroke for the five supported mark types,
  and `write` as whole-grapheme text/list progression using the authored font and line breaks.
  The mark's fill appears at action completion. These two verbs no longer use a generic
  rectangular reveal; `progressive_reveal` still rejects until ordered-child semantics exist.
  This is a limited frame-compositor capability, not desktop preview/export wiring.
- Slice 3E adds bounded `freehand` point-polylines and authored absolute M/L/Q/C path strokes.
  Its parser accepts data-only coordinates, emits sanitized path geometry, checks control points
  against authored bounds, and rejects unsupported SVG commands and invalid/degenerate paths.
  Existing `draw` progression now applies to these strokes. This does not add arbitrary SVG,
  external artwork, or full-object compositor coverage.
- Slice 3F adds bounded semantic arrows between named anchors on two same-board objects. Straight,
  elbow, and quadratic-curve routes follow endpoint movement, scale, and rotation in random-access
  frames; authored `draw` progresses the shaft and places the arrowhead only at completion.
  Free-source pointers, network objects, independent connector transforms, hidden endpoints,
  cross-board bindings, and out-of-bounds routes remain rejected. This does not implement the
  full network-layout engine.
- Slice 3G adds canonical `connect`/`disconnect` actions for that arrow subset. The resolved
  timeline now treats source/destination as checked references, not objects mutated by a
  connection. Exact static binding and canonical disconnected→connected→disconnected state
  transitions are required; connect draws the shaft/arrowhead and disconnect retracts it.
  Managed connector initial visibility must match its relationship state, and unrelated
  target/transform actions cannot move or redraw it independently. Neither verb broadens
  support to free-source pointers or general networks. State evaluation and SVG composition
  share one static arrow support gate, so unsupported self-loops, connector endpoints, and
  ignored connector styling cannot pass state evaluation but fail at rendering.
- No audio events are produced by the kernel. The full 35-type primitive/container
  compositor, asset/media resolution, remaining canonical action verbs, camera/board composition,
  and real project preview/export dispatcher are still required.
- The current application continues to report renderer v1 and rejects v2 layouts for project
  preview/export. No installed desktop rebuild is claimed.
- Real-project preview/export parity, frozen/offline execution, and representative production
  acceptance remain outstanding; proof-render parity from Phase 2 is not a substitute.

## Verification

- Slice 3A focused tests: 30 passed.
- Combined v2 contract/frame-state tests: pass.
- Ruff on touched Python: pass.
- Full sidecar regression: passed after Slice 3B (2026-09-23).
- Slice 3B focused SVG/raster tests: 21 passed; 51 combined frame-state/compositor tests passed.
- Independent Slice 3B decision: PASS for the declared primitive subset; not full Phase 3.
- Slice 3C focused illustration tests: 38 passed; 119 combined Phase 2/3 renderer tests passed.
- Independent Slice 3C decision: PASS for verified bundled illustrations and the strict SVG subset;
  not full Phase 3. The auditor separately rechecked the nested-viewport hardening. The full
  sidecar regression passed against the finalized Slice 3C files (2026-09-23).
- Slice 3D focused SVG/raster tests: 29 passed, including all five supported draw paths,
  random/backward seek parity, incompatible-target rejection, zero-length path rejection,
  and combining-character text writing. The independent auditor passed the bounded gate after
  97 combined Phase 3 tests, 13 targeted v1/offline-render tests, and Ruff. The full sidecar
  regression also passed with exit code 0 against the finalized Slice 3D files (2026-09-23).
- Slice 3E focused freehand/SVG tests and Ruff passed. The independent auditor passed the
  bounded gate after rechecking coordinate overflow, serialized zero-length paths, malformed
  inputs, future/hidden path rejection, and deterministic seek/raster output; 79 focused tests
  passed in its separate run. The full sidecar regression passed against the finalized 3E files
  with exit code 0 (2026-09-23).
- Slice 3F focused connector/SVG tests and Ruff passed. The independent auditor passed the
  bounded gate after 72 connector/SVG/frame-state tests, 12 targeted v1/offline-render tests,
  and checks for effective endpoint visibility, fractional transform parity, bounds, routing,
  and deterministic seeking. The full sidecar regression passed against finalized 3F files
  with exit code 0 (2026-09-23).
- Slice 3G: 85 focused connection/connector/state/contract tests and Ruff passed. The
  independent auditor passed the bounded gate, including shared fail-closed validation,
  random-access deterministic seeking, and 13 targeted v1/offline-render regressions.
  The full sidecar regression passed with exit code 0 against finalized Slice 3G files
  (2026-09-23). No full Phase 3 or installed-app claim follows.
- Independent Slice 3A decision: PASS. The auditor repeated the focused and v2-contract tests,
  Ruff, non-finite rejection, exact-boundary and chained-state checks, and confirmed that no v2
  production capability is falsely advertised.
