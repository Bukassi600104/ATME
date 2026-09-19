# External production without API keys

Approved 2026-09-08. This is the initial structured-input adapter, not the complete studio/MCP refactor.

> V4 authority correction: the combined script/layout adapter below remains a transitional
> script-based path. The project service also supports audio-only and video-only projects,
> where the uploaded recording is the Authoritative Narrative Source and no script approval
> is required. See `MCP_CONNECTION.md` for the current authority and pre-layout timing flow.

## Inputs

Prepare two UTF-8 JSON files with an external tool of your choice:

- Script: match `schemas/script-scenes.schema.json`. Include topic and at least two scenes with unique scene_id, phase, spoken_text and visual_directive.
- Layout: match `schemas/excalidraw-layout.schema.json` and the runtime LayoutDoc rules. Include an explicit board_timeline, all script scenes, original drawable elements, and valid camera intent. `schemas/examples/board-continuity.example.json` demonstrates the structure, not a finished production.

The combined request is limited to 12 MiB. The initial import preset is 1280×720 at 30 fps. Do not substitute a prose storyboard or the research packet's schema for these runtime contracts.

In Compose choose both files and import. ATME validates them, stores the supplied inputs and pauses for approval. Narration is read-only to avoid silently invalidating the matching layout. For script changes, create a revised matching pair and import as a new project; the previous project remains available.

After approval, upload your original continuous narration. Settings only prepares the local alignment model. A model download may require internet and disk space, but never a user creative-provider API key.

## Final-audio board revisions

After polished audio and reliable alignment exist, export planning context in visual review. Give the exported JSON to your external AI with this instruction:

> Propose board continuity using this measured narration context and supplied object inventory. Return only a JSON object with two fields: source_hashes copied unchanged from the export, and proposal matching proposal_schema. Use existing board/object identities and global word indices; the first activation starts at zero via a null anchor. Preserve geometry, camera, scene ownership and evidence provenance. Do not invent timing confidence, unavailable words, or new objects. Use persistent boards, meaningful evidence excursions and returns where the explanation warrants them; sponsorship is optional, never a mandatory segment.

Import the returned proposal JSON (maximum 1 MiB). The engine checks its anchors against actual narration, rejects stale/uncertain context, and leaves the saved layout unchanged until explicit acceptance. Compare rendered frames first. Acceptance preserves a layout backup and requires realignment/rendering.

HTTP clients use the existing bearer authentication:

- POST /jobs/external: {"script": ScriptScenes, "layout": LayoutDoc}
- GET /jobs/{id}/board-proposal/context: measured context, revision, inventory and proposal schema
- POST /jobs/{id}/board-proposal?revision=HASH: {"source_hashes": exported hashes, "proposal": proposal JSON}, not an AI-generation command
- Existing proposal preview and accept endpoints remain available.

ATME does not claim to have independently fact-checked external narration. External tools may charge for their own services. Existing encrypted credentials and historical usage records are retained but not needed or read by this workflow. Original-narration quality acceptance and full MCP integration remain separate gates.
