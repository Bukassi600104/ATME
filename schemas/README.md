# Contracts (versioned)

Every stage boundary in the pipeline is a versioned JSON Schema. Agents, renderer, and UI all
speak these contracts; sidecar tests validate the bundled examples against them on every run
(golden-file discipline). Breaking changes require a new file version, not an edit in place.

The legacy filenames below remain immutable v1 contracts. Visual pipeline v2 is an additive,
strict contract family generated reproducibly from `sidecar/src/atme/store/contracts_v2.py` by
`sidecar/tools/generate_v2_schemas.py`. The checked-in JSON files are the distributable contract
read by MCP and non-Python clients; generation plus golden tests prevent model/schema drift.

Paper & Ink v2 production resources are governed by
`paper-ink-style-v2.schema.json` and `paper-ink-assets-v2.schema.json`. Their
checked instances live under `production-assets/paper-ink-v2`, are verified by
SHA-256 at runtime, and are packaged with the sidecar.

- fact-sheet.schema.json       output of Research+Verifier (S5)
- script-scenes.schema.json    output of Scriptwriter (S6)
- excalidraw-layout.schema.json output of Spatial/Layout agent (S7)
- cue-timeline.schema.json     output of Alignment (S9), consumed by renderer (S10)

Visual pipeline v2:

- visual-plan-v2.schema.json                 semantic directing plan authored through MCP
- executable-layout-v2.schema.json           deterministic typed scene graph and board activations
- resolved-visual-timeline-v2.schema.json    timing-resolved canonical actions and validation state
- migration-report-v2.schema.json            immutable v1-to-v2 provenance and degradation record

V2 authoring/storage is available before v2 rendering. Capabilities therefore report authoring
versions and renderer versions separately. A v2 layout must never be passed to the v1 renderer;
until the v2 action runtime is installed, validation returns `renderer_contract_unsupported`.

Examples live in examples/ and MUST validate (enforced by sidecar/tests/test_contracts.py).
