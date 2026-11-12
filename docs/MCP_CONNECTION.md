# ATME local MCP connection — Windows desktop

ATME includes a genuine stdio MCP adapter using the official Python SDK. The installed
launcher resolves the project store selected by the ATME installer every time it starts;
copied client settings no longer hard-code a database path. ChatGPT Desktop, Codex and
Claude Desktop are the only supported user-facing clients.

The MCP process establishes an authenticated loopback bridge to the running ATME desktop.
The UI reports a connection only after that live process/handshake reaches this exact
desktop instance. A shared SQLite row is not connection evidence.

## Launch

Use the Python executable from the ATME environment and select the intended project
database explicitly. Example launch from the repository:

    sidecar\.venv\Scripts\python.exe -m atme.mcp_server --database C:\ATME-data\jobs.db

The packaged sidecar accepts the stable command used by the AI Connection screen:

    atme-sidecar.exe mcp

The installed process resolves `HKCU\Software\ATME\ProjectDataDir`, matching the desktop.
`--database` remains available only as an explicit development/test override.

Claude Desktop uses standard `mcpServers` JSON. ChatGPT Desktop and Codex on the same
Windows host share `%USERPROFILE%\.codex\config.toml`; ATME displays a ready-to-copy TOML
block. Save/restart the client, then call `atme.get_capabilities` and `atme.list_projects`.

    {
      "mcpServers": {
        "atme": {
          "command": "C:/Users/USER/AppData/Local/ATME/atme-sidecar.exe",
          "args": ["mcp"]
        }
      }
    }

Grant access only to a trusted AI client: it can read and revise projects in the selected
database. It cannot choose arbitrary paths or execute shell commands through ATME tools.
Stdio opens no public network listener. Its desktop acknowledgement uses only the running
ATME process's authenticated `127.0.0.1` endpoint and short-lived runtime discovery file.
ChatGPT Web is not a supported local client; use the Windows desktop app.

## Optional TypeSafe Jev decisions

Jev is not an LLM author and is not required for ATME. Add `TYPESAFE_API_KEY` to the
ATME MCP server's environment in the client configuration to enable
`atme.evaluate_with_jev`. The tool supports `visual_treatment`, `scene_density`, and
`revision_route`. Results are advisory, revision-bound typed decisions; the call never
writes an artifact, changes the timeline, or renders. The connected AI remains responsible
for scripts, semantic transcription, storyboard and layout authorship.

## Implemented MCP tools

- atme.get_capabilities
- atme.get_schema
- atme.list_projects (bounded ID pagination)
- atme.create_project
- atme.get_project_state
- atme.get_project_artifact
- atme.get_visual_compilation_context (read-only v2 production basis and draft fingerprint)
- atme.write_artifact
- atme.approve_script (only after explicit user approval of that exact revision)
- atme.list_source_media
- atme.get_narrative_source
- atme.read_authoritative_audio
- `atme://projects/{id}/authoritative-narrative` binary resource
- atme.prepare_timing (non-blocking local timing request)
- atme.get_timing_status
- atme.validate_project
- atme.preview_project (bounded PNG from the exact project revision)
- atme.render_project (explicit, non-blocking queue request)
- atme.get_render_status
- atme.set_output_profile
- atme.list_project_assets
- `atme://projects/{id}/assets/{asset_id}` integrity-checked binary resource
- atme.list_revision_requests
- atme.submit_revision_proposal
- atme.evaluate_with_jev (optional, advisory and read-only)

Writes use expected_revision. Domain failures return isError plus structured code,
message and validation errors; an invalid write leaves the revision unchanged.
Externally authored brief/script/storyboard/layout artifacts are stored as immutable
versions. Storyboard uses the existing VisualPlan schema; layout uses the existing
LayoutDoc contract. Selected-range revision requests are bounded by project revision and
timeline interval. The connected AI can submit one schema-validated proposal; applying or
rejecting it remains a local user decision. Supporting project assets are immutable inputs
and never become narrative authority.

Storyboards and layouts record their source script revision. Changed scripts or newly
attached media make earlier plans stale; clients must revise them rather than assuming
old timing remains correct. Geometry writes do not revoke unchanged script approval.

## Authoritative Narrative Source

ATME does not require an approved script for every project:

- Script-based projects use the exact approved external script as semantic authority and
  the selected user recording as timing authority.
- Audio-only and video-only projects use the user recording as both narrative and timing
  authority. A script-shaped artifact supplied later by the connected AI is a derived
  transcript/scene index for planning and rendering; it requires no script approval and
  never supersedes the recording.

The connected AI can inspect authoritative audio through `atme.read_authoritative_audio`; for
video authority this is the locally extracted audio track and the original video remains authority.
Audio and video originals up to 128 MiB are also available through the integrity-checked MCP
binary resource; larger videos use the audio tool or the user's direct client attachment.
`atme.prepare_timing` accepts either an approved script plus recording or a recording-only
source. Recording-only timing contains anonymous speech-unit bounds and confidence, never
locally recognized words. After the connected AI supplies derived semantic structure, a new
timing run binds its text to the recording's technical timebase while keeping the recording
authoritative. Timing and render requests return durable IDs for status polling.

## Direct local media upload

Upload PCM WAV bytes to the authenticated local HTTP service:

    POST /projects/{id}/media/wav?expected_revision=N
    Authorization: Bearer LOCAL_SERVICE_TOKEN
    Content-Type: audio/wav

The service retains the original bytes and exposes only technical metadata through MCP:
hash, duration, sample rate, channels and frame count. No semantic transcript is created.
PCM WAV ingress supports up to 64 MiB. Video ingress streams MP4, MOV, MKV or WebM up to
1 GiB, retains the original as authority, and creates a private local PCM timing derivative.
Derivative paths are never returned through MCP or HTTP. The desktop project intake
supports script+audio, script+video, audio-only and video-only authority modes.

## Compilation, preview and render

Validation requires an authoritative narrative source, current externally authored storyboard
and layout revisions, and a semantic scene structure. Script-authority projects additionally
require exact script approval; recording-authority projects do not. Layout aspect ratio
must match the selected 16:9 or 9:16 profile, and authored timing must fit the narration.

`atme.render_project` requires `confirmed: true` and the exact current revision. It returns
a durable run ID without waiting for encoding; poll `atme.get_render_status`. Retrieve a
completed MP4 through the authenticated local service:

    GET /projects/{id}/renders/{run_id}/output

The compiler copies exact immutable inputs into a fingerprinted private runtime. No tool
accepts a source or output filesystem path. A missing or corrupt derived output is rebuilt.
The local acoustic model supplies timing only. Exposed labels come from either the approved
external script or a connected-AI-derived index, according to the explicit authority mode.

Automated network-isolation acceptance produces and integrity-checks real MP4 files for
both 1280×720 and 720×1280 using the real polish/render/mux path. Its acoustic timestamps
use an installed-engine double and its narration is synthetic. A live external-AI flow,
original human narration/local-model quality, desktop connection UX, native packaging and
full media-format acceptance remain separate gates.

## Authoring a stored v2 production

Read the current project, its narrative authority, the selected output profile and the
schema for each artifact. Submit the approved script or recording-derived scene index,
then write the v2 storyboard and executable layout with `atme.write_artifact`. Use each
returned project revision for the next write. The same tool accepts `resolved_timeline`
with contract version `2.0.0`. The authoring client supplies the compiled actions and
measured timing against the stored plan, layout and edited recording. ATME verifies
their revisions, canonical SHA-256 fingerprints, owned asset references and action
coverage when it stores that result. A subsequent edit requires a new matching timeline.

Use `atme.get_visual_compilation_context(project_id, expected_revision)` after
each write. Copy its `project` and `narrative_authority` fields into the storyboard.
Copy `layout_basis` into the authored layout. After storing the layout, copy
`resolved_basis` into the resolved timeline. Call the same read-only operation with
that timeline as `resolved_draft` to receive its exact `compilation_fingerprint`.
Set that field and submit the document with `atme.write_artifact`. A missing basis
indicates a missing or stale prerequisite. ATME computes these hashes locally.
The connected producer supplies authored actions,
measured triggers and the action-specific evidence or continuity required by its plan.

Call `atme.validate_project`, request a frame with `atme.preview_project`, then request
the confirmed render. Both output profiles use 30 fps. Placed camera footage supplies
the video base under the authored ink. For a sound cue or music, upload the sound as
a project asset, use its measured duration, and author explicit bus, playback and fade
policies. The export mixes these cues with mastered narration. Standalone storyboard
sound descriptions need executable actions to be audible. Fetch the MP4 through the
authenticated output endpoint or use **Save MP4** in Studio.

SDK reference: https://github.com/modelcontextprotocol/python-sdk
