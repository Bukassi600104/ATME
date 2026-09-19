// ATME frontend entry. Talks to the loopback sidecar using host-provided token/port.
import { invoke } from "@tauri-apps/api/core";
import { mountBoardEditor } from "./board-editor";

interface SidecarInfo { port: number; token: string; ready: boolean; }

let sidecarReady: Promise<SidecarInfo> | null = null;
async function sidecar(): Promise<SidecarInfo> {
  if (sidecarReady === null) {
    sidecarReady = (async () => {
      const deadline = Date.now() + 65_000;
      while (Date.now() < deadline) {
        const info = await invoke<SidecarInfo>("sidecar_info");
        if (info.ready) {
          if ($("job-status").textContent === "starting") $("job-status").textContent = "idle";
          return info;
        }
        $("job-status").textContent = "starting";
        await new Promise((resolve) => window.setTimeout(resolve, 400));
      }
      throw new Error("The local media engine did not start within 60 seconds.");
    })().catch((error) => {
      sidecarReady = null;
      throw error;
    });
  }
  return await sidecarReady;
}

const $ = <T extends HTMLElement = HTMLElement>(id: string) =>
  document.getElementById(id) as T;

type ViewName = "compose" | "run" | "review" | "voice-upload" | "library" | "settings";
type Stage = { name: string; status: string };

interface Scene {
  scene_id: number; phase: string; spoken_text: string;
  visual_directive: string; est_seconds?: number; claim_ids?: string[];
}
interface ScriptDoc { topic?: string; title?: string; scenes: Scene[]; }

type ProjectInputKind = "script+audio" | "script+video" | "audio-only" | "video-only";
interface ProjectState {
  project_id: number;
  revision: number;
  input_kind: ProjectInputKind;
  status: string;
  approved_script_revision: number | null;
  artifacts: Record<string, number>;
  authoritative_narrative_source: {
    mode: "script_authority" | "recording_authority";
    ready_for_timing: boolean;
  };
}

let currentJob: number | null = null;
let pollTimer: number | null = null;
let eventSource: EventSource | null = null;

function show(view: ViewName): void {
  for (const v of ["compose", "run", "review", "voice-upload", "library", "settings"] as ViewName[]) {
    const el = document.getElementById(v);
    if (el) el.classList.toggle("hidden", v !== view);
  }
  document.querySelectorAll(".navlink").forEach((b) => {
    b.classList.toggle("active", (b as HTMLElement).dataset.view === view);
  });
}

function drawRunLine(stages: Stage[]): void {
  const path = $("runline-path") as unknown as SVGPathElement;
  const n = Math.max(1, stages.length);
  const w = 1000, pad = 16;
  const seg = (w - pad * 2) / n;
  let d = "";
  const y = 12;
  stages.forEach((s, i) => {
    const x0 = pad + i * seg;
    const x1 = x0 + seg * 0.86;
    if (s.status === "done") d += ` M ${x0} ${y} L ${x1} ${y}`;
    else if (s.status === "running") d += ` M ${x0} ${y} l ${seg * 0.5} 0`;
  });
  path.setAttribute("d", d.trim() || `M ${pad} ${y} l 0.01 0`);
}

async function refresh(jobId: number): Promise<string> {
  const info = await sidecar();
  const res = await fetch(`http://127.0.0.1:${info.port}/jobs/${jobId}`,
    { headers: { Authorization: `Bearer ${info.token}` } });
  const state = await res.json();
  drawRunLine(state.stages);
  $("job-status").textContent = state.job.status;
  $("run-meta").textContent =
    `resume point: ${state.resume_point} · done: ${state.done_stages.length}`;
  return state.job.status as string;
}

function logLine(s: string): void {
  $("log").textContent += "\n" + s;
  const pre = $("log") as HTMLPreElement;
  pre.scrollTop = pre.scrollHeight;
}

function stopWatchers(): void {
  if (pollTimer !== null) { window.clearInterval(pollTimer); pollTimer = null; }
  if (eventSource !== null) { eventSource.close(); eventSource = null; }
}

function projectError(value: unknown, fallback: string): string {
  if (!value || typeof value !== "object") return fallback;
  const payload = value as { detail?: string | { message?: string }; message?: string };
  if (typeof payload.detail === "string") return payload.detail;
  if (payload.detail && typeof payload.detail.message === "string") return payload.detail.message;
  return payload.message || fallback;
}

async function projectRequest<T>(path: string, init?: RequestInit): Promise<T> {
  const info = await sidecar();
  const headers = new Headers(init?.headers);
  headers.set("Authorization", `Bearer ${info.token}`);
  const response = await fetch(`http://127.0.0.1:${info.port}${path}`, { ...init, headers });
  const value = await response.json().catch(() => null) as T | null;
  if (!response.ok) throw new Error(projectError(value, `ATME request failed (${response.status}).`));
  if (value === null) throw new Error("ATME returned an empty response.");
  return value;
}

function refreshNarrativeFields(): void {
  const kind = ($<HTMLSelectElement>("project-input-kind")).value as ProjectInputKind;
  const scriptBased = kind.startsWith("script+");
  $("project-script-row").classList.toggle("hidden", !scriptBased);
  const recording = $<HTMLInputElement>("project-recording");
  recording.accept = kind.endsWith("video")
    ? "video/mp4,video/quicktime,video/x-matroska,video/webm,.mp4,.mov,.mkv,.webm"
    : "audio/wav,.wav";
  $("project-source-explanation").textContent = scriptBased
    ? `The external script supplies meaning; your ${kind.endsWith("video") ? "video" : "WAV"} supplies exact timing.`
    : `Your ${kind === "video-only" ? "video" : "WAV"} is both the narrative and timing authority. Your connected AI may derive a semantic scene index through MCP.`;
}

async function waitForProjectTiming(projectId: number, runId: string): Promise<Record<string, unknown>> {
  const deadline = Date.now() + 120_000;
  while (Date.now() < deadline) {
    const state = await projectRequest<Record<string, unknown>>(`/projects/${projectId}/timing/${runId}`);
    if (state.status === "done" || state.status === "failed") return state;
    await new Promise((resolve) => window.setTimeout(resolve, 500));
  }
  throw new Error("Timing continues in the background. Open this project again to check its status.");
}

async function createAuthoritativeProject(): Promise<void> {
  const title = $<HTMLInputElement>("project-title").value.trim();
  const profile = $<HTMLSelectElement>("project-profile").value;
  const inputKind = $<HTMLSelectElement>("project-input-kind").value as ProjectInputKind;
  const scriptFile = $<HTMLInputElement>("project-script").files?.[0];
  const recording = $<HTMLInputElement>("project-recording").files?.[0];
  const feedback = $("project-feedback");
  const result = $("project-result");
  const button = $<HTMLButtonElement>("create-project");
  let createdState: ProjectState | null = null;
  result.classList.add("hidden");
  if (!title) { feedback.textContent = "Enter a project title."; return; }
  if (inputKind.startsWith("script+") && !scriptFile) {
    feedback.textContent = "Choose the externally authored script JSON for this project."; return;
  }
  if (!recording) { feedback.textContent = "Choose the authoritative recording."; return; }
  const wantsVideo = inputKind.endsWith("video");
  const extension = recording.name.slice(recording.name.lastIndexOf(".")).toLowerCase();
  if (wantsVideo !== [".mp4", ".mov", ".mkv", ".webm"].includes(extension)) {
    feedback.textContent = wantsVideo ? "Choose an MP4, MOV, MKV, or WebM video." : "Choose an uncompressed PCM WAV recording.";
    return;
  }
  button.disabled = true;
  feedback.textContent = "Creating the project…";
  try {
    let scriptDocument: ScriptDoc | null = null;
    if (scriptFile) {
      if (scriptFile.size > 1024 * 1024) throw new Error("Script JSON exceeds 1 MiB.");
      scriptDocument = JSON.parse(await scriptFile.text()) as ScriptDoc;
    }
    let state = await projectRequest<ProjectState>("/projects", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title, profile, input_kind: inputKind }),
    });
    createdState = state;
    if (scriptDocument) {
      state = await projectRequest<ProjectState>(`/projects/${state.project_id}/artifacts/script`, {
        method: "PUT", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ document: scriptDocument, expected_revision: state.revision }),
      });
      createdState = state;
      state = await projectRequest<ProjectState>(`/projects/${state.project_id}/script-approval`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ script_revision: state.artifacts.script,
          expected_revision: state.revision, approved: true }),
      });
      createdState = state;
    }
    feedback.textContent = `Uploading ${recording.name}…`;
    const mediaPath = wantsVideo ? "video" : "wav";
    const media = await projectRequest<{ project: ProjectState }>(
      `/projects/${state.project_id}/media/${mediaPath}?expected_revision=${state.revision}`, {
        method: "POST", headers: wantsVideo
          ? { "Content-Type": recording.type || "application/octet-stream", "X-Filename": recording.name }
          : { "Content-Type": "audio/wav" }, body: recording,
      });
    state = media.project;
    createdState = state;
    feedback.textContent = "Preparing local technical speech timing…";
    const timing = await projectRequest<{ run_id: string }>(`/projects/${state.project_id}/timing`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ expected_revision: state.revision }),
    });
    const timingState = await waitForProjectTiming(state.project_id, timing.run_id);
    const timingDocument = timingState.timing as { status?: string } | undefined;
    const next = state.authoritative_narrative_source.mode === "recording_authority"
      ? "Connect your external AI through MCP so it can derive and store the semantic scene structure."
      : "Connect your external AI through MCP to create the storyboard and production layout.";
    feedback.textContent = "Authoritative narrative stored and timed locally.";
    result.textContent = `Project #${state.project_id} · revision ${state.revision}\nAuthority: ${state.authoritative_narrative_source.mode.replace("_", " ")}\nTiming: ${timingDocument?.status || timingState.status}\nNext: ${next}`;
    result.classList.remove("hidden");
  } catch (error) {
    feedback.textContent = error instanceof Error ? error.message : "Project creation failed.";
    if (createdState) {
      result.textContent = `Project #${createdState.project_id} was saved at revision ${createdState.revision}.\nResolve the message above, then continue through MCP; no uploaded source has been discarded.`;
      result.classList.remove("hidden");
    }
  } finally {
    button.disabled = false;
  }
}

/** Live progress: SSE primary, poll fallback. Closes on terminal/paused states. */
function watch(jobId: number): void {
  stopWatchers();
  void (async () => {
    const info = await sidecar();
    const es = new EventSource(
      `http://127.0.0.1:${info.port}/jobs/${jobId}/events?token=${encodeURIComponent(info.token)}`);
    eventSource = es;
    es.addEventListener("progress", (ev) => {
      try {
        const data = JSON.parse((ev as MessageEvent).data) as { phase: string };
        logLine(`[${data.phase}]`);
      } catch { /* ignore malformed */ }
    });
    pollTimer = window.setInterval(async () => {
      const status = await refresh(jobId);
      if (status === "done" || status === "failed" || status === "paused" ||
          status === "waiting_voice" || status === "voice_rejected" ||
          status === "canceled") {
        stopWatchers();
        if (status === "done") logLine("final.mp4 ready in the Library.");
        else if (status === "waiting_voice") {
          $("job-status").textContent = "voice needed";
          logLine("Script approved. Upload your original voiceover to continue.");
          show("voice-upload");
        } else if (status === "voice_rejected") {
          logLine("The recording does not match the approved script closely enough.");
          await showVoiceReport(jobId);
          show("voice-upload");
        } else if (status === "paused") {
          if (await jobWasReviewed(jobId)) {
            $("job-status").textContent = "paused";
            logLine("Paused at a safe checkpoint. Click Resume when ready.");
          } else {
            $("job-status").textContent = "review";
            logLine("Paused for your review - edit scenes, then approve.");
            await openReview(jobId);
          }
        } else logLine(status === "failed" ? "run failed - see events." : "canceled.");
      }
    }, 1500);
  })();
}

async function importExternal(): Promise<void> {
  const script = ($("external-script") as HTMLInputElement).files?.[0];
  const layout = ($("external-layout") as HTMLInputElement).files?.[0];
  const feedback = $("external-feedback");
  if (!script || !layout) { feedback.textContent = "Choose both script and production layout JSON files."; return; }
  const button = $("import-external") as HTMLButtonElement; button.disabled = true;
  try {
    if (script.size + layout.size > 12 * 1024 * 1024) throw new Error("Inputs exceed the 12 MiB limit.");
    const payload = { script: JSON.parse(await script.text()), layout: JSON.parse(await layout.text()) };
    const info = await sidecar();
    const response = await fetch(`http://127.0.0.1:${info.port}/jobs/external`, {
      method: "POST", headers: { Authorization: `Bearer ${info.token}`, "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.detail || "Import failed.");
    feedback.textContent = "Imported without AI calls. Review the supplied script before uploading narration.";
    await openReview(result.job_id);
  } catch (error) { feedback.textContent = error instanceof Error ? error.message : "Import failed."; }
  finally { button.disabled = false; }
}

async function controlJob(action: "pause" | "resume" | "cancel"): Promise<void> {
  if (currentJob === null) return;
  const info = await sidecar();
  const response = await fetch(
    `http://127.0.0.1:${info.port}/jobs/${currentJob}/control`, {
      method: "POST",
      headers: { Authorization: `Bearer ${info.token}`, "Content-Type": "application/json" },
      body: JSON.stringify({ action }),
    });
  const result = await response.json().catch(() => ({ detail: "Control request failed" }));
  if (!response.ok) { logLine(result.detail || "Control request failed"); return; }
  logLine(`[${result.status}]`);
  if (action === "resume") watch(currentJob);
  if (result.status === "canceled") { stopWatchers(); await refresh(currentJob); }
}

async function showVoiceReport(jobId: number): Promise<void> {
  const info = await sidecar();
  const response = await fetch(
    `http://127.0.0.1:${info.port}/jobs/${jobId}/voice-report`,
    { headers: { Authorization: `Bearer ${info.token}` } });
  if (!response.ok) return;
  const report = await response.json() as { comparison?: {
    similarity?: number; missing_words?: string[]; unexpected_words?: string[];
  }};
  const comparison = report.comparison;
  if (!comparison) return;
  const similarity = Math.round((comparison.similarity || 0) * 100);
  const missing = (comparison.missing_words || []).slice(0, 12).join(", ");
  const extra = (comparison.unexpected_words || []).slice(0, 12).join(", ");
  $("voice-feedback").textContent =
    `Script match ${similarity}%. ${missing ? `Missing: ${missing}. ` : ""}` +
    `${extra ? `Unexpected: ${extra}. ` : ""}Upload a corrected take to continue.`;
}

// ---------- review ----------
interface TimingEvent {
  target_id: string; scene_id: number; phrase: string; status: string;
  match_count?: number; confidence?: number | null; at_ms?: number;
}

async function loadTimingReport(button: HTMLButtonElement): Promise<void> {
  const output = button.parentElement?.querySelector<HTMLElement>("[data-timing-report]");
  if (!output) return;
  const jobId = currentJob;
  if (jobId === null) { output.textContent = "Select a job first."; return; }
  button.disabled = true;
  output.textContent = `Loading timing report for job ${jobId}…`;
  try {
    const info = await sidecar();
    const response = await fetch(`http://127.0.0.1:${info.port}/jobs/${jobId}/narration-events`,
      { headers: { Authorization: `Bearer ${info.token}` } });
    if (!response.ok) throw new Error(`Could not load timing report (${response.status}).`);
    const report = await response.json() as { status: string; events: TimingEvent[] };
    if (currentJob !== jobId) { output.textContent = "Job changed. Load its report again."; return; }
    output.replaceChildren();
    const heading = document.createElement("p");
    const statuses: Record<string, string> = {
      not_available: "No timing report yet. Align the final voice recording first.",
      no_triggers: "No explicit phrase triggers were authored for this alignment.",
      resolved: "All authored phrase triggers resolved in this saved report.",
      needs_review: "Some phrase triggers need revision before rendering.",
    };
    heading.textContent = `Job ${jobId}: ${statuses[report.status] || "Unknown report status."}`;
    output.append(heading);
    for (const event of report.events) {
      const row = document.createElement("p");
      const confidence = typeof event.confidence === "number"
        ? `${Math.round(event.confidence * 100)}%` : "unavailable";
      const time = typeof event.at_ms === "number" ? `${(event.at_ms / 1000).toFixed(3)}s` : "unresolved";
      row.textContent = `Scene ${event.scene_id} · ${event.target_id} · “${event.phrase}” — ` +
        `${event.status.replaceAll("_", " ")} · time: ${time} · ` +
        `matches: ${event.match_count ?? 0} · confidence: ${confidence}`;
      output.append(row);
    }
  } catch (error) {
    output.textContent = error instanceof Error ? error.message : "Could not load timing report.";
  } finally { button.disabled = false; }
}

async function openReview(jobId: number, visualOnly = false): Promise<void> {
  currentJob = jobId;
  const info = await sidecar();
  const auth = { Authorization: `Bearer ${info.token}` };
  const res = await fetch(`http://127.0.0.1:${info.port}/jobs/${jobId}/script`,
                          { headers: auth });
  if (!res.ok) { show("run"); return; }
  const doc = (await res.json()) as ScriptDoc;
  document.querySelector("#review h1")!.textContent = visualOnly ? "Visual review" : "Script review";
  document.querySelector("#review .hint")!.textContent = visualOnly
    ? "Approved narration is read-only here. Edit evidence or board timing, then resume to realign and render."
    : "Review the imported script, then approve and upload your original voice. To revise narration, import a matching revised script and layout.";
  $("approve").textContent = visualOnly ? "Resume with visual changes" : "Approve & continue";
  $("cancel-job").textContent = visualOnly ? "Back to Library" : "Cancel job";
  mountBoardEditor($("board-editor"), jobId, info);
  const evidenceResponse = await fetch(`http://127.0.0.1:${info.port}/jobs/${jobId}/evidence`, { headers: auth });
  const evidence = evidenceResponse.ok ? await evidenceResponse.json() as { slots: Array<{
    id: string; scene_id: number; provenance: { kind: string; description: string; source_url?: string }
  }>; boards: Array<{ board_id: string }>;
    activations: Array<{ board_id: string; start_ms: number; end_ms: number }>;
    canvas: { width: number; height: number } | null;
  } : { slots: [], boards: [], activations: [], canvas: null };

  const wrap = $("scenes");
  wrap.innerHTML = "";
  for (const s of doc.scenes) {
    const card = document.createElement("div");
    card.className = "scene-card";
    const label = document.createElement("div");
    label.className = "phase";
    label.textContent = `scene ${s.scene_id} - ${s.phase}`;
    const ta = document.createElement("textarea");
    ta.rows = 3; ta.value = s.spoken_text; ta.dataset.sid = String(s.scene_id);
    ta.readOnly = true;
    const preview = document.createElement("img");
    preview.className = "scene-preview";
    preview.alt = `Draft drawing through scene ${s.scene_id}`;
    void fetch(`http://127.0.0.1:${info.port}/jobs/${jobId}/preview/${s.scene_id}`,
      { headers: auth }).then(async (response) => {
        if (response.ok) preview.src = URL.createObjectURL(await response.blob());
      });
    const editor = document.createElement("div");
    editor.append(label, ta);
    const sceneSlots = evidence.slots.filter((item) => item.scene_id === s.scene_id);
    const newSlotId = `el-evidence-${crypto.randomUUID()}`;
    if (evidence.boards.length > 0) sceneSlots.push({
      id: newSlotId, scene_id: s.scene_id,
      provenance: { kind: "original_illustration", description: "" },
    });
    else {
      const hint = document.createElement("p");
      hint.textContent = "New evidence placement requires an authored board timeline. This layout has none yet.";
      editor.append(hint);
    }
    for (const slot of sceneSlots) {
      const creating = slot.id === newSlotId;
      let created = false;
      const controls = document.createElement("fieldset");
      const legend = document.createElement("legend");
      legend.textContent = creating ? "Add evidence image to a board" : `Replace evidence: ${slot.id}`;
      const board = document.createElement("select");
      board.setAttribute("aria-label", "Evidence board activation");
      for (const activation of evidence.activations) {
        const option = document.createElement("option");
        option.value = activation.board_id;
        option.dataset.start = String(activation.start_ms);
        option.textContent = `${activation.board_id}: ${activation.start_ms}–${activation.end_ms} ms`;
        board.append(option);
      }
      const placement: Record<string, HTMLInputElement> = {};
      if (creating) {
        const explanation = document.createElement("p");
        explanation.textContent = "Adds an overlay to this board; does not create a new board or move existing objects. Coordinates use a 50-pixel grid. Reveal time uses final-audio milliseconds.";
        controls.append(explanation, board);
        for (const [key, value] of Object.entries({
          x: 0, y: 0, width: Math.min(400, Math.floor((evidence.canvas?.width || 400) / 50) * 50),
          height: Math.min(200, Math.floor((evidence.canvas?.height || 200) / 50) * 50),
          appear_at_ms: evidence.activations[0]?.start_ms || 0,
        })) {
          const label = document.createElement("label"); label.textContent = key.replaceAll("_", " ");
          const input = document.createElement("input"); input.type = "number";
          input.min = key === "width" || key === "height" ? "50" : "0";
          input.step = key === "appear_at_ms" ? "1" : "50"; input.value = String(value);
          label.append(input); controls.append(label); placement[key] = input;
        }
        board.onchange = () => { placement.appear_at_ms.value = board.selectedOptions[0]?.dataset.start || "0"; };
      }
      const file = document.createElement("input");
      file.type = "file"; file.accept = "image/png"; file.setAttribute("aria-label", "Replacement PNG");
      const description = document.createElement("input");
      description.value = slot.provenance.description;
      description.setAttribute("aria-label", "Evidence description");
      const kind = document.createElement("select");
      kind.setAttribute("aria-label", "Evidence provenance");
      for (const [value, text] of [["original_illustration", "Original illustration"], ["external_evidence", "External evidence"]]) {
        const option = document.createElement("option"); option.value = value; option.textContent = text;
        kind.append(option);
      }
      kind.value = slot.provenance.kind;
      const source = document.createElement("input");
      source.type = "url"; source.value = slot.provenance.source_url || "";
      source.placeholder = "Source URL (required for external evidence)";
      source.setAttribute("aria-label", "Evidence source URL");
      const save = document.createElement("button"); save.textContent = creating ? "Add evidence PNG" : "Save replacement PNG";
      const feedback = document.createElement("p"); feedback.setAttribute("role", "status");
      save.onclick = async () => {
        save.disabled = true;
        try {
          const selected = file.files?.[0];
          if (!selected || selected.size > 8 * 1024 * 1024) throw new Error("Choose a PNG up to 8 MiB.");
          feedback.textContent = "Validating and saving…";
          const bytes = await selected.arrayBuffer();
          const digest = await crypto.subtle.digest("SHA-256", bytes);
          const sha256 = Array.from(new Uint8Array(digest), (b) => b.toString(16).padStart(2, "0")).join("");
          const png_base64 = await new Promise<string>((resolve, reject) => {
            const reader = new FileReader(); reader.onerror = () => reject(new Error("Could not read PNG."));
            reader.onload = () => resolve(String(reader.result).split(",")[1]);
            reader.readAsDataURL(new Blob([bytes]));
          });
          const result = await fetch(`http://127.0.0.1:${info.port}/jobs/${jobId}/evidence/${encodeURIComponent(slot.id)}`, {
            method: creating ? "POST" : "PUT", headers: { ...auth, "Content-Type": "application/json" },
            body: JSON.stringify({ png_base64, sha256, provenance: {
              kind: kind.value, description: description.value.trim(),
              ...(source.value.trim() ? { source_url: source.value.trim() } : {}) },
              ...(creating ? { placement: { scene_id: s.scene_id, board_id: board.value,
                ...Object.fromEntries(Object.entries(placement).map(([key, input]) => [key, Number(input.value)])) } } : {}) }),
          });
          const body = await result.json();
          if (!result.ok) throw new Error(body.detail || "Could not save evidence.");
          created = creating;
          feedback.textContent = "Saved. Previous layout backed up. Resume to realign and rerender.";
          const updated = await fetch(`http://127.0.0.1:${info.port}/jobs/${jobId}/preview/${s.scene_id}`, { headers: auth });
          if (updated.ok) {
            if (preview.src.startsWith("blob:")) URL.revokeObjectURL(preview.src);
            preview.src = URL.createObjectURL(await updated.blob());
          }
        } catch (error) { feedback.textContent = error instanceof Error ? error.message : "Evidence import failed."; }
        finally { save.disabled = created; }
      };
      controls.prepend(legend);
      controls.append(file, kind, description, source, save, feedback);
      editor.append(controls);
    }
    card.append(editor, preview);
    wrap.appendChild(card);
  }
  ($("approve") as HTMLButtonElement).onclick = async () => {
    if (visualOnly) {
      currentJob = jobId; show("run"); await controlJob("resume"); return;
    }
    const edited: Scene[] = doc.scenes.map((s) => {
      const ta = wrap.querySelector(
        `textarea[data-sid='${s.scene_id}']`) as HTMLTextAreaElement | null;
      return { ...s, spoken_text: ta ? ta.value : s.spoken_text };
    });
    const response = await fetch(`http://127.0.0.1:${info.port}/jobs/${jobId}/review`, {
      method: "POST",
      headers: { ...auth, "Content-Type": "application/json" },
      body: JSON.stringify({ approved: true, scenes: edited }) });
    const result = await response.json();
    currentJob = jobId;
    if (result.status === "waiting_voice") show("voice-upload");
    else { show("run"); watch(jobId); }
  };
  ($("cancel-job") as HTMLButtonElement).onclick = async () => {
    if (visualOnly) { show("library"); await loadLibrary(); return; }
    await fetch(`http://127.0.0.1:${info.port}/jobs/${jobId}/review`, {
      method: "POST",
      headers: { ...auth, "Content-Type": "application/json" },
      body: JSON.stringify({ approved: false }) });
    $("job-status").textContent = "canceled";
    show("compose");
  };
  show("review");
}

async function uploadVoice(): Promise<void> {
  if (currentJob === null) return;
  const input = $("voice-file") as HTMLInputElement;
  const file = input.files?.[0];
  if (!file) {
    $("voice-feedback").textContent = "Choose a recording first.";
    return;
  }
  const button = $("upload-voice") as HTMLButtonElement;
  button.disabled = true;
  $("voice-feedback").textContent = `Uploading ${file.name}…`;
  try {
    const info = await sidecar();
    const response = await fetch(
      `http://127.0.0.1:${info.port}/jobs/${currentJob}/voice`, {
        method: "POST",
        headers: { Authorization: `Bearer ${info.token}`, "X-Filename": file.name,
                   "Content-Type": file.type || "application/octet-stream" },
        body: file,
      });
    const result = await response.json().catch(() => ({ detail: "Upload failed" }));
    if (!response.ok) throw new Error(result.detail || "Upload failed");
    const warnings = (result.quality?.warnings || []) as string[];
    $("voice-feedback").textContent = warnings.length
      ? `Uploaded with warning: ${warnings.join("; ")}` : "Voiceover accepted. Rendering started.";
    show("run");
    watch(currentJob);
  } catch (error) {
    $("voice-feedback").textContent = error instanceof Error ? error.message : String(error);
  } finally {
    button.disabled = false;
  }
}

// ---------- library ----------
async function loadLibrary(): Promise<void> {
  const info = await sidecar();
  const res = await fetch(`http://127.0.0.1:${info.port}/jobs`,
    { headers: { Authorization: `Bearer ${info.token}` } });
  const data = (await res.json()) as {
    jobs: Array<{ id: number; title: string; topic: string; status: string;
                  video_path?: string | null; video_bytes?: number | null;
                  duration_ms?: number | null; cost_usd?: number | null;
                  created_at: number }>;
  };
  const rows = $("lib-rows");
  rows.innerHTML = "";
  for (const j of data.jobs) {
    const row = document.createElement("div");
    row.className = "lib-row";
    row.innerHTML = `<span class="t"></span><span class="m"></span>
                     <span class="lib-actions"></span><span class="pill mono">${j.status}</span>`;
    (row.querySelector(".t") as HTMLElement).textContent =
      j.title || j.topic || ("Job " + j.id);
    const bits = [`#${j.id}`, new Date(j.created_at * 1000).toLocaleDateString()];
    if (j.duration_ms) bits.push(`${Math.round(j.duration_ms / 600) / 100} min`);
    if (j.video_bytes) bits.push(`${(j.video_bytes / 1048576).toFixed(1)} MB`);
    if (j.cost_usd) bits.push(`$${j.cost_usd.toFixed(3)}`);
    (row.querySelector(".m") as HTMLElement).textContent = bits.join(" · ");
    const actions = row.querySelector(".lib-actions") as HTMLElement;
    if (["done", "paused", "failed", "waiting_voice", "voice_rejected"].includes(j.status)) {
      const edit = document.createElement("button");
      edit.className = "linkbutton"; edit.textContent = "Edit visuals";
      edit.onclick = () => void openReview(j.id, true);
      actions.append(edit);
    }
    if (j.video_path) {
      const open = document.createElement("button");
      open.className = "linkbutton"; open.textContent = "Open";
      open.onclick = () => void invoke("open_artifact", { path: j.video_path, reveal: false });
      const reveal = document.createElement("button");
      reveal.className = "linkbutton"; reveal.textContent = "Show in folder";
      reveal.onclick = () => void invoke("open_artifact", { path: j.video_path, reveal: true });
      actions.append(open, reveal);
    }
    if (["running", "paused", "failed", "waiting_voice", "voice_rejected"].includes(j.status)) {
      const continueButton = document.createElement("button");
      continueButton.className = "linkbutton";
      continueButton.textContent = "Continue";
      continueButton.onclick = () => void continueJob(j.id, j.status);
      actions.append(continueButton);
    }
    rows.appendChild(row);
  }
}

async function continueJob(jobId: number, status: string): Promise<void> {
  currentJob = jobId;
  if (status === "waiting_voice" || status === "voice_rejected") {
    if (status === "voice_rejected") await showVoiceReport(jobId);
    show("voice-upload");
    return;
  }
  if (status === "paused") {
    if (await jobWasReviewed(jobId)) {
      show("run");
      await controlJob("resume");
    } else {
      await openReview(jobId);
    }
    return;
  }
  show("run");
  if (status === "failed") await controlJob("resume");
  else watch(jobId);
}

async function jobWasReviewed(jobId: number): Promise<boolean> {
  const info = await sidecar();
  const response = await fetch(`http://127.0.0.1:${info.port}/jobs/${jobId}`,
    { headers: { Authorization: `Bearer ${info.token}` } });
  if (!response.ok) return false;
  const state = await response.json() as { done_stages?: string[] };
  return (state.done_stages || []).includes("reviewed");
}

async function loadSettings(): Promise<void> {
  const info = await sidecar();
  try {
    const connection = await invoke<{ command: string; args: string[] }>("mcp_connection_info");
    $<HTMLTextAreaElement>("mcp-config").value = JSON.stringify({
      mcpServers: { atme: { command: connection.command, args: connection.args } },
    }, null, 2);
  } catch (error) {
    $("mcp-feedback").textContent = error instanceof Error ? error.message : "Could not locate the local MCP server.";
  }
  const modelResponse = await fetch(
    `http://127.0.0.1:${info.port}/models/alignment`,
    { headers: { Authorization: `Bearer ${info.token}` } });
  if (modelResponse.ok) {
    const model = await modelResponse.json() as { status: string; error?: string | null };
    $("alignment-model-state").textContent = model.error
      ? `${model.status} — ${model.error}` : model.status.replace("_", " ");
  }
}

async function copyMcpConfig(): Promise<void> {
  const config = $<HTMLTextAreaElement>("mcp-config").value;
  if (!config) { $("mcp-feedback").textContent = "MCP configuration is not available yet."; return; }
  try {
    await navigator.clipboard.writeText(config);
    $("mcp-feedback").textContent = "MCP configuration copied. Paste it into your trusted AI client's MCP settings.";
  } catch {
    $<HTMLTextAreaElement>("mcp-config").select();
    $("mcp-feedback").textContent = "Copy was blocked; the configuration has been selected for manual copying.";
  }
}

async function prepareModel(): Promise<void> {
  const info = await sidecar();
  const response = await fetch(`http://127.0.0.1:${info.port}/models/alignment`, {
    method: "POST", headers: { Authorization: `Bearer ${info.token}` },
  });
  const result = await response.json().catch(() => ({ detail: "Could not start model setup" }));
  $("alignment-model-state").textContent = response.ok
    ? result.status : (result.detail || "setup failed");
}

window.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll<HTMLButtonElement>("[data-timing-refresh]").forEach((button) => {
    button.addEventListener("click", () => void loadTimingReport(button));
  });
  document.querySelectorAll(".navlink").forEach((b) => {
    b.addEventListener("click", () => {
      const view = (b as HTMLElement).dataset.view as ViewName;
      show(view);
      if (view === "library") void loadLibrary();
      if (view === "settings") void loadSettings();
    });
  });
  $("import-external").addEventListener("click", () => void importExternal());
  $("project-input-kind").addEventListener("change", refreshNarrativeFields);
  $("create-project").addEventListener("click", () => void createAuthoritativeProject());
  $("upload-voice").addEventListener("click", () => void uploadVoice());
  $("back-to-review").addEventListener("click", () => {
    if (currentJob !== null) void openReview(currentJob);
  });
  $("voice-file").addEventListener("change", () => {
    const file = ($("voice-file") as HTMLInputElement).files?.[0];
    $("voice-file-name").textContent = file ? file.name : "Choose your voiceover";
  });
  $("prepare-model").addEventListener("click", () => void prepareModel());
  $("copy-mcp-config").addEventListener("click", () => void copyMcpConfig());
  $("pause-run").addEventListener("click", () => void controlJob("pause"));
  $("resume-run").addEventListener("click", () => void controlJob("resume"));
  $("cancel-run").addEventListener("click", () => void controlJob("cancel"));
  refreshNarrativeFields();
  void loadSettings();
});
