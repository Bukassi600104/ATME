# P3-38 / P3-41 bounded ink and evidence tokens

The existing nullable `StyleRefs.effect` field admits exactly `ink_fine` and `ink_emphasis` on the closed owners below. They select the pinned `fine_px` or `emphasis_px` multiplied by uniform profile scale. Null preserves the existing type-default width and serialized field. No bundle, schema, asset or dependency is added.

| Token or reference | Applicable owner | Disposition |
|---|---|---|
| `ink_fine`, `ink_emphasis` | Stroked freehand, line, rectangle, rounded_rectangle, ellipse, polygon, bracket; ordinary admitted arrow/network semantic relationships | Consumed as primary stroke width, including selected-width connector head and footprint. Same ordinary/frozen paint path. |
| Any other non-null effect (including empty) | Every object, including hidden objects | Rejected. |
| Either ink reference | Highlight/underline marks, owned callout/annotation/evidence pointers, text/code/chart/registry/technical/evidence/media objects, containers and mask sources | Rejected; their paint owners are unchanged. |
| Semantic stroke/fill/text colors | Existing native paint owners | Consumed through existing color resolver; ink references preserve authored colors and fills. |
| `fine_px` | Evidence outer border, focus rectangle and inline pointer | Consumed. Outer border keeps authored/default color. |
| `evidence.mask_color_token` | Evidence outside-focus fill | Consumed through `style.colors`; opacity remains exactly authored `intent.darkening`. |
| `evidence.highlight_color_token` | Evidence focus rectangle and inline pointer | Consumed through `style.colors`; source bytes remain unchanged. |
| `evidence.source_label_color_token` | Evidence source attribution | Consumed through `style.colors`; inline annotation text retains its existing owner. |
| `evidence.mask_opacity` | Default evidence intent compilation | Deferred to compiler ownership; never overrides authored darkening. |
| Typography/font resources | Native text/code/evidence/chart/callout owners | Consumed where applicable with existing pinned font isolation. |
| Spacing | Existing callout/chart layout consumers | Consumed only at existing owner sites; no authored geometry rewrite. Other compiler defaults remain deferred. |
| `corner_radius_px` | Default/specimen authoring | Deferred where geometry supplies its own radius; authored radius remains authoritative. |
| `roughness_px` | No approved native perturbation | Deferred; no random geometry displacement or invented treatment. |
| Motion/easing defaults | Compilation and authored action semantics | Deferred to their owners; no timing replacement. |
| Density, safe areas, accessibility, read holds | Quality/layout/evidence validation | Existing owner authority retained; no forced paint/layout rewrite. |
| Captions | Caption compiler/compositor owner | Deferred to that owner. |

The current ordinary mark color authority always paints a default ink stroke for null stroke; `none` is not a supported color token and rejects. An effect does not reinterpret null or accept a filled-only/no-stroke form.

Ink weight changes preserve centerlines, endpoints, routes, source pixels, timing, opacity, transforms and hierarchy order. The existing connector-head formula uses the selected width. Selected-width route half-stroke and head paint must fit existing authority. An authored hierarchy clip/mask can crop paint in its existing order; an SVG viewport is not admission authority.

## Finite verification boundary

`sidecar/tests/test_v2_ink_effects.py` separates `test_pure_*` from `test_native_*`. Pure cases deny native SVG paint, font measurement and network; they cover weight, closed eligibility, unknown/empty hidden references, authored color/fill/centerline, null serialization, connector half-stroke/head immediate-invalid extents, and exact evidence token/opacity consumption. Stubbed evidence crop/text in pure cases are token proof only, never raster proof.

The finite native selection consists of eight profile/weight/carrier literal stroke cases (begin/mid/end draw/connect plus backward repeats and independent null baseline), two reveal/transform/opacity/clip/mask comparisons, one affected retained Split pair for each mark/connector, and two evidence before/after cases. No unrelated family Cartesian product or new every-millisecond expansion is required. Existing owner coverage machinery remains authoritative where called by fixture admission.

Native output schema: each test receives a retained `tmp_path` directory. Literal cases save `phase-{fraction}-{actual,expected}.{svg,png}` and `null-{actual,expected}.{svg,png}`; composite cases save `reveal-transform-opacity-clip-mask-{actual,expected}.{svg,png}`; frozen cases save `frozen-{0,12,40}.{svg,png}` and `ordinary-{0,40}.{svg,png}`; evidence cases save `evidence-{actual,before}.{svg,png}`. PNG pixel buffers, not encoded-compression hashes, are compared. Expected literal strokes use independently authored SVG and pinned token values; frozen comparisons verify the affected reference survives retained painting. Evidence before frames recreate only the prior token choices and preserve the same embedded crop.

This is supporting owner evidence, not ledger, public capability, whole-phase, installed, audiovisual or release acceptance. Exact integrated bytes and the retained independent reviewer remain required.
