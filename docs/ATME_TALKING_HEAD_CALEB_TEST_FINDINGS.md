# ATME talking-head Caleb-style test findings

Status: In progress

Observed: 2026-09-14 (Africa/Lagos)

## Test subject

- Desktop project: `Test` (project ID 1)
- Source: `Untitled_Video.mp4`
- Media ID: `95c7f7fd93e94caaab614a404e7d68ff`
- Source duration: 284,757 ms
- Profile: `LONG_FORM_16_9`
- Transcript artifact: script revision 7, 49 scenes, 781 words

## Findings to preserve

1. **MCP/Desktop project visibility remains inconsistent.** The stdio MCP sidecar lists no projects, while the running desktop HTTP sidecar exposes project 1 and its media. Test work therefore used the authenticated desktop sidecar. This is the same unresolved class of issue recorded in `ATME_MCP_DESKTOP_PROJECT_VIEW_INCONSISTENCY.md`.
2. **Imported talking-head video is configured as script-authority.** The project has `input_kind: idea-first` and requires approval of an external script before timing/planning, despite the source itself containing the narrative recording. The locally derived transcript had to be stored as script revision 7 to continue through the current workflow.
3. **The current project renderer does not composite the talking-head video.** `ProjectRunner.compile` materializes `timing_audio`, copies it as narration, and passes script/layout/audio to the Caleb renderer. It does not copy or composite the authoritative source-video picture. A successful render under the current code would be a whiteboard animation with the source audio, not a Caleb-style edit layered over the talking head.
4. **The desired test cannot yet prove talking-head styling.** It can exercise transcription, timing, Caleb board planning, validation and whiteboard rendering, but it cannot demonstrate preservation of the presenter, punch-ins, talking-head cuts, or graphic overlays on the source footage.

No architecture or renderer fix was made during this test. The original source timeline remains intact; only script revision 7 was added from the local transcription.
