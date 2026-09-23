# ATME Paper & Ink v2 resources

This is the immutable production-resource bundle for the `2.0.0` Paper & Ink style contract. It is not a reference-art archive and contains no copied creator artwork, wording, branding, handwriting, or identity.

- `style.json` defines semantic production colors, typography, spacing, stroke, density, motion, caption, evidence, and independent 16:9/9:16 composition rules.
- `asset-registry.json` records checksums and provenance for sixteen original ATME vector assets across eight semantic families.
- `assets/` contains original, local-only, text-free, script-free SVG components using a bounded token vocabulary.
- `fonts/` contains pinned render-safe typefaces and their unmodified OFL 1.1 licenses.

Kalam Regular/Bold comes from the Google Fonts repository at commit `e44c4b011a820c2cbe2fd2cfa8052037d7edb571`. Atkinson Hyperlegible Regular/Bold comes from its Google Fonts project repository at commit `1cb311624b2ddf88e9e37873999d165a8cd28b46`. Exact source URLs and SHA-256 digests are in `style.json`. Font bytes are embedded into generated SVG before rasterization, so preview and export do not depend on host-installed fonts.

Run `sidecar/tools/generate_paper_ink_v2.py` to recompute resource hashes, validate the strict contracts, and regenerate the manifests and JSON Schemas.

The two manifest SHA-256 values are also pinned in `sidecar/src/atme/render/style_bundle.py`. Changing resource bytes or tokens while retaining `2.0.0` is rejected at runtime. An intentional revision requires a new versioned bundle and new pins.
