# Phase 2 — Paper & Ink style and asset foundation

Status: complete; independent gate PASS

Date: 2026-09-22

## Outcome

ATME now has a versioned Paper & Ink v2 production resource bundle. It defines semantic color,
typography, spacing, stroke, density, motion, caption, evidence, and independent landscape/portrait
composition rules. Sixteen original SVG assets cover people, gestures, devices, documents, networks,
charts, technical frames, and abstract metaphors, with semantic attachment points for later scene
actions. Four pinned OFL fonts render without host font fallback.

This phase provides the production resources and their deterministic renderer proof path. The v2
scene/action renderer and real project preview/export consumption remain Phase 3. Legacy v1 output
is unchanged; it still uses its existing system-font fallback until v2 replaces that path.

## Contracts and provenance

- `production-assets/paper-ink-v2/style.json` — `atme-style-v2`, semver `2.0.0`.
- `production-assets/paper-ink-v2/asset-registry.json` — `atme-assets-v2`, semver `2.0.0`.
- `schemas/paper-ink-style-v2.schema.json` and `schemas/paper-ink-assets-v2.schema.json` are generated
  from strict typed models.
- Source URLs, pinned commits, license files, resource SHA-256 hashes, asset family, keywords,
  normalized anchors, and originality attestations are recorded in the manifests.
- Runtime verifies every font, font license, and asset checksum, validates SVG structure and viewBox,
  and code-pins both manifest hashes. Mutating tokens or assets under the same version fails.
- The generator emits LF deterministically, and `.gitattributes` preserves LF for hashed manifests,
  schemas, licenses, and SVGs across Windows checkout. A fresh temporary Git clone reproduced the
  same resource bytes and hashes.
- The bundled fonts are Kalam Regular/Bold and Atkinson Hyperlegible Regular/Bold, each covered by
  the included SIL OFL 1.1 license file.

## Rendering proof

- Both aspect profiles render an original asset matrix and a typography/evidence/caption specimen.
- The proof renderer passes only the verified bundled fonts to resvg and sets
  `skip_system_fonts=True`.
- Proof preview and proof export byte output match exactly for each aspect. Frozen and source proof
  SHA-256 values also match.
- `docs/visual-acceptance/phase-2-paper-ink-landscape.png` and
  `phase-2-paper-ink-portrait.png` show all sixteen components.
- `docs/visual-acceptance/phase-2-type-landscape.png` and `phase-2-type-portrait.png` show typography,
  semantic colors, caption treatment, evidence treatment, and safe-area placement.
- Contrast of body, muted, accent, attention, success, and caption text meets the declared 4.5:1
  minimum against its background.

## Modules changed

- New `sidecar/src/atme/render/style_contracts.py` and `style_bundle.py`.
- New `sidecar/tools/generate_paper_ink_v2.py`.
- New `production-assets/paper-ink-v2/` bundle and two generated schemas.
- `sidecar/atme-sidecar.spec` packages the bundle and explicitly includes its loader modules.
- `sidecar/launcher.py` adds a read-only `--verify-style-bundle` packaging diagnostic.
- `sidecar/tests/test_paper_ink_style_bundle.py` checks contracts, provenance, tampering, visual
  determinism, profile rules, font isolation, and proof parity.
- `schemas/README.md` documents the contract family.

## Verification

- Focused Phase 2 suite: 30 passed.
- Ruff on touched Python: passed.
- Isolated PyInstaller build: passed; the standard dirty build output was not overwritten.
- Frozen executable `--verify-style-bundle`: passed, returning sixteen assets and both profile
  proof hashes. Source and frozen hashes match for both manifests and both schemas.
- Full sidecar suite: clean final run reached 100% with exit code 0 and no failures.
- The LF checkout fix was followed by another 30-test focused pass, Ruff pass, full sidecar pass,
  fresh isolated frozen build, and source/frozen diagnostic parity.

## Requirement claims and limits

- R-07: original asset families, registry, provenance, checksums, and visual matrix are implemented
  as the foundation. Automatic selection and expressive per-beat composition remain Phases 3–4.
- R-12: style tokens, bundled fonts, accessibility rules, profile rules, and proof rendering are
  implemented. Token consumption by the full v2 action renderer remains Phase 3.
- Phase 2 proof parity is not a claim that current real-project v2 preview/export is available.
  Phase 1 correctly blocks v2 rendering until the Phase 3 runtime executes the plan.

## Independent gate

PASS. The independent auditor reproduced strict-contract rejection, resource and font integrity,
the 30-test focused suite, Ruff, and matching source/frozen proof hashes. The full sidecar suite
completed at 100% with exit code 0. The auditor confirmed that real-project v2 rendering and
preview/export parity remain Phase 3 work, not a Phase 2 claim.
