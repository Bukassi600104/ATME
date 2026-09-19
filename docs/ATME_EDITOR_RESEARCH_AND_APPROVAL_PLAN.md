# ATME editor behavior and architecture: research and proposed implementation

ATME should operate as a continuous, non-destructive video editor. One project owns its media and editing decisions. Importing supporting material, moving clips, adding graphics, undoing changes, and exporting do not create another project. The external AI interprets creative instructions and performs ordinary editing operations on the same document that the desktop displays.

This report is an approval proposal. Application changes, project changes, installation changes, and database migrations are outside this research deliverable.

## 1. Evidence boundaries

Official CapCut, Blackmagic Design, Adobe, and KDE documentation establishes documented editing behavior. OpenTimelineIO and MLT provide publicly described models for editorial data and audiovisual evaluation. These public models help explain design choices; they do not establish that CapCut, Premiere, or Resolve uses those libraries internally.

References were accessed on 14 September 2026. Adobe pages cited below carry January 2026 update dates; the KDE manual identifies itself as version 26.08; OpenTimelineIO's latest documentation identifies itself as 0.19.0.dev1. Several CapCut pages do not expose a publication date. Product screenshots and instructions can vary by release and platform. Desktop documentation is prioritized; a browser or mobile instruction is not assumed to prove Windows desktop behavior.

This is documentary research with a read-only inspection of the current ATME workspace. It is not a hands-on benchmark of installed competing editors, a certification of feature parity, or access to their proprietary implementation. Findings from ATME source describe the checkout inspected; equivalence with the installed binary has not been established during this research.

## 2. Documented editor mechanics

### Projects, media, and the timeline

CapCut's desktop overlay guide describes creating a project, importing the background video, placing it on the timeline, and importing additional visual material into that editing context. Supporting material becomes an overlay rather than an independent production. Its help page on previous projects says direct cross-draft import is unsupported and distinguishes importing an exported video from importing an editable project. These sources support separate concepts of project and media, not hidden project creation during import.[1][2]

Kdenlive's Quick Start explicitly separates the project bin, original-clip monitor, project monitor, and timeline. Saving records clip placement and effects; rendering produces the deliverable. Its example can be played after arranging clips, before final export. It also supports project import, which ATME is not required to copy.[3]

**ATME decision proposed:** Imports always target the open project's bin. Dropping into the timeline can additionally place a clip in that project. The only new-project path is an explicit action from the project screen after closing the active project. An external AI follows the same lifecycle. A render is an output associated with the existing project, and the project remains editable afterward.

### Editing operations have distinct meanings

Resolve documents insert, overwrite, replace, append, place-on-top, and ripple overwrite. Insert moves later material to make room; overwrite replaces material at the destination. Ripple trimming changes subsequent timing; slip changes which source frames are used without relocating the clip. Its Edit page also documents trimming during playback, titles above footage, keyframes, and picture-in-picture composition.[4]

**ATME decision proposed:** A normal move, insertion, overwrite, and ripple move must be separate operations with predictable effects. The AI chooses the operation appropriate to the request. Manual controls may expose familiar tools, snapping, track locks, and linked selection. Moving a clip to a later time can intentionally leave an empty gap; that is valid editing, not a failed project.

### Original media and timeline instances

OpenTimelineIO represents timelines using tracks, clips, gaps, and transitions. A clip refers to media and has a selected source range; the source reference and the timeline instance are different objects. Multiple tracks express simultaneous composition. OTIO describes editorial interchange rather than a complete renderer.[5]

**ATME decision proposed:** Preserve the source file and assign stable identities to its timeline uses. Splitting creates two clip instances that reference the same source. Deleting a timeline instance does not remove the imported file. Importing a second video does not automatically replace the primary narrative recording. A media item can supply different ranges in multiple positions within the same project.

### Linked picture, audio, and graphics

Adobe documents linking audio and video instances so moving and trimming can act on them together. It explicitly distinguishes linked timeline instances from the original source clips.[6]

**ATME decision proposed:** Presenter picture and its synchronized audio remain linked by default. Captions and Caleb events attach to the relevant clip or spoken phrase. A logo can instead be attached to the whole sequence. These attachments govern what moves; arbitrary absolute timestamps alone cannot keep a changing edit synchronized.

### History is not a collection of new projects

Premiere's History panel records operations and states inside the current project. Undo and redo change that project's editing state. Adobe notes that this panel's previous actions are unavailable after closing and reopening the project.[7]

**ATME decision proposed:** Keep one project identity and an internal edit history. Ten completed moves create ten reversible editing actions, not ten projects. A drag gesture should be one undoable action rather than hundreds of pointer-motion entries. Persistent history after restart remains an ATME requirement; it should not be presented as a universal behavior of all competitors.

### Playback and background processing

Adobe documents temporary preview files and selective reuse: unchanged segments can retain previews while affected parts are changed. This is evidence that an editor can recompute derived frames without treating the entire project as unusable.[8]

CapCut's missing-preview help identifies visibility, opacity, file compatibility, rendering problems, and playhead position as troubleshooting categories. It does not describe a script-approval or storyboard-validation prerequisite for watching imported footage.[9]

**ATME decision proposed:** The timeline viewer evaluates the current edit. There is no routine message that a clip move requires validation, no stale-project workflow, and no user requirement to regenerate a storyboard after dragging. Background processing can report progress when it matters. Previously computed frames must not masquerade as the current edit. If a heavy effect cannot play in real time, reduced preview quality or an explicit temporary effect bypass can preserve editing access.

### Export checks are different from editorial approval

CapCut documents export failures involving particular clips, missing linked media, and resources. This demonstrates that practical editors still encounter technical constraints. It does not establish a compulsory, separate validation ceremony before ordinary editing.[10]

**ATME decision proposed:** Keep technical safeguards but remove the generic production-validation gate from editing. Export checks should concern what is actually being exported: readable source ranges, supported effects, destination access, available resources, and encoder compatibility. Missing optional creative artifacts are not faults in a manually assembled video. AI approval of new wording is a creative workflow decision, not permission to play existing media.

## 3. Public architecture evidence and its limits

MLT describes frame-producing services, filters, transitions, multitrack composition, and consumers. Image and audio extraction can be deferred until requested. The consumer requests frames from the connected composition. This is a published example of an editor evaluating media at a requested time instead of relying on a preapproved narrative document.[11]

Kdenlive's published file-format documentation distinguishes project-wide properties from sequence properties. Its FAQ describes serialization of edit points and transitions for rendering. These are useful public examples of an editable document driving an output process; they do not require ATME to migrate to MLT or change its existing database.[12][13]

The proposed ATME structure is therefore:

```text
User's creative request → External AI ─┐
                                     ├→ Shared editing commands
Manual desktop editing ──────────────┘             │
                                                  ▼
                             One independent project document
                             • media bin and stable source IDs
                             • timeline clips and linked audio
                             • graphics, captions, effects
                             • Caleb board/event attachments
                             • reversible edit history
                                                  │
                                 Current composition evaluator
                                      /                  \
                              Timeline viewer       Export snapshot
```

This is an ATME recommendation informed by the sources, not a claim about CapCut's private architecture. Preserve the current transport and persistence choices unless a separately evidenced compatibility problem requires an approved change.

## 4. What “nothing becomes stale” should mean

The editing document must remain current after every accepted edit. Moving a clip should directly update its placement and attached visual events. The application should not leave the editor responsible for repairing a chain of script, timing, storyboard, and layout approvals.

That does not mean the software can reuse every previously computed frame forever. If footage at a timestamp changes, its displayed image must change. The proposed solution is localized automatic recomputation and time mapping, rather than a public stale flag or a global regeneration requirement.

The rules below are proposed ATME behavior:

| Edit | Immediate result | Automatic dependent behavior |
|---|---|---|
| Move a presenter clip | Picture and linked sound move together | Attached captions and drawings follow their clip-local positions |
| Trim the start | Earlier source frames stop appearing | Source-time attachments are clipped to the remaining range |
| Split a clip | Two independently editable instances appear | Attachments are partitioned without double-playing sound or events |
| Ripple-delete a pause | Gap closes on participating tracks | Later linked events shift by the same amount |
| Delete a spoken passage | That footage and sound are removed | Its attached graphics stop appearing; other material remains usable |
| Add supporting footage to the bin | New media becomes available | The active narrative and timeline stay as they were |
| Add a cutaway above the presenter | Cutaway covers the chosen interval | Presenter audio continues unless an audio edit was requested |
| Move a sequence-wide logo | Its position changes | Unrelated narration and boards require no recomputation |
| Adjust speed | Clip duration changes | Sound and anchored events use the same retiming map |
| Undo | Previous edit state returns | Playback and dependent objects follow that state |

Technical time relationships can be updated deterministically. A major rearrangement may change the meaning of an explanation; no time-mapping system can guarantee creative coherence. The external AI can review narrative flow when instructed to revise the edit, without blocking playback or silently undoing manual decisions.

A video clip moved away from the playhead can legitimately leave an empty viewer at that time. ATME must show the correct gap and continue playing through it. It must not replace that situation with a validation warning. Exact diagnosis of the reported incident still needs a live reproduction because a gap, a failed playback ticket, and a UI race are different causes.

## 5. Automatic interpretation without a mode selector

ATME should expose media facts to the external AI: audio/video streams, duration, dimensions, available timeline placement, and existing project intent. The external AI interprets speech, images, and the user's request. No internal generative AI layer is required.

File type alone is insufficient to decide creative role. An MP4 may be a presenter, a screen recording, silent B-roll, or an exported animation. A WAV may be narration, music, or a sound effect. Import does not give a file narrative authority simply because it is the latest file.

The proposed automatic behavior is:

- An idea and requested duration start research and script preparation in an explicitly created project. Once narration is available, measured speech timing drives production.
- A script supplies intended words; the external AI arranges a voiceover workflow and requests only genuinely missing inputs.
- Narration audio supplies the spoken narrative and timing. Transcript analysis helps editing; a routine transcript is not turned into a fresh-script approval obstacle.
- Presenter footage remains the picture and sound foundation. Caleb overlays, reframing, captions, and cutaways are added around its meaning.
- Mixed footage and supporting material coexist in one project. The AI uses context and the user's stated intent to assign roles. Only material ambiguity requires a short plain-language question.

For “create a three-minute explanation of Pi Network Solo Host,” the AI should handle research, structure, pacing, asset choices, and the Caleb plan. It should not ask for internal schemas or a production-mode label. If no narration exists, that is a real missing input; the system should not falsely claim a complete voiced video is ready.

For “use the video and create a video for me,” the AI should inspect the active project, identify the intended footage, understand the content, make the editing decisions, and present a reviewable result. The same project remains active throughout. Existing script-review and final-preview approvals follow the user's creative preferences, independently of ordinary editing availability.

## 6. Why validation exists today, and what should replace its current role

The current ATME checkout groups several concerns under one ready/not-ready result: script approval, presence of storyboard/layout, their dependencies, media availability, and layout timing/aspect checks. These concerns are valid for a narrowly scripted production pipeline but are too broadly coupled for a general editor.

The replacement should use four scoped responsibilities:

| Responsibility | When it runs | User experience |
|---|---|---|
| Edit integrity | When applying an operation | Valid operations apply immediately; an impossible trim gets a specific explanation |
| Media/playback health | During import and playback | Identify the unreadable or offline clip; retain access to the rest of the project |
| Creative review | When the user wants new scripts or AI output reviewed | Show the actual creative result, without locking manual tools |
| Export readiness | At export | Check the chosen output and report actionable failures |

Examples of acceptable messages are “This source file is missing—locate it,” “This trim extends beyond the recording,” or “The export folder is not writable.” “Your storyboard is stale” after a clip move is not an acceptable normal editing experience.

The absence of a global gate must not mean accepting corrupt editing commands, silently showing old results, or falsely declaring an unfinished export successful. Those checks remain engine responsibilities and should be as localized as possible.

## 7. ATME evidence checked against the proposed design

The following source observations are confirmed in the inspected workspace:

- `app/src/studio.ts`, `uploadSource` and `uploadAsset`, address the current project ID. The inspected import functions do not create another project.
- `sidecar/src/atme/source_timeline.py` updates the existing `project_state` row by project ID and records edit history. The inspected move/history path does not prove duplicate-project creation.
- `app/src/studio.ts`, `togglePreviewPlayback`, contains the exact “Preview playback becomes available when validation passes” fallback when the source player is hidden and `render_ready` is false.
- `loadSourcePlayback` initially clears/hides the source player and then requests a playback ticket. A failure or race may expose that fallback. This is a code-supported hypothesis, not a reproduced root cause.
- `ProjectService.artifact` marks dependencies stale on timeline-version mismatch. `ProjectRunner.validate` treats stale storyboard/layout artifacts as issues.
- Prior source inspection showed production compilation copying narrative audio into the board-render path without preserving the presenter picture. Installed-runtime behavior needs verification in the implementation phase.

The earlier assertion that timeline movement creates a new project was incorrect. Internal history versions and separate projects must not be conflated. Likewise, the conflicting desktop/MCP project lists do not yet prove that the two live processes resolve the same physical database file. That remains an open diagnostic question.

## 8. Revised implementation sequence for approval

**Stage 1 — Project identity and shared state.** Establish the actual desktop/MCP storage discrepancy without merging or overwriting divergent data. Enforce explicit create/open/close project boundaries in UI and external commands. Ensure import and edit operations remain attached to the intended independent project. Preserve source files and existing work.

**Stage 2 — Continuous timeline editing and playback.** Remove production readiness as a condition for normal timeline playback. Make gaps, linked picture/audio, clip positions, seek behavior, and undo/redo consistent. Keep source inspection available, while the primary project viewer shows the current composition. Recompute only affected output automatically rather than asking for artifact regeneration.

**Stage 3 — Unified composition for mixed media.** Preserve source video, audio, captions, transparent Caleb graphics, and full-screen boards in one editing model. Implement attachment rules for move/trim/split/ripple operations. Preview and export must evaluate the same timeline semantics; preview may use a lower resolution but must preserve timing and layer order.

**Stage 4 — External AI as an editor.** Expose available media, active project context, capabilities, and ordinary edit commands. The AI infers creative roles, follows Caleb rules, and performs bounded undoable changes. It reads current state before acting. Simultaneous manual edits must not be silently overwritten: independent changes can be accepted; overlapping changes require the AI to reread and adapt. Technical conflicts must not become a stale-project repair task for the user.

**Stage 5 — Connection and delivery usability.** Retain the previously requested connection workspace and updater as separate workstreams. Connection instructions must be verified for each client's actual supported transport and release before advertising one-click or local connectivity. The earlier blanket statement that ChatGPT Desktop necessarily accepts this stdio configuration is not established by this editor research. Updates require a verified distribution/signing setup before the app can truthfully advertise available updates.

The editor should keep familiar visible areas: project name and save state, media bin, current timeline viewer, timeline tracks, selection inspector, undo/redo, and export. Diagnostic IDs and schemas belong in advanced connection details. There should be no forced talking-head/voiceover mode selector and no Validate button required to unlock ordinary work.

## 9. Acceptance criteria

| Test | Required result |
|---|---|
| Import ten supporting files | Same project ID and project count; files appear in its bin |
| Move a clip ten times | One project, ten completed undoable moves; no stale workflow |
| Move a clip leaving an initial gap | Viewer shows the gap and plays into the clip normally |
| Undo and redo a move | Position, linked audio, and attached graphics return together |
| Import music after presenter footage | Music does not become the primary narrative automatically |
| Add B-roll above presenter | Correct picture layering and continuous intended audio |
| Split and trim speech | Surviving captions and graphics stay with their intended speech |
| Edit without a script/storyboard | Normal source and timeline playback remains available |
| Export a manually assembled video | No AI artifact or script-approval prerequisite |
| Change the edit while frames are processing | Obsolete results do not overwrite the current viewer |
| AI edit after a manual edit | Current state is respected; unrelated edits survive |
| Two external clients act | No duplicate project or silent loss of edits |
| Close and reopen | Same independent project and saved edit state |
| Create another project | Explicit close/home/create lifecycle; no nested project |
| Export and continue editing | Project stays editable; completed export stays associated with its captured edit |
| 30-second presenter test | Presenter preserved; overlays, cutaways, and audio align in preview and export |
| Voiceover test | Caleb boards and supporting media play without requiring presenter footage |
| Compare desktop and MCP | Same project identities and observable edit state |

Performance testing should measure drag response, seek latency, playback smoothness, and concurrent edit behavior on the actual machine. Numeric targets should be set from a baseline rather than promised without measurements. Passing an export command alone is insufficient: representative frames, audio continuity, and an actual playback review are required.

## 10. Sources

1. CapCut, [How to Add Overlays on CapCut](https://www.capcut.com/resource/how-to-add-capcut-overlays), publication date not displayed; accessed 14 September 2026. Desktop import and overlay workflow.
2. CapCut Help, [How Do I Import A Previous Project into The Current Project?](https://www.capcut.com/help/import-a-previous-project-into-the-current-project), publication date not displayed; accessed 14 September 2026. Project import limitation and exported-media distinction.
3. KDE, [Kdenlive Quick Start](https://docs.kdenlive.org/en/getting_started/quickstart.html), manual 26.08; accessed 14 September 2026. Bin, monitors, timeline, saving, playback, rendering.
4. Blackmagic Design, [DaVinci Resolve — Edit](https://www.blackmagicdesign.com/products/davinciresolve/edit), current product documentation; accessed 14 September 2026. Edit operations, live trimming, compositing, transforms.
5. OpenTimelineIO, [Timeline Structure](https://opentimelineio.readthedocs.io/en/latest/tutorials/otio-timeline-structure.html), documentation 0.19.0.dev1; accessed 14 September 2026. References, source ranges, tracks, gaps, transitions.
6. Adobe, [Link audio and video clips](https://helpx.adobe.com/premiere/desktop/add-audio-effects/basic-audio-editing/link-audio-and-video-clips.html), updated 7 January 2026. Linked timeline instances.
7. Adobe, [View or make changes in the History panel](https://helpx.adobe.com/ca/premiere/desktop/edit-projects/correct-mistakes/view-or-make-changes-in-the-history-panel.html), updated 21 January 2026. Undoable actions and session-history limits.
8. Adobe, [Use preview files when rendering](https://helpx.adobe.com/ca/premiere/desktop/render-and-export/render-sequences-for-playback/use-preview-files-when-rendering.html), updated 21 January 2026. Preview reuse and affected segments.
9. CapCut Help, [Why Is My Video Not Showing in CapCut?](https://www.capcut.com/help/video-not-showing-in-capcut), publication date not displayed; accessed 14 September 2026. Playback troubleshooting.
10. CapCut Help, [How Do I Fix Export Issues in CapCut?](https://www.capcut.com/help/export-issues), publication date not displayed; accessed 14 September 2026. Export failure categories. Troubleshooting suggestions are evidence of failure categories, not blanket recommendations to disable security software.
11. MLT, [Framework documentation](https://www.mltframework.org/docs/framework/), accessed 14 September 2026. Public frame-processing model.
12. KDE, [Kdenlive file format](https://github.com/KDE/kdenlive/blob/master/dev-docs/fileformat.md), moving master branch; accessed 14 September 2026. Project versus sequence properties.
13. KDE, [Kdenlive FAQ](https://docs.kdenlive.org/en/troubleshooting/faq.html), manual 26.08; accessed 14 September 2026. Published rendering architecture.

Local evidence: `app/src/studio.ts`, `sidecar/src/atme/project_service.py`, `sidecar/src/atme/source_timeline.py`, `sidecar/src/atme/project_runner.py`; prior diagnostic notes in `docs/ATME_MCP_DESKTOP_PROJECT_VIEW_INCONSISTENCY.md` and `docs/ATME_TALKING_HEAD_CALEB_TEST_FINDINGS.md`. These support ATME-specific findings, not claims about other editors.
