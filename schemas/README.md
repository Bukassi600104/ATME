# Contracts (versioned)

Every stage boundary in the pipeline is a versioned JSON Schema. Agents, renderer, and UI all
speak these contracts; sidecar tests validate the bundled examples against them on every run
(golden-file discipline). Breaking changes require a new file version, not an edit in place.

- fact-sheet.schema.json       output of Research+Verifier (S5)
- script-scenes.schema.json    output of Scriptwriter (S6)
- excalidraw-layout.schema.json output of Spatial/Layout agent (S7)
- cue-timeline.schema.json     output of Alignment (S9), consumed by renderer (S10)

Examples live in examples/ and MUST validate (enforced by sidecar/tests/test_contracts.py).
