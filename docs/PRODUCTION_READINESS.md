# ATME production audit and live-test plan

12 November 2026. Scope includes the Windows Studio, local HTTP and MCP services, SQLite projects, media and timing, renderer, export, packaging, source recovery and user-visible delivery. The baseline is the integrated source at `f3a759a1`. The installed September application, the source checkout and a newly built installer are separate deliverables.

## Where the production path broke

The apparent loop had multiple causes. Historical verification repeatedly exercised renderer internals while the public project dispatcher still rejected v2 layouts. The interrupted full run produced no terminal result. Independently, a worker that terminated after recording a running status could leave the Studio waiting forever. Only the last of these requires recovering an individual project job. Render progress and software-development progress should be measured separately.

| Area | What exists | Finding and work required |
| --- | --- | --- |
| Project and authoring | Local projects, revisioned script/storyboard/layout, undo, scoped media, authenticated HTTP and stdio MCP | Keep the existing project service. Script-led projects require approval of the displayed script. Recording-led projects retain the recording as authority and let the connected AI supply structure. A stale Studio dialog could act on a different revision. Bind review, preview and edits to the project and revision displayed. |
| Media and timeline | Managed originals, clip placement, linked audio/video, editing, playback and derived caches | Importing another source could change narrative selection even when the intended recording was placed. Some cache paths ignored the chosen output profile. A manual export could return the original source container under an MP4 filename. Resolve authority from the edited timeline, pin inputs and encode the requested output. |
| Timing and jobs | Local speech recognition, measured timings, immutable render snapshots, SQLite run history | Abrupt worker exit left queued/running rows with no owner. Repeated submissions could wait on a nonexistent worker. Claim each revision-bound run across processes, surface interruption, and allow an explicit retry. Reuse intact completed results. |
| Visual production | A legacy renderer, a typed visual-plan compiler, paper/ink resources, asset checks and a v2 frame compositor | At baseline the production dispatcher rejected all stored v2 layouts. Standalone renderer tests could succeed while a real project could neither preview nor export. Exercise the same stored project and compositor through the public preview and MP4 paths. Restrict advertised support to combinations the engine can deliver. |
| Sound and camera | Mastering, word alignment, AAC mux and camera/ink composition | In a talking-head export the final mux could copy camera audio and the manifest could describe the pre-composite video. Select mastered audio explicitly and hash the bytes after the last mux. Authored sound events and camera underneath typed v2 artwork require separate audiovisual proof. |
| Desktop and delivery | Tauri project launcher, viewer, timeline, inspector and render history | The Studio could display older network responses, hide a saved storyboard until layout existed, and give little explanation for a stopped render. Surface saved beats, exact revisions, worker errors and a downloadable finished movie. |
| Installer and recovery | Rust/TypeScript application, frozen Python runtime, FFmpeg, NSIS and existing Git history | The installed build predates the integrated renderer work. A Windows FFmpeg launcher can be mistaken for the encoder. The runtime also needs the speech detector data. Package real dependencies, restrict upgrade cleanup to the installed path and exercise the built payload. Preserve source history and restore a clean, publishable branch from GitHub. |
| Quality and operations | Extensive renderer, contract and fixture tests, historical reports and local recordings | The interrupted regression has 1,445 passing call records, an incomplete final record and no terminal result. It cannot certify the full suite. A human’s review of pacing, intelligibility, fidelity to the script and suitability for publication is distinct from programmatic delivery checks. |

## Completion plan

1. **Secure the work.** Restore the GitHub source snapshot into an independent checkout. Compare required code, contracts, fonts, artwork, lockfiles and tests. Preserve private working history separately and list every exclusion.
2. **Make one saved revision authoritative.** Exercise two clients, late Studio responses, changes to timeline selection and output profile. Success means the exact reviewed text, placed recording, canvas and source revision reach the exported file.
3. **Make interrupted work actionable.** Verify a real process exit releases its claim, a second client cannot duplicate a live job, a failed launch is visible and an explicit retry completes. Use a named check with a terminal result for each defect.
4. **Deliver through the public entry points.** Create and reopen a project, author through MCP, prepare speech timing, preview saved artwork, render both orientations, decode the MP4 and verify its recorded hash. For supported v2 work, verify the MP4 actually contains the authored pixels. Record any unsupported combination at validation.
5. **Deliver the Windows candidate.** Build from the integrated source, verify encoder and model dependencies, then run the packaged HTTP/stdio and Studio against disposable data. Save the installer digest and repeatable live-test instructions. Preserve the existing installation and projects.
6. **Decide launch scope from evidence.** Exercise an operator-selected original recording with the intended connected AI. Review the exported movie in a player. Resolve each outstanding delivery or creative-quality failure against that saved revision. An installer tested on a second Windows machine establishes fresh-install behavior beyond the development host.

No project-wide rewrite is needed. The work to start afresh is the release artifact, its reproducible verification and a current release record. Keep the stored projects, original media, renderer/compiler, asset catalog, editor and project APIs. Historical phase documents remain development history.

## Audit coverage and source recovery

The inventory at engineering checkpoint `e2d46e85` contains 116 tracked files under the Python runtime, 262 under its tests, seven under the desktop source directories, 24 under schemas, 28 production asset files, six prompts and 26 benchmark files. A syntax pass parsed 400 Python files and 23 JSON contracts/examples. Type checking and behavioral Studio tests complement that pass. An older benchmark script emitted a nonfatal Python escape-sequence warning. This inventory describes coverage of the review. A passing file count is insufficient evidence for an audiovisual feature.

The first independent GitHub restore matched the integrated source, lockfiles, contracts, artwork, fonts and tests. The separately verified November production checkpoint contains the first 51 engineering changes in this audit. The public branch omits generated binaries, build caches, source research documents, customer project data and local diagnostics. Eligible internal engineering history and earlier reports have an owner-only backup. The private crash dump stays on the workstation.

- [Public production source branch](https://github.com/Bukassi600104/ATME/tree/backup/production-source-20261112)
- [Verified 51-file checkpoint](https://github.com/Bukassi600104/ATME/commit/ec36c1fd9142aaa1800c0e9200127a083d670c63)

## Live operator test

1. Start the candidate with a separate project directory for the first run. Open a project and choose **Help → Speech timing model**. Prepare the English model. On a new machine the first preparation needs access to the model weights. Subsequent timing can use the local copy.
2. Open **AI Connection** and copy the configuration for the intended client. After connecting, confirm the Studio indicates an active session. Create a project and upload the recording. Place the intended media on the timeline.
3. Ask the connected AI to read the project state and capabilities, submit the script or recording-derived scene structure, prepare timing, and author the storyboard and layout for the selected profile. For a script-led project, read the displayed script and approve that revision in Studio.
4. Review the storyboard and seek the preview. Open **Export Check**, resolve any listed issues, then select **Render**. A successful run appears under **Renders**. Open it and choose **Save MP4**. Manual timeline export is available for a video edit that has no authored animation.
5. Play the saved file in an independent player and check intelligibility, timing, framing and artwork. Close and reopen the same project and retrieve the same completed run. Test a second orientation with a layout authored for its canvas.
