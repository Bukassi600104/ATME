import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import { getCurrentWindow } from "@tauri-apps/api/window";

interface SidecarInfo { port: number; token: string; ready: boolean }
interface NarrativeSource { mode: "script_authority" | "recording_authority"; ready_for_timing: boolean; ready_for_planning: boolean; semantic_structure: { ready: boolean } }
interface ProjectState { project_id: number; title: string; revision: number; profile: "LONG_FORM_16_9" | "SHORT_FORM_9_16"; input_kind: string; status: string; approved_script_revision: number | null; artifacts: Record<string, number>; authoritative_narrative_source: NarrativeSource; render_ready: boolean }
interface MediaItem { media_id: string; name?: string; kind: "audio" | "video"; format: string; bytes: number; duration_ms: number; revision: number; sample_rate?: number; channels?: number }
interface TimelineClip { clip_id: string; media_id: string; kind: "audio" | "video"; stream?: "audio" | "video" | "linked_av"; track_index?: number; audio_enabled?: boolean; source_start_ms: number; source_end_ms: number; timeline_start_ms: number; link_group_id: string; crossfade_ms: number }
interface SourceTimeline { timeline_revision: number; project_revision: number; operation: string; document: { contract_version: string; duration_ms: number; clips: TimelineClip[] }; history: EditHistory }
interface Waveform { resolution_ms: number; duration_ms: number; peaks: Array<[number, number, number]>; silences: Array<{ start_ms: number; end_ms: number; duration_ms: number }> }
interface AssetItem { asset_id: string; name: string; format: string; media_type: string; bytes: number; revision: number; role: string }
interface ValidationIssue { code: string; message: string }
interface Validation { ready: boolean; project_revision: number; issues: ValidationIssue[]; selected_revisions: Record<string, number | null> }
interface ScriptScene { scene_id: number; phase: string; spoken_text: string; visual_directive: string; est_seconds?: number }
interface ScriptDoc { topic?: string; title?: string; scenes: ScriptScene[] }
interface LayoutElement { id: string; scene_id: number; board_id: string; appear_at_ms: number; kind?: string; layer?: number; visibility_intervals?: Array<{ start_ms: number; end_ms: number }> }
interface LayoutDoc { elements: LayoutElement[]; board_timeline?: { activations: Array<{ board_id: string; start_ms: number; end_ms: number }> } }
interface RevisionRequest { request_id: string; project_revision: number; selection: { kind: string; id: string; start_ms: number; end_ms: number }; instruction: string; status: string; proposal?: { artifact_kind: string; document: object; summary: string } }
interface McpSession { session_id: string; active: boolean; client_identity: string | null; started_at: number; last_seen_at: number; last_activity_at: number | null; last_tool: string | null; last_project_id: number | null; call_count: number }
interface McpActivity { active: boolean; active_session_count: number; client_identities: string[]; identity_available: boolean; last_activity_at: number | null; last_tool: string | null; last_project_id: number | null; recent_project_ids: number[]; sessions: McpSession[]; version?: number; connection_evidence?: string }
interface StudioSync { project_version: string; mcp: McpActivity }
interface EditHistory { can_undo: boolean; can_redo: boolean; undo_label: string | null; redo_label: string | null }

const $ = <T extends HTMLElement = HTMLElement>(id: string) => document.getElementById(id) as T;
const state: {
  project: ProjectState | null; projects: ProjectState[]; media: MediaItem[]; assets: AssetItem[];
  script: ScriptDoc | null; layout: LayoutDoc | null; validation: Validation | null;
  playheadMs: number; durationMs: number; zoom: number; previewUrl: string | null;
  selected: { kind: string; id: string; label: string; startMs: number; endMs: number } | null;
  projectVersion: string | null; mcp: McpActivity | null;
  editHistory: EditHistory; sourceTimeline: SourceTimeline | null; showSilences: boolean;
} = { project: null, projects: [], media: [], assets: [], script: null, layout: null, validation: null,
  playheadMs: 0, durationMs: 60_000, zoom: 1, previewUrl: null, selected: null,
  projectVersion: null, mcp: null,
  editHistory: { can_undo: false, can_redo: false, undo_label: null, redo_label: null },
  sourceTimeline: null, showSilences: false };
let mediaTab: "sources" | "assets" = "sources";
let inspectorTab: "scene" | "style" | "audio" | "ai" = "scene";
let previewTimer: number | null = null;
let rangeAnchorMs: number | null = null;
let syncInFlight = false;
let connectionDetailsRoot: HTMLElement | null = null;
let lastOverlayRefresh = 0;
let viewerClip: TimelineClip | null = null;
let viewerUsesCleanedTimeline = false;
const selectedClipIds = new Set<string>();
let playheadDragTarget: HTMLElement | null = null;
let activeTool: "select" | "blade" = "select";
let snapping = true;
const waveformCache = new Map<string, Waveform>();
const objectUrls = new Set<string>();

let sidecarReady: Promise<SidecarInfo> | null = null;
async function sidecar(): Promise<SidecarInfo> {
  if (!sidecarReady) sidecarReady = (async () => {
    const deadline = Date.now() + 65_000;
    while (Date.now() < deadline) {
      const info = await invoke<SidecarInfo>("sidecar_info");
      if (info.ready) return info;
      await new Promise((resolve) => window.setTimeout(resolve, 350));
    }
    throw new Error("The local media engine did not start.");
  })().catch((error) => { sidecarReady = null; throw error; });
  return sidecarReady;
}

function apiError(value: unknown, fallback: string): string {
  if (!value || typeof value !== "object") return fallback;
  const payload = value as { detail?: string | { message?: string }; message?: string };
  if (typeof payload.detail === "string") return payload.detail;
  if (payload.detail && typeof payload.detail.message === "string") return payload.detail.message;
  return payload.message || fallback;
}

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const info = await sidecar();
  const headers = new Headers(init?.headers);
  headers.set("Authorization", `Bearer ${info.token}`);
  const response = await fetch(`http://127.0.0.1:${info.port}${path}`, { ...init, headers });
  const value = await response.json().catch(() => null) as T | null;
  if (!response.ok) throw new Error(apiError(value, `Request failed (${response.status}).`));
  if (value === null) throw new Error("ATME returned an empty response.");
  return value;
}

async function apiBlobUrl(path: string): Promise<string> {
  const info = await sidecar();
  const response = await fetch(`http://127.0.0.1:${info.port}${path}`, { headers: { Authorization: `Bearer ${info.token}` } });
  if (!response.ok) throw new Error(`Media request failed (${response.status}).`);
  const url = URL.createObjectURL(await response.blob()); objectUrls.add(url); return url;
}

function toast(message: string): void {
  const node = $("toast"); node.textContent = message; node.classList.remove("hidden");
  window.setTimeout(() => node.classList.add("hidden"), 3200);
}

function formatTime(ms: number): string {
  const seconds = Math.max(0, Math.floor(ms / 1000));
  return `${String(Math.floor(seconds / 60)).padStart(2, "0")}:${String(seconds % 60).padStart(2, "0")}`;
}
function formatBytes(bytes: number): string {
  return bytes >= 1048576 ? `${(bytes / 1048576).toFixed(1)} MB` : `${Math.max(1, Math.round(bytes / 1024))} KB`;
}
function friendlyStatus(project: ProjectState): string {
  if (project.render_ready) return "Ready to render";
  const source = project.authoritative_narrative_source;
  if (!source.ready_for_timing) return "Needs narration";
  if (!source.semantic_structure.ready) return "AI planning needed";
  return "Production in progress";
}

async function loadProjects(selectId?: number): Promise<void> {
  const response = await api<{ projects: ProjectState[] }>("/projects");
  state.projects = response.projects;
  renderProjectList();
  const id = selectId ?? state.project?.project_id;
  if (id) await openProject(id);
  else { renderEmptyStudio(); showProjectBrowser(true); }
}

function formatActivityTime(value: number | null): string {
  if (value === null) return "No tool activity recorded";
  return new Date(value * 1000).toLocaleString();
}

function renderMcpStatus(): void {
  const activity = state.mcp;
  const dot = $("connection-dot");
  dot.classList.toggle("good", activity?.active === true);
  dot.classList.toggle("neutral", activity?.active !== true);
  const identity = activity?.identity_available
    ? activity.client_identities.join(", ")
    : "Client identity unavailable";
  $("connection-status").textContent = activity?.active
    ? `MCP connected live${activity.identity_available ? ` · ${identity}` : ""}`
    : "MCP inactive";
  $("project-access").textContent = activity?.last_project_id
    ? `Recent project #${activity.last_project_id}${activity.last_tool ? ` · ${activity.last_tool.replace("atme.", "")}` : ""}`
    : identity;
  if (connectionDetailsRoot && activity) {
    connectionDetailsRoot.replaceChildren();
    const heading = document.createElement("h3"); heading.textContent = activity.active ? "MCP active" : "MCP inactive";
    const client = document.createElement("p"); client.textContent = identity;
    const last = document.createElement("p"); last.textContent = `Last activity: ${formatActivityTime(activity.last_activity_at)}`;
    const access = document.createElement("p"); access.textContent = activity.last_project_id
      ? `Recent access: project #${activity.last_project_id}${activity.last_tool ? ` via ${activity.last_tool}` : ""}`
      : "No recent project access";
    const sessions = document.createElement("p"); sessions.textContent = `${activity.active_session_count} active logical session${activity.active_session_count === 1 ? "" : "s"}`;
    connectionDetailsRoot.append(heading, client, last, access, sessions);
  }
}

async function watchMcpConnection(): Promise<void> {
  let after = state.mcp?.version || 0;
  while (true) {
    try {
      const activity = await api<McpActivity>(`/studio/mcp/wait?after=${after}`);
      state.mcp = activity; after = activity.version || after; renderMcpStatus();
    } catch { await new Promise(resolve => window.setTimeout(resolve, 1500)); }
  }
}

async function refreshStudioSync(forceProjects = false): Promise<void> {
  if (syncInFlight) return;
  syncInFlight = true;
  try {
    const sync = await api<StudioSync>("/studio/sync");
    state.mcp = sync.mcp;
    renderMcpStatus();
    if (!forceProjects && sync.project_version === state.projectVersion) return;
    const response = await api<{ projects: ProjectState[] }>("/projects");
    state.projectVersion = sync.project_version;
    state.projects = response.projects;
    renderProjectList();
    const currentId = state.project?.project_id;
    if (!currentId) {
      renderEmptyStudio();
      showProjectBrowser(true);
      return;
    }
    const updated = state.projects.find((project) => project.project_id === currentId);
    if (!updated) {
      if (state.projects[0]) await openProject(state.projects[0].project_id, false);
      else renderEmptyStudio();
    } else if (updated.revision !== state.project?.revision) {
      await openProject(currentId, false);
    }
  } finally {
    syncInFlight = false;
  }
}

function renderProjectList(): void {
  const list = $("launcher-project-list"); list.replaceChildren();
  if (!state.projects.length) {
    const empty = document.createElement("div"); empty.className = "inspector-empty";
    empty.innerHTML = "<strong>No projects yet</strong><p>Create one here or let your connected AI create it.</p>";
    list.append(empty); return;
  }
  for (const project of state.projects) {
    const row = document.createElement("button"); row.className = "launcher-project";
    const thumb = document.createElement("span"); thumb.className = "launcher-project-preview"; thumb.textContent = project.profile === "SHORT_FORM_9_16" ? "▯" : "▭";
    const text = document.createElement("span"); text.className = "launcher-project-copy"; const title = document.createElement("strong"); title.textContent = project.title;
    const meta = document.createElement("small"); meta.textContent = friendlyStatus(project); text.append(title, meta);
    const remove = document.createElement("button"); remove.className = "launcher-project-delete"; remove.textContent = "⌫"; remove.title = "Remove project";
    remove.onclick = (event) => { event.stopPropagation(); void removeProject(project); };
    row.append(thumb, text, remove); row.onclick = () => void openProject(project.project_id); list.append(row);
  }
}

async function removeProject(project: ProjectState): Promise<void> {
  const dialog = $<HTMLDialogElement>("project-removal-dialog");
  $("project-removal-message").textContent = `Remove “${project.title}” from the ATME project screen? Its managed data is retained for recovery and original external files are never deleted.`;
  const accepted = await new Promise<boolean>((resolve) => { const yes = $<HTMLButtonElement>("confirm-project-removal"), no = $<HTMLButtonElement>("cancel-project-removal"); const done=(value:boolean)=>{yes.onclick=null;no.onclick=null;dialog.close();resolve(value)};yes.onclick=()=>done(true);no.onclick=()=>done(false);dialog.showModal(); });
  if (!accepted) return;
  try { await api(`/projects/${project.project_id}/archive`, {method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({expected_revision:project.revision,confirmed:true})}); await loadProjects(); toast("Project removed from the project screen."); }
  catch (error) { toast(error instanceof Error ? error.message : "Project could not be removed."); }
}

async function optionalArtifact<T>(kind: string): Promise<T | null> {
  if (!state.project?.artifacts[kind]) return null;
  try { return (await api<{ document: T }>(`/projects/${state.project.project_id}/artifacts/${kind}`)).document; }
  catch { return null; }
}

async function openProject(id: number, hideDrawer = true): Promise<void> {
  stopPreviewPlayback();
  for (const url of objectUrls) URL.revokeObjectURL(url); objectUrls.clear();
  state.project = await api<ProjectState>(`/projects/${id}`);
  $("project-launcher").classList.add("hidden"); $("studio").classList.remove("hidden");
  await invoke("set_studio_open", { open: true }).catch(() => undefined);
  const [media, assets, script, layout, sourceTimeline] = await Promise.all([
    api<{ media?: MediaItem[] } | MediaItem[]>(`/projects/${id}/media`),
    api<{ assets: AssetItem[] }>(`/projects/${id}/assets`),
    optionalArtifact<ScriptDoc>("script"), optionalArtifact<LayoutDoc>("layout"),
    api<SourceTimeline>(`/projects/${id}/source-timeline`),
  ]);
  state.media = Array.isArray(media) ? media : media.media || [];
  state.assets = assets.assets;
  state.script = script; state.layout = layout; state.sourceTimeline = sourceTimeline; state.editHistory = sourceTimeline.history; state.validation = null; state.playheadMs = 0; state.selected = null;
  state.durationMs = Math.max(1000, sourceTimeline.document.duration_ms || deriveLayoutDuration(layout) || 60_000);
  $("project-name").textContent = state.project.title;
  $("save-state").textContent = `Saved locally · revision ${state.project.revision}`;
  $("add-source").toggleAttribute("disabled", false);
  $("render-project").toggleAttribute("disabled", !(state.project.render_ready || sourceTimeline.document.clips.some(clip=>clip.kind==="video")));
  applyViewerProfile(state.project.profile);
  document.querySelectorAll<HTMLButtonElement>("[data-profile]").forEach((button) => button.classList.toggle("active", button.dataset.profile === state.project?.profile));
  renderProjectList(); renderSources(); renderTimeline(); renderInspector(); updateClock(); updateEditCommands();
  $("viewer-empty").classList.add("hidden");
  await loadSourcePlayback(); await refreshValidation(false); await refreshPreview();
}

function deriveLayoutDuration(layout: LayoutDoc | null): number {
  return Math.max(0, ...(layout?.board_timeline?.activations || []).map((item) => item.end_ms));
}

function applyViewerProfile(profile: ProjectState["profile"]): void {
  const canvas = $("viewer-canvas");
  canvas.dataset.profile = profile;
  $("viewer-stage").classList.remove("hidden");
  document.querySelectorAll<HTMLButtonElement>("[data-profile]").forEach((button) => button.classList.toggle("active", button.dataset.profile === profile));
  sizeViewerCanvas();
}

function sizeViewerCanvas(): void {
  const stage = $("viewer-stage"); const canvas = $("viewer-canvas");
  const availableWidth = Math.max(1, stage.clientWidth); const availableHeight = Math.max(1, stage.clientHeight);
  const ratio = canvas.dataset.profile === "SHORT_FORM_9_16" ? 9 / 16 : 16 / 9;
  if (availableWidth / availableHeight > ratio) {
    canvas.style.height = `${availableHeight}px`; canvas.style.width = `${Math.round(availableHeight * ratio)}px`;
  } else {
    canvas.style.width = `${availableWidth}px`; canvas.style.height = `${Math.round(availableWidth / ratio)}px`;
  }
}

function showProjectBrowser(show = true): void { if (!show) return; stopPreviewPlayback(); $("studio").classList.add("hidden"); $("project-launcher").classList.remove("hidden"); void invoke("set_studio_open", { open: false }).catch(() => undefined); renderProjectList(); }

function showMediaPanel(tab: "sources" | "assets"): void {
  selectMediaTab(tab);
  const panel = $("media-panel"); panel.classList.add("focused");
  window.setTimeout(() => panel.classList.remove("focused"), 700);
}

function renderEmptyStudio(): void {
  stopPreviewPlayback();
  state.project = null; state.media = []; state.assets = []; state.script = null; state.layout = null;
  state.sourceTimeline = null;
  state.editHistory = { can_undo: false, can_redo: false, undo_label: null, redo_label: null };
  $("project-name").textContent = "No project open"; $("save-state").textContent = "Local studio";
  $("add-source").setAttribute("disabled", "");
  $("render-project").setAttribute("disabled", ""); $("viewer-empty").classList.remove("hidden");
  $("preview-image").classList.add("hidden"); $("viewer-message").classList.add("hidden");
  $("viewer-stage").classList.add("hidden"); $("viewer").classList.remove("source-video-active");
  renderSources(); renderTimeline(); renderInspector(); updateEditCommands();
}

function renderSources(): void {
  const list = $("source-list"); list.replaceChildren();
  if (!state.project) return;
  if (mediaTab === "sources") {
    const scriptRevision = state.project.artifacts.script;
    if (scriptRevision) list.append(sourceCard("script", "Production script", `Version ${scriptRevision}`, "≡"));
    for (const media of state.media) {
      list.append(sourceCard(media.media_id, media.name || (media.kind === "audio" ? "Narration audio" : "Source video"),
        `${media.format.toUpperCase()} · ${formatTime(media.duration_ms)} · ${formatBytes(media.bytes)}`, media.kind === "audio" ? "≋" : "▶", media));
    }
  } else {
    for (const asset of state.assets) list.append(assetCard(asset));
  }
  if (!list.children.length) {
    const empty = document.createElement("div"); empty.className = "inspector-empty";
    empty.innerHTML = mediaTab === "sources" ? "<strong>No sources</strong><p>Add a recording, or let your connected AI populate the project.</p>" : "<strong>No assets</strong><p>Add images, reference documents, supporting audio or source footage.</p>"; list.append(empty);
  }
}

function assetCard(asset: AssetItem): HTMLElement {
  const icon = asset.media_type.startsWith("image/") ? "◇" : asset.media_type.startsWith("audio/") ? "≋" : asset.media_type.startsWith("video/") ? "▶" : "▤";
  const card = sourceCard(asset.asset_id, asset.name, `${asset.format.toUpperCase()} · ${formatBytes(asset.bytes)}`, icon);
  card.onclick = () => { state.selected = { kind: "asset", id: asset.asset_id, label: asset.name, startMs: 0, endMs: state.durationMs }; selectVisual(card); renderInspector(); };
  return card;
}

function sourceCard(id: string, titleText: string, metaText: string, iconText: string, media?: MediaItem): HTMLElement {
  const card = document.createElement("div"); card.className = "source-card"; card.dataset.sourceId = id; card.tabIndex = 0;
  const icon = document.createElement("span"); icon.className = "source-icon"; icon.textContent = iconText;
  const text = document.createElement("span"); const title = document.createElement("strong"); title.textContent = titleText;
  const meta = document.createElement("span"); meta.textContent = metaText; text.append(title, meta); card.append(icon, text);
  if (media) {
    card.draggable = true; card.addEventListener("dragstart", (event) => event.dataTransfer?.setData("application/x-atme-media", media.media_id));
    const add = document.createElement("button"); add.className = "source-add"; add.textContent = "+"; add.title = "Add to timeline at playhead"; add.onclick = (event) => { event.stopPropagation(); void insertMedia(media.media_id, state.playheadMs); };
    const remove = document.createElement("button"); remove.className = "source-remove"; remove.textContent = "⋯"; remove.title = "Remove from project"; remove.onclick = (event) => { event.stopPropagation(); void removeSource(media); }; card.append(add, remove);
    card.ondblclick = () => void insertMedia(media.media_id, state.playheadMs);
  }
  card.onclick = () => { state.selected = { kind: media?.kind || "script", id, label: titleText, startMs: 0, endMs: media?.duration_ms || state.durationMs }; selectVisual(card); renderInspector(); if(media) void previewMediaSource(media); };
  return card;
}

async function previewMediaSource(media: MediaItem): Promise<void> {
  if (!state.project) return; stopPreviewPlayback(); viewerUsesCleanedTimeline=false;
  viewerClip={clip_id:"media-preview",media_id:media.media_id,kind:media.kind,stream:media.kind==="video"?"linked_av":"audio",source_start_ms:0,source_end_ms:media.duration_ms,timeline_start_ms:0,link_group_id:"",crossfade_ms:0};
  try { const info=await sidecar(); const ticket=await api<{path:string}>(`/projects/${state.project.project_id}/playback-ticket`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({expected_revision:state.project.revision,media_id:media.media_id,cleaned:false})}); const video=$<HTMLVideoElement>("source-video"); video.src=`http://127.0.0.1:${info.port}${ticket.path}`; video.classList.toggle("audio-preview",media.kind==="audio"); video.classList.remove("hidden"); $("viewer").classList.add("source-video-active"); const message=$("viewer-message"); message.textContent=`Audio preview · ${media.name||"Narration"}`; message.classList.toggle("hidden",media.kind!=="audio"); video.onloadedmetadata=()=>{state.playheadMs=0;updatePlayhead();}; }
  catch(error){toast(error instanceof Error?error.message:"Source preview unavailable.");}
}

async function previewTimelineClip(clipId:string):Promise<void>{const clip=state.sourceTimeline?.document.clips.find(value=>value.clip_id===clipId),media=clip&&state.media.find(value=>value.media_id===clip.media_id);if(!clip||!media)return;await previewMediaSource(media);viewerClip=clip;state.playheadMs=Math.max(clip.timeline_start_ms,Math.min(state.playheadMs,clip.timeline_start_ms+clip.source_end_ms-clip.source_start_ms));const video=$<HTMLVideoElement>("source-video");video.currentTime=(clip.source_start_ms+state.playheadMs-clip.timeline_start_ms)/1000;updatePlayhead();}

async function insertMedia(mediaId: string, atMs: number): Promise<void> {
  await applySourceEdit("insert", { media_id: mediaId, at_ms: Math.max(0, Math.round(atMs)) });
}

async function removeSource(media: MediaItem): Promise<void> {
  if (!state.project) return;
  try {
    const impact = await api<{ timeline_clips: number; artifacts: Array<{ kind: string; revision: number }>; render_runs: number; timing_runs: number }>(`/projects/${state.project.project_id}/media/${media.media_id}/removal-impact`);
    if (!await showSourceRemovalDialog(media, impact)) return;
    await api(`/projects/${state.project.project_id}/media/${media.media_id}/remove`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ expected_revision: state.project.revision, confirmed: true }) });
    await openProject(state.project.project_id, false); toast("Source removed. Your original file remains on your computer.");
  } catch (error) {
    const message = error instanceof Error && error.message.includes("Project changed")
      ? "The project changed while the dialog was open. It has been refreshed; please remove the source again."
      : error instanceof Error ? error.message : "ATME could not remove this source.";
    if (state.project) await openProject(state.project.project_id, false).catch(() => undefined);
    toast(message);
  }
}

function showSourceRemovalDialog(media: MediaItem, impact: { timeline_clips: number; artifacts: Array<{ kind: string }>; render_runs: number; timing_runs: number }): Promise<boolean> {
  const dialog = $<HTMLDialogElement>("source-removal-dialog");
  const type = media.kind === "video" ? "video" : "audio";
  $("source-removal-title").textContent = `Remove ${type} source?`;
  const consequences: string[] = [];
  if (impact.timeline_clips) consequences.push(`${impact.timeline_clips} timeline clip${impact.timeline_clips === 1 ? "" : "s"} will be removed`);
  if (impact.artifacts.length) consequences.push("the current storyboard and layout will be marked for review");
  if (impact.timing_runs) consequences.push("prepared timing will need to be refreshed");
  if (impact.render_runs) consequences.push("past renders will remain in render history");
  $("source-removal-message").textContent = consequences.length
    ? `This source is in use. ${consequences.join("; ")}.`
    : "This source is not used by the current timeline or production plan.";
  return new Promise((resolve) => {
    const confirm = $<HTMLButtonElement>("confirm-source-removal"); const cancel = $<HTMLButtonElement>("cancel-source-removal");
    const finish = (accepted: boolean) => { confirm.onclick = null; cancel.onclick = null; dialog.oncancel = null; dialog.close(); resolve(accepted); };
    confirm.onclick = () => finish(true); cancel.onclick = () => finish(false);
    dialog.oncancel = (event) => { event.preventDefault(); finish(false); };
    dialog.showModal();
  });
}

function selectVisual(node: HTMLElement): void {
  document.querySelectorAll(".selected").forEach((item) => item.classList.remove("selected")); node.classList.add("selected");
  $("range-selection").classList.add("hidden");
  updateEditCommands();
}

function renderTimeline(): void {
  // Object URLs also back the active viewer. Keep them alive for the lifetime of
  // the open project; openProject() revokes the complete project-scoped set.
  document.querySelectorAll(".track.generated-track").forEach(node=>node.remove());
  const clips=state.sourceTimeline?.document.clips||[], maxTrack=Math.max(0,...clips.map(c=>c.track_index||0));
  for(const kind of ["video","audio"]){const base=document.querySelector<HTMLElement>(`.track[data-track='${kind}'][data-track-index='0']`)!;for(let i=1;i<=maxTrack;i++){const row=base.cloneNode(true) as HTMLElement;row.classList.add("generated-track");row.dataset.trackIndex=String(i);row.querySelector(".track-label")!.innerHTML=`<span>${kind==="video"?"▣":"≋"}</span>${kind==="video"?"Video":"Audio"} ${i+1}`;base.parentElement!.insertBefore(row,$("playhead"));}}
  const parent=$("timeline-tracks"), marker=$("playhead"); for(let i=0;i<=maxTrack;i++){for(const kind of ["video","audio"]){const row=document.querySelector<HTMLElement>(`.track[data-track='${kind}'][data-track-index='${i}']`);if(row)parent.insertBefore(row,marker);}}
  document.querySelectorAll<HTMLElement>(".track-lane").forEach((lane) => lane.replaceChildren());
  if (!state.project) return;
  const width = timelineWidth();
  document.querySelectorAll<HTMLElement>(".track").forEach((track) => track.style.width = `${145 + width}px`);
  document.querySelectorAll<HTMLElement>(".track-lane").forEach((lane) => lane.style.width = `${width}px`);
  renderRuler(width); updateRulerScroll();
  const add = (track: string, start: number, end: number, label: string, kind: string, id: string, provisional = false, trackIndex=0) => {
    const lane = document.querySelector<HTMLElement>(`.track[data-track='${track}']${track==="video"||track==="audio"?`[data-track-index='${trackIndex}']`:""} .track-lane`); if (!lane) return;
    const clip = document.createElement("button"); clip.className = `clip ${kind}`; clip.textContent = label;
    if (kind === "video" || kind.startsWith("audio")) clip.dataset.sourceClip = id;
    clip.classList.toggle("provisional", provisional);
    clip.style.left = `${Math.max(0, start / state.durationMs * width)}px`; clip.style.width = `${Math.max(16, (end - start) / state.durationMs * width)}px`;
    clip.classList.toggle("selected",selectedClipIds.has(id));
    clip.onclick = (event) => { event.stopPropagation(); const clickedAt = timelineTime(event.clientX); if (activeTool === "blade" && clip.dataset.sourceClip) { state.playheadMs = clickedAt; void applySourceEdit("split", {clip_id:id,at_ms:state.playheadMs}); return; } if(clip.dataset.sourceClip&&(event.ctrlKey||event.metaKey)){selectedClipIds.has(id)?selectedClipIds.delete(id):selectedClipIds.add(id);renderTimeline();return;}selectedClipIds.clear();if(clip.dataset.sourceClip)selectedClipIds.add(id); state.selected = { kind, id, label, startMs: start, endMs: end }; state.playheadMs = Math.max(start, Math.min(end, clickedAt)); selectVisual(clip); updatePlayhead(); renderInspector(); if(clip.dataset.sourceClip) void previewTimelineClip(id); else void refreshPreview(); };
    if (clip.dataset.sourceClip) {
      clip.oncontextmenu = (event) => { event.preventDefault(); event.stopPropagation(); state.selected={kind,id,label,startMs:start,endMs:end}; selectVisual(clip); showTimelineMenu(event.clientX,event.clientY); };
      let originX=0, originStart=start, moved=false;
      clip.onpointerdown = (event) => { if (activeTool !== "select" || event.button !== 0) return; event.stopPropagation(); originX=event.clientX; originStart=start; moved=false; clip.setPointerCapture(event.pointerId); clip.classList.add("dragging"); };
      clip.onpointermove = (event) => { if (!clip.hasPointerCapture(event.pointerId)) return; const delta=(event.clientX-originX)/width*state.durationMs; let target=Math.max(0,Math.round(originStart+delta)); if(snapping) target=snapTime(target,id); clip.style.left=`${target/state.durationMs*width}px`; moved=Math.abs(delta)>15; clip.dataset.moveTarget=String(target); };
      clip.onpointerup = (event) => {
        if (!clip.hasPointerCapture(event.pointerId)) return;
        clip.releasePointerCapture(event.pointerId); clip.classList.remove("dragging");
        if (!moved) return;
        const target = document.elementFromPoint(event.clientX, event.clientY)?.closest<HTMLElement>(`.track[data-track='${track}']`);
        const targetIndex = Number(target?.dataset.trackIndex ?? trackIndex);
        void applySourceEdit("move_position", { clip_id: id, clip_ids:Array.from(selectedClipIds), timeline_start_ms: Number(clip.dataset.moveTarget), track_index: targetIndex });
      };
    }
    lane.append(clip);
  };
  for (const item of state.sourceTimeline?.document.clips || []) {
    const end = item.timeline_start_ms + item.source_end_ms - item.source_start_ms;
    const media=state.media.find(value=>value.media_id===item.media_id); add(item.kind === "video" ? "video" : "audio", item.timeline_start_ms, end, media?.name || (item.kind === "video" ? "Source video" : "Narration"), item.kind, item.clip_id, false, item.track_index||0);
    // Linked source audio stays inside its video clip until explicit detachment.
  }
  for (const activation of state.layout?.board_timeline?.activations || []) add("illustrations", activation.start_ms, activation.end_ms, activation.board_id, "illustration", activation.board_id);
  const scenes = state.script?.scenes || [];
  const totalWeight = scenes.reduce((sum, scene) => sum + Math.max(1, scene.est_seconds || scene.spoken_text.split(/\s+/).length), 0);
  let cursor = 0;
  for (const scene of scenes) {
    const weight = Math.max(1, scene.est_seconds || scene.spoken_text.split(/\s+/).length);
    const end = cursor + Math.round(state.durationMs * weight / Math.max(1, totalWeight));
    add("captions", cursor, end, scene.spoken_text, "caption", String(scene.scene_id), state.media.length === 0); cursor = end;
  }
  updatePlayhead(); updateEditCommands();
  void decorateSourceClips();
}

function snapTime(value:number, movingId:string):number { const threshold=Math.max(30,800/state.zoom); const points=[0,state.playheadMs]; for(const c of state.sourceTimeline?.document.clips||[]){if(c.clip_id===movingId)continue;points.push(c.timeline_start_ms,c.timeline_start_ms+c.source_end_ms-c.source_start_ms)} const nearest=points.reduce((a,b)=>Math.abs(b-value)<Math.abs(a-value)?b:a,value);return Math.abs(nearest-value)<=threshold?nearest:value; }

function showTimelineMenu(x:number,y:number):void { const menu=$("timeline-context-menu"); const clip=selectedSourceClip(); const detach=menu.querySelector<HTMLButtonElement>("[data-action='detach-audio']")!; detach.disabled=!clip||clip.kind!=="video"||clip.stream==="video"; menu.style.left=`${x}px`;menu.style.top=`${y}px`;menu.classList.remove("hidden"); }

function timelineWidth(): number {
  return Math.max(120, state.durationMs / 1000 * 80 * state.zoom);
}

function renderRuler(width: number): void {
  const ruler = $("timeline-ruler"); ruler.replaceChildren(); ruler.style.width = `${width}px`;
  const secondsVisible = state.durationMs / 1000; const targetTicks = Math.max(2, Math.floor(width / 100));
  const raw = secondsVisible / targetTicks; const steps = [1, 2, 5, 10, 15, 30, 60, 120, 300, 600];
  const step = steps.find((value) => value >= raw) || 600;
  for (let seconds = 0; seconds <= secondsVisible; seconds += step) { const mark = document.createElement("span"); mark.style.left = `${seconds * 1000 / state.durationMs * width}px`; mark.textContent = formatTime(seconds * 1000); ruler.append(mark); }
}

function updateRulerScroll(): void { $("timeline-ruler").style.transform = `translateX(${-$("timeline-tracks").scrollLeft}px)`; }

async function decorateSourceClips(): Promise<void> {
  if (!state.project || !state.sourceTimeline) return;
  for (const item of state.sourceTimeline.document.clips) {
    const media = state.media.find((value) => value.media_id === item.media_id); if (!media) continue;
    const nodes = Array.from(document.querySelectorAll<HTMLElement>(`.clip[data-source-clip='${item.clip_id}']`));
    const resolution = state.zoom > 1.5 ? 10 : state.zoom > .7 ? 40 : 160;
    const key = `${item.media_id}:${resolution}`;
    let evidence = waveformCache.get(key);
    if (!evidence) { try { evidence = await api<Waveform>(`/projects/${state.project.project_id}/media/${item.media_id}/waveform?resolution_ms=${resolution}`); waveformCache.set(key, evidence); } catch { continue; } }
    for (const node of nodes.filter((value) => value.classList.contains("audio") || (item.kind==="video" && item.stream!=="video"))) drawWaveform(node, evidence, item);
    if (media.kind === "video") await drawThumbnails(item);
    if (state.showSilences) drawSilenceMarkers(evidence, item);
  }
}

function drawWaveform(node: HTMLElement, waveform: Waveform, clip: TimelineClip): void {
  const canvas = document.createElement("canvas"); canvas.className = "waveform"; canvas.width = Math.max(40, Math.round(node.clientWidth * devicePixelRatio)); canvas.height = Math.max(28, Math.round(node.clientHeight * devicePixelRatio));
  const context = canvas.getContext("2d"); if (!context) return; context.strokeStyle = "#74e0b8"; context.lineWidth = 1;
  const first = Math.floor(clip.source_start_ms / waveform.resolution_ms); const last = Math.min(waveform.peaks.length, Math.ceil(clip.source_end_ms / waveform.resolution_ms));
  const middle=canvas.height/2, amplitude=Math.max(2,middle-3), span=Math.max(1,last-first);
  for (let x = 0; x < canvas.width; x++) {
    const from=first+Math.floor(x/canvas.width*span), to=Math.max(from+1,first+Math.ceil((x+1)/canvas.width*span));
    let lo=0,hi=0; for(let i=from;i<Math.min(last,to);i++){const peak=waveform.peaks[i];if(peak){lo=Math.min(lo,peak[0]);hi=Math.max(hi,peak[1]);}}
    context.beginPath(); context.moveTo(x,middle-hi*amplitude); context.lineTo(x,middle-lo*amplitude); context.stroke();
  }
  node.prepend(canvas);
}

async function drawThumbnails(clip: TimelineClip): Promise<void> {
  if (!state.project) return; const node = document.querySelector<HTMLElement>(`.clip.video[data-source-clip='${clip.clip_id}']`); if (!node) return;
  const count = Math.max(1, Math.min(20, Math.ceil(node.clientWidth / 110)));
  const strip = document.createElement("span"); strip.className = "thumbnail-strip"; node.prepend(strip);
  for (let index = 0; index < count; index++) { const at = Math.round(clip.source_start_ms + (index + .5) / count * (clip.source_end_ms - clip.source_start_ms)); try { const image = document.createElement("img"); image.src = await apiBlobUrl(`/projects/${state.project.project_id}/media/${clip.media_id}/thumbnail?at_ms=${at}&width=160`); strip.append(image); } catch { break; } }
}

function drawSilenceMarkers(waveform: Waveform, clip: TimelineClip): void {
  const lane = document.querySelector<HTMLElement>(`.track[data-track='audio'] .track-lane`); if (!lane) return; const width = timelineWidth();
  for (const silence of waveform.silences) { const start = Math.max(silence.start_ms, clip.source_start_ms); const end = Math.min(silence.end_ms, clip.source_end_ms); if (end <= start) continue; const marker = document.createElement("div"); marker.className = "silence-marker"; const timelineStart = clip.timeline_start_ms + start - clip.source_start_ms; marker.style.left = `${timelineStart / state.durationMs * width}px`; marker.style.width = `${Math.max(2, (end - start) / state.durationMs * width)}px`; marker.title = `Likely silence ${((end - start) / 1000).toFixed(1)}s`; lane.append(marker); }
}

function updatePlayhead(): void {
  $("playhead").style.left = `${145 + state.playheadMs / state.durationMs * timelineWidth()}px`; updateClock();
  const video = $<HTMLVideoElement>("source-video");
  if (!video.classList.contains("hidden")) {
    const sourceMs = viewerUsesCleanedTimeline ? state.playheadMs : viewerClip && state.playheadMs >= viewerClip.timeline_start_ms && state.playheadMs <= viewerClip.timeline_start_ms + viewerClip.source_end_ms - viewerClip.source_start_ms ? viewerClip.source_start_ms + state.playheadMs - viewerClip.timeline_start_ms : null;
    if (sourceMs !== null && Math.abs(video.currentTime * 1000 - sourceMs) > 250) video.currentTime = sourceMs / 1000;
  }
}
function updateClock(): void { $("viewer-time").textContent = `${formatTime(state.playheadMs)} / ${formatTime(state.durationMs)}`; }

async function refreshPreview(): Promise<void> {
  if (!state.project) return;
  const image = $<HTMLImageElement>("preview-image"); const message = $("viewer-message");
  $<HTMLVideoElement>("render-video").classList.add("hidden");
  const sourceVideo = $<HTMLVideoElement>("source-video");
  if (!sourceVideo.classList.contains("hidden")) {
    $("viewer").classList.add("source-video-active");
    message.classList.add("hidden");
    if (!state.project.render_ready) { image.classList.add("hidden"); return; }
  }
  if (!state.project.render_ready) {
    image.classList.add("hidden");
    if ($<HTMLVideoElement>("source-video").classList.contains("hidden")) { message.textContent = viewerStatusMessage(); message.classList.remove("hidden"); }
    else message.classList.add("hidden");
    return;
  }
  try {
    const info = await sidecar(); const at = Math.min(state.playheadMs, state.durationMs - 1);
    const response = await fetch(`http://127.0.0.1:${info.port}/projects/${state.project.project_id}/preview?expected_revision=${state.project.revision}&at_ms=${at}`, { headers: { Authorization: `Bearer ${info.token}` } });
    if (!response.ok) throw new Error("Preview is not available for this revision.");
    if (state.previewUrl) URL.revokeObjectURL(state.previewUrl); state.previewUrl = URL.createObjectURL(await response.blob());
    image.src = state.previewUrl; image.classList.remove("hidden"); message.classList.add("hidden");
  } catch (error) { image.classList.add("hidden"); message.textContent = error instanceof Error ? error.message : "Preview unavailable."; message.classList.remove("hidden"); }
}

async function loadSourcePlayback(): Promise<void> {
  const video = $<HTMLVideoElement>("source-video"); video.pause(); video.removeAttribute("src"); video.load(); video.classList.add("hidden");
  $("viewer").classList.remove("source-video-active");
  $<HTMLVideoElement>("render-video").classList.add("hidden");
  viewerClip = null; viewerUsesCleanedTimeline = false;
  if (!state.project || !(state.sourceTimeline?.document.clips.length)) return;
  const videoClips = state.sourceTimeline.document.clips.filter((clip) => clip.kind === "video"); if (!videoClips.length) return;
  const allVideo = videoClips.length === state.sourceTimeline.document.clips.length;
  viewerClip = videoClips[0]; viewerUsesCleanedTimeline = allVideo;
  try {
    const info = await sidecar(); const ticket = await api<{ path: string }>(`/projects/${state.project.project_id}/playback-ticket`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ expected_revision: state.project.revision, media_id: allVideo ? null : viewerClip.media_id, cleaned: allVideo }) });
    video.src = `http://127.0.0.1:${info.port}${ticket.path}`; video.classList.remove("hidden"); $("viewer").classList.add("source-video-active");
    $("preview-image").classList.add("hidden"); $("viewer-message").classList.add("hidden");
    video.onloadedmetadata = () => { if (viewerUsesCleanedTimeline && Number.isFinite(video.duration) && video.duration > 0) state.durationMs = Math.max(1000, Math.round(video.duration * 1000)); else if (viewerClip) video.currentTime = viewerClip.source_start_ms / 1000; renderTimeline(); updateClock(); };
    video.onerror = () => { $("viewer").classList.remove("source-video-active"); video.classList.add("hidden"); const message = $("viewer-message"); message.textContent = "This video could not be played. Remove it and import the original file again."; message.classList.remove("hidden"); };
    video.ontimeupdate = () => {
      if (video.paused) return;
      state.playheadMs = viewerUsesCleanedTimeline
        ? Math.round(video.currentTime * 1000)
        : viewerClip ? viewerClip.timeline_start_ms + Math.round(video.currentTime * 1000) - viewerClip.source_start_ms : 0;
      if (viewerClip && !viewerUsesCleanedTimeline && video.currentTime * 1000 >= viewerClip.source_end_ms) video.pause();
      updatePlayheadPositionOnly();
      if (state.project?.render_ready && performance.now() - lastOverlayRefresh > 450) { lastOverlayRefresh = performance.now(); void refreshPreview(); }
    };
    video.onplay = () => { $("play-preview").textContent = "Ⅱ"; };
    video.onpause = () => { $("play-preview").textContent = "▶"; };
  } catch (error) { toast(error instanceof Error ? error.message : "Source preview unavailable."); }
}

function updatePlayheadPositionOnly(): void { $("playhead").style.left = `${145 + state.playheadMs / state.durationMs * timelineWidth()}px`; updateClock(); }

function togglePreviewPlayback(): void {
  const button = $("play-preview");
  const sourceVideo = $<HTMLVideoElement>("source-video");
  if (!sourceVideo.classList.contains("hidden")) {
    if (sourceVideo.paused) {
      const end = viewerUsesCleanedTimeline ? state.durationMs : viewerClip?.source_end_ms || state.durationMs;
      if (sourceVideo.currentTime * 1000 >= end - 50) sourceVideo.currentTime = viewerUsesCleanedTimeline ? 0 : (viewerClip?.source_start_ms || 0) / 1000;
      void sourceVideo.play().catch(() => toast("Playback could not start. Try importing the original video again."));
    } else sourceVideo.pause();
    return;
  }
  if (previewTimer !== null) { stopPreviewPlayback(); return; }
  // Playback is an editor operation. Creative-plan/export validation must never
  // disable transport controls or hide media after a timeline edit.
  if (!state.layout) {
    toast(state.media.length
      ? "The current media is available in the timeline. Select a video clip to preview it."
      : "Add media to the timeline to begin playback.");
    return;
  }
  button.textContent = "Ⅱ";
  previewTimer = window.setInterval(() => {
    state.playheadMs += 500;
    if (state.playheadMs >= state.durationMs) { state.playheadMs = 0; togglePreviewPlayback(); }
    updatePlayhead(); void refreshPreview();
  }, 500);
}

function stopPreviewPlayback(): void {
  $<HTMLVideoElement>("source-video").pause();
  if (previewTimer !== null) window.clearInterval(previewTimer);
  previewTimer = null;
  $("play-preview").textContent = "▶";
}

function viewerStatusMessage(): string {
  if (!state.media.length) return "Add narration or source video. Your connected AI can then build the production plan.";
  if (!state.script) return "The recording is ready. Waiting for the connected AI to add semantic scene structure.";
  if (!state.layout) return "The script is available. Waiting for storyboard and layout planning.";
  return "The edit is available. Creative overlays will appear when their plan is ready.";
}

async function refreshValidation(showDialog = true): Promise<void> {
  if (!state.project) return;
  state.validation = await api<Validation>(`/projects/${state.project.project_id}/validate`).catch(() => null as unknown as Validation);
  const pill = $("validation-pill"); const dot = pill.querySelector(".status-dot") as HTMLElement; const label = pill.lastElementChild as HTMLElement;
  dot.className = `status-dot ${state.validation?.ready ? "good" : state.validation ? "warn" : "bad"}`;
  label.textContent = state.validation?.ready ? "Ready to export" : state.validation ? `${state.validation.issues.length} export items` : "Export check failed";
  if (state.validation?.ready) { state.project.render_ready = true; $("render-project").toggleAttribute("disabled", false); }
  if (showDialog) showValidationDialog();
}

function renderInspector(): void {
  const root = $("inspector-content"); root.replaceChildren();
  document.querySelectorAll<HTMLButtonElement>("[data-inspector]").forEach((button) => button.classList.toggle("active", button.dataset.inspector === inspectorTab));
  $("selection-label").textContent = state.selected ? `${state.selected.label} · ${formatTime(state.selected.startMs)}–${formatTime(state.selected.endMs)}` : "No selection";
  if (!state.selected) { root.innerHTML = "<div class='inspector-empty'><strong>Nothing selected</strong><p>Select a scene, clip or timeline range.</p></div>"; return; }
  if (inspectorTab === "style") { appendStyleInspection(root); return; }
  if (inspectorTab === "audio") { appendAudioInspection(root); return; }
  if (inspectorTab === "ai") { appendAiRevision(root); return; }
  const section = document.createElement("section"); section.className = "inspector-section";
  const heading = document.createElement("h3"); heading.textContent = state.selected.kind;
  const title = document.createElement("strong"); title.textContent = state.selected.label;
  const time = document.createElement("div"); time.className = "inspector-row"; time.innerHTML = `<span>Timing</span><strong>${formatTime(state.selected.startMs)} – ${formatTime(state.selected.endMs)}</strong>`;
  section.append(heading, title, time); root.append(section);
  if (state.selected.kind === "caption" && state.script) appendCaptionEditor(root);
  if (state.selected.kind === "illustration" && state.layout) appendTimingOverride(root);
  if ((state.selected.kind === "video" || state.selected.kind.startsWith("audio")) && state.sourceTimeline) appendSourceClipEditor(root);
  updateEditCommands();
}

function appendCaptionEditor(root: HTMLElement): void {
  const scene = state.script?.scenes.find((item) => String(item.scene_id) === state.selected?.id);
  if (!scene) return;
  const section = document.createElement("section"); section.className = "inspector-section";
  const heading = document.createElement("h3"); heading.textContent = "Edit scene";
  const text = document.createElement("textarea"); text.className = "revision-box"; text.value = scene.spoken_text;
  text.setAttribute("aria-label", "Scene narration text");
  const save = document.createElement("button"); save.className = "small-primary"; save.textContent = "Save edit";
  save.onclick = () => {
    const value = text.value.trim();
    if (!value || value === scene.spoken_text || !state.script) return;
    const document = structuredClone(state.script);
    const changed = document.scenes.find((item) => item.scene_id === scene.scene_id);
    if (changed) changed.spoken_text = value;
    void applyEditorEdit("edit", "script", document);
  };
  section.append(heading, text, save); root.append(section);
}

function appendSourceClipEditor(root: HTMLElement): void {
  const clip = selectedSourceClip(); if (!clip || !state.sourceTimeline) return;
  const section = document.createElement("section"); section.className = "inspector-section";
  const heading = document.createElement("h3"); heading.textContent = "Non-destructive source edit";
  const startLabel = document.createElement("label"); startLabel.textContent = "Timeline in (ms)";
  const start = document.createElement("input"); start.type = "number"; start.min = String(clip.timeline_start_ms); start.max = String(clip.timeline_start_ms + clip.source_end_ms - clip.source_start_ms - 40); start.value = String(clip.timeline_start_ms);
  const endLabel = document.createElement("label"); endLabel.textContent = "Timeline out (ms)";
  const end = document.createElement("input"); end.type = "number"; end.min = String(clip.timeline_start_ms + 40); end.max = String(clip.timeline_start_ms + clip.source_end_ms - clip.source_start_ms); end.value = String(clip.timeline_start_ms + clip.source_end_ms - clip.source_start_ms);
  const trim = document.createElement("button"); trim.className = "small-primary"; trim.textContent = "Apply trim"; trim.onclick = () => void applySourceEdit("trim", { clip_id: clip.clip_id, start_ms: Number(start.value), end_ms: Number(end.value) });
  const crossfadeLabel = document.createElement("label"); crossfadeLabel.textContent = "Cut crossfade";
  const crossfade = document.createElement("select"); for (const value of [0, 50, 100, 250, 500]) { const option = document.createElement("option"); option.value = String(value); option.textContent = value ? `${value} ms` : "None"; option.selected = clip.crossfade_ms === value; crossfade.append(option); } crossfade.onchange = () => void applySourceEdit("crossfade", { clip_id: clip.clip_id, crossfade_ms: Number(crossfade.value) });
  const moves = document.createElement("div"); moves.className = "mini-actions"; const ordered = [...state.sourceTimeline.document.clips].sort((a, b) => a.timeline_start_ms - b.timeline_start_ms); const index = ordered.findIndex((item) => item.clip_id === clip.clip_id);
  const left = document.createElement("button"); left.className = "command-button"; left.textContent = "Move earlier"; left.disabled = index <= 0; left.onclick = () => void applySourceEdit("move", { clip_id: clip.clip_id, to_index: index - 1 });
  const right = document.createElement("button"); right.className = "command-button"; right.textContent = "Move later"; right.disabled = index < 0 || index >= ordered.length - 1; right.onclick = () => void applySourceEdit("move", { clip_id: clip.clip_id, to_index: index + 1 }); moves.append(left, right);
  const note = document.createElement("p"); note.textContent = clip.kind === "video" ? "Picture and source audio are linked; every edit keeps them synchronized." : "The original recording remains unchanged.";
  section.append(heading, startLabel, start, endLabel, end, trim, crossfadeLabel, crossfade, moves, note); root.append(section);
}

function updateEditCommands(): void {
  const sourceClip = Boolean(selectedSourceClip()); const range = state.selected?.kind === "timeline";
  $<HTMLButtonElement>("undo-edit").disabled = !state.project || !state.editHistory.can_undo;
  $<HTMLButtonElement>("redo-edit").disabled = !state.project || !state.editHistory.can_redo;
  $<HTMLButtonElement>("cut-edit").disabled = !sourceClip;
  $<HTMLButtonElement>("delete-edit").disabled = !range;
  $<HTMLButtonElement>("ripple-delete").disabled = !range;
  $("undo-edit").title = state.editHistory.undo_label ? `Undo ${state.editHistory.undo_label} (Ctrl+Z)` : "Nothing to undo";
  $("redo-edit").title = state.editHistory.redo_label ? `Redo ${state.editHistory.redo_label} (Ctrl+Y)` : "Nothing to redo";
}

async function applyEditorEdit(operation: string, artifactKind: "script" | "layout", document: object): Promise<void> {
  if (!state.project) return;
  const projectId = state.project.project_id;
  try {
    await api(`/projects/${projectId}/edits`, { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ operation, artifact_kind: artifactKind, document, expected_revision: state.project.revision }) });
    await openProject(projectId, false);
    toast(`${operation[0].toUpperCase()}${operation.slice(1)} saved. Script approval must be reviewed again.`);
  } catch (error) { toast(error instanceof Error ? error.message : "Edit failed."); }
}

async function historyAction(action: "undo" | "redo"): Promise<void> {
  if (!state.project) return;
  const projectId = state.project.project_id;
  try {
    await api(`/projects/${projectId}/source-timeline/${action}`, { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ expected_revision: state.project.revision }) });
    await openProject(projectId, false); toast(`${action === "undo" ? "Undo" : "Redo"} complete.`);
  } catch (error) { toast(error instanceof Error ? error.message : `${action} failed.`); }
}

function cutSelected(): void {
  const clip = selectedSourceClip(); if (!clip) return;
  void applySourceEdit("split", { clip_id: clip.clip_id, at_ms: state.playheadMs });
}

function deleteSelected(ripple = false): void { if (state.selected?.kind === "timeline") void applySourceEdit(ripple ? "ripple_delete" : "delete_range", { start_ms: state.selected.startMs, end_ms: state.selected.endMs }); }

function selectedSourceClip(): TimelineClip | null { return state.sourceTimeline?.document.clips.find((clip) => clip.clip_id === state.selected?.id) || null; }

async function applySourceEdit(operation: string, args: object): Promise<void> {
  if (!state.project || !state.sourceTimeline) return; const projectId = state.project.project_id;
  try { await api(`/projects/${projectId}/source-timeline/commands`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ operation, arguments: args, expected_revision: state.project.revision, expected_timeline_revision: state.sourceTimeline.timeline_revision }) }); await openProject(projectId, false); toast(`${operation.replaceAll("_", " ")} saved non-destructively.`); }
  catch (error) { toast(error instanceof Error ? error.message : "Timeline edit failed."); }
}

function appendStyleInspection(root: HTMLElement): void {
  if (!state.selected) return;
  const section = document.createElement("section"); section.className = "inspector-section";
  const heading = document.createElement("h3"); heading.textContent = "Rendered style";
  const elements = (state.layout?.elements || []).filter((item) => item.id === state.selected?.id || item.board_id === state.selected?.id);
  const description = document.createElement("p");
  description.textContent = elements.length
    ? `${elements.length} layout element${elements.length === 1 ? "" : "s"} use the saved project style and Caleb-derived draw behavior.`
    : "This selection has no independent style properties in the current layout.";
  section.append(heading, description);
  for (const element of elements.slice(0, 8)) {
    const row = document.createElement("div"); row.className = "inspector-row";
    const name = document.createElement("span"); name.textContent = element.kind || element.id;
    const value = document.createElement("strong"); value.textContent = element.layer === undefined ? `Scene ${element.scene_id}` : `Layer ${element.layer}`;
    row.append(name, value); section.append(row);
  }
  root.append(section);
}

function appendAudioInspection(root: HTMLElement): void {
  if (!state.selected) return;
  const section = document.createElement("section"); section.className = "inspector-section";
  const heading = document.createElement("h3"); heading.textContent = "Source audio"; section.append(heading);
  const sourceClip = state.sourceTimeline?.document.clips.find((item) => item.clip_id === state.selected?.id);
  const media = state.media.find((item) => item.media_id === (sourceClip?.media_id || state.selected?.id));
  if (!media) { const message = document.createElement("p"); message.textContent = "Select a narration or source-video clip to inspect its technical audio metadata."; section.append(message); root.append(section); return; }
  const values: Array<[string, string]> = [["Format", media.format.toUpperCase()], ["Duration", formatTime(media.duration_ms)]];
  if (media.sample_rate) values.push(["Sample rate", `${media.sample_rate.toLocaleString()} Hz`]);
  if (media.channels) values.push(["Channels", String(media.channels)]);
  for (const [label, value] of values) { const row = document.createElement("div"); row.className = "inspector-row"; const left = document.createElement("span"); left.textContent = label; const right = document.createElement("strong"); right.textContent = value; row.append(left, right); section.append(row); }
  root.append(section);
}

function appendAiRevision(root: HTMLElement): void {
  const ai = document.createElement("section"); ai.className = "inspector-section"; ai.innerHTML = "<h3>AI revision</h3>";
  const note = document.createElement("textarea"); note.className = "revision-box"; note.maxLength = 500; note.placeholder = "Describe a focused change to this selection…";
  const button = document.createElement("button"); button.className = "add-source"; button.textContent = "Send bounded revision";
  button.onclick = () => void sendRevisionRequest(note, button);
  ai.append(note, button); root.append(ai); void appendRevisionState(root);
}

async function sendRevisionRequest(note: HTMLTextAreaElement, button: HTMLButtonElement): Promise<void> {
  if (!state.project || !state.selected || !note.value.trim()) return;
  button.disabled = true;
  try {
    await api(`/projects/${state.project.project_id}/revision-requests`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ expected_revision: state.project.revision, selection: {
        kind: state.selected.kind, id: state.selected.id,
        start_ms: state.selected.startMs, end_ms: state.selected.endMs,
      }, instruction: note.value.trim() }),
    });
    note.value = ""; toast("Revision request is ready for the connected AI."); renderInspector();
  } catch (error) { toast(error instanceof Error ? error.message : "Revision request failed."); }
  finally { button.disabled = false; }
}

async function appendRevisionState(root: HTMLElement): Promise<void> {
  if (!state.project || !state.selected) return;
  try {
    const response = await api<{ requests: RevisionRequest[] }>(`/projects/${state.project.project_id}/revision-requests`);
    const requests = response.requests.filter((request) => request.selection.id === state.selected?.id && ["pending", "proposed"].includes(request.status));
    for (const request of requests) {
      const card = document.createElement("section"); card.className = "inspector-section revision-state";
      const heading = document.createElement("h3"); heading.textContent = request.status === "pending" ? "Waiting for AI" : "Revision proposed";
      const text = document.createElement("p"); text.textContent = request.proposal?.summary || request.instruction; card.append(heading, text);
      if (request.status === "proposed") {
        const preview = document.createElement("img"); preview.className = "proposal-preview"; preview.alt = "Renderer preview of the proposed revision"; card.append(preview);
        void loadProposalPreview(request, preview);
        const actions = document.createElement("div"); actions.className = "mini-actions";
        const reject = document.createElement("button"); reject.className = "secondary-button"; reject.textContent = "Reject";
        const accept = document.createElement("button"); accept.className = "small-primary"; accept.textContent = "Apply revision";
        reject.onclick = () => void decideRevision(request, false); accept.onclick = () => void decideRevision(request, true); actions.append(reject, accept); card.append(actions);
      }
      root.append(card);
    }
  } catch { /* Inspector remains usable while the external client is disconnected. */ }
}

async function loadProposalPreview(request: RevisionRequest, image: HTMLImageElement): Promise<void> {
  if (!state.project) return;
  try {
    const info = await sidecar(); const at = Math.min(request.selection.start_ms, state.durationMs - 1);
    const response = await fetch(`http://127.0.0.1:${info.port}/projects/${state.project.project_id}/revision-requests/${request.request_id}/preview?expected_revision=${state.project.revision}&at_ms=${at}`, { headers: { Authorization: `Bearer ${info.token}` } });
    if (!response.ok) throw new Error(); image.src = URL.createObjectURL(await response.blob());
  } catch { image.replaceWith(document.createTextNode("Preview is unavailable for this proposal.")); }
}

function appendTimingOverride(root: HTMLElement): void {
  if (!state.selected) return;
  const section = document.createElement("section"); section.className = "inspector-section"; section.innerHTML = "<h3>Manual timing override</h3>";
  const start = document.createElement("input"); start.type = "number"; start.min = "0"; start.value = String(state.selected.startMs); start.setAttribute("aria-label", "Start time in milliseconds");
  const end = document.createElement("input"); end.type = "number"; end.min = "1"; end.value = String(state.selected.endMs); end.setAttribute("aria-label", "End time in milliseconds");
  const save = document.createElement("button"); save.className = "small-primary"; save.textContent = "Save timing";
  save.onclick = () => void saveBoardTiming(Number(start.value), Number(end.value)); section.append(start, end, save); root.append(section);
}

async function saveBoardTiming(startMs: number, endMs: number): Promise<void> {
  if (!state.project || !state.layout || !state.selected || !Number.isInteger(startMs) || !Number.isInteger(endMs) || startMs < 0 || endMs <= startMs) { toast("Enter a valid start and end time."); return; }
  const document = structuredClone(state.layout); const activation = document.board_timeline?.activations.find((item) => item.board_id === state.selected?.id);
  if (!activation) return;
  const delta = startMs - activation.start_ms; activation.start_ms = startMs; activation.end_ms = endMs;
  for (const element of document.elements.filter((item) => item.board_id === activation.board_id)) {
    element.appear_at_ms = Math.max(startMs, Math.min(endMs - 1, element.appear_at_ms + delta));
    element.visibility_intervals = element.visibility_intervals?.map((interval) => ({ start_ms: Math.max(startMs, interval.start_ms + delta), end_ms: Math.min(endMs, interval.end_ms + delta) }));
  }
  try {
    await api<ProjectState>(`/projects/${state.project.project_id}/artifacts/layout`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ document, expected_revision: state.project.revision }) });
    toast("Board timing saved as a new project revision."); await openProject(state.project.project_id);
  } catch (error) { toast(error instanceof Error ? error.message : "Timing change failed validation."); }
}

async function decideRevision(request: RevisionRequest, accepted: boolean): Promise<void> {
  if (!state.project) return;
  try {
    await api(`/projects/${state.project.project_id}/revision-requests/${request.request_id}/decision`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ expected_revision: state.project.revision, accepted }),
    });
    toast(accepted ? "AI edit applied to this project." : "AI edit rejected.");
    await openProject(state.project.project_id);
  } catch (error) { toast(error instanceof Error ? error.message : "Could not decide this revision."); }
}

async function uploadSource(file: File): Promise<MediaItem | null> {
  if (!state.project) return null;
  if (mediaTab === "assets") { await uploadAsset(file); return null; }
  const ext = file.name.slice(file.name.lastIndexOf(".")).toLowerCase(); const video = [".mp4", ".mov", ".mkv", ".webm"].includes(ext);
  if (!video && ext !== ".wav") { toast("This production build currently accepts PCM WAV, MP4, MOV, MKV and WebM sources."); return null; }
  toast(`Adding ${file.name}…`);
  try {
    const path = video ? "video" : "wav"; const headers: Record<string, string> = { "Content-Type": video ? file.type || "application/octet-stream" : "audio/wav", "X-Filename": file.name };
    const result = await api<{ project: ProjectState; media: MediaItem }>(`/projects/${state.project.project_id}/media/${path}?expected_revision=${state.project.revision}`, { method: "POST", headers, body: file });
    toast("Source added to the project media bin."); await openProject(result.project.project_id); return result.media;
  } catch (error) { toast(error instanceof Error ? error.message : "Source upload failed."); return null; }
}

async function uploadAsset(file: File): Promise<void> {
  if (!state.project) return;
  toast(`Adding ${file.name}…`);
  try {
    const result = await api<{ project: ProjectState }>(`/projects/${state.project.project_id}/assets?expected_revision=${state.project.revision}`, {
      method: "POST", headers: { "Content-Type": file.type || "application/octet-stream", "X-Filename": file.name }, body: file,
    });
    toast("Asset added to the project."); await openProject(result.project.project_id);
  } catch (error) { toast(error instanceof Error ? error.message : "Asset upload failed."); }
}

function selectMediaTab(tab: "sources" | "assets"): void {
  mediaTab = tab;
  document.querySelectorAll<HTMLButtonElement>("[data-media-tab]").forEach((button) => button.classList.toggle("active", button.dataset.mediaTab === tab));
  const input = $<HTMLInputElement>("source-file");
  input.accept = tab === "sources" ? "audio/wav,.wav,video/mp4,video/quicktime,video/x-matroska,video/webm,.mp4,.mov,.mkv,.webm" : ".png,.jpg,.jpeg,.webp,.gif,.svg,.pdf,.md,.txt,.json,.wav,.mp3,.m4a,.aac,.flac,.mp4,.mov,.mkv,.webm";
  $("add-source").textContent = tab === "sources" ? "＋ Add Source" : "＋ Add Asset";
  $("source-drop").textContent = tab === "sources" ? "Drop narration or source video here" : "Drop images, documents, audio or video here";
  renderSources();
}

function openNewProject(): void { $<HTMLDialogElement>("new-project-dialog").showModal(); $<HTMLInputElement>("new-project-title").focus(); }
function closeNewProject(): void { const dialog=$<HTMLDialogElement>("new-project-dialog"); dialog.close(); $<HTMLFormElement>("new-project-form").reset(); $("new-project-error").textContent=""; }
async function createProject(event: SubmitEvent): Promise<void> {
  event.preventDefault();
  const title = $<HTMLInputElement>("new-project-title").value.trim(); const profile = $<HTMLSelectElement>("new-project-profile").value;
  const file = $<HTMLInputElement>("new-project-source").files?.[0]; const error = $("new-project-error");
  if (!title) { error.textContent = "Enter a project name."; return; }
  const ext = file ? file.name.slice(file.name.lastIndexOf(".")).toLowerCase() : "";
  const inputKind = file ? ([".mp4", ".mov", ".mkv", ".webm"].includes(ext) ? "video-only" : "audio-only") : "idea-first";
  if (file && inputKind === "audio-only" && ext !== ".wav") { error.textContent = "Narration audio must be an uncompressed PCM WAV file."; return; }
  try {
    let project = await api<ProjectState>("/projects", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ title, profile, input_kind: inputKind }) });
    if (file) {
      const video = inputKind === "video-only"; const headers: Record<string, string> = { "Content-Type": video ? file.type || "application/octet-stream" : "audio/wav" }; if (video) headers["X-Filename"] = file.name;
      project = (await api<{ project: ProjectState }>(`/projects/${project.project_id}/media/${video ? "video" : "wav"}?expected_revision=${project.revision}`, { method: "POST", headers, body: file })).project;
    }
    $<HTMLDialogElement>("new-project-dialog").close(); $<HTMLFormElement>("new-project-form").reset(); error.textContent = "";
    await loadProjects(); toast("Project created. Select it from the project screen when you are ready to open it.");
  } catch (problem) { error.textContent = problem instanceof Error ? problem.message : "Project creation failed."; }
}

function showDialog(title: string, subtitle: string, content: HTMLElement): void {
  $("workspace-dialog-title").textContent = title; $("workspace-dialog-subtitle").textContent = subtitle;
  const root = $("workspace-dialog-content"); root.replaceChildren(content); $<HTMLDialogElement>("workspace-dialog").showModal();
}

function showValidationDialog(): void {
  const wrap = document.createElement("div");
  if (!state.validation) wrap.innerHTML = "<div class='workspace-card'><h3>Validation unavailable</h3><p>Try again after the local service is ready.</p></div>";
  else if (state.validation.ready) wrap.innerHTML = "<div class='workspace-card'><h3>Ready to render</h3><p>The current project revision has all required production artifacts and media.</p></div>";
  else for (const issue of state.validation.issues) {
    const card = document.createElement("div"); card.className = "workspace-card"; const title = document.createElement("h3"); title.textContent = issue.message; const code = document.createElement("p"); code.textContent = issue.code.replaceAll("_", " "); card.append(title, code);
    if (issue.code === "script_not_approved") { const approve = document.createElement("button"); approve.className = "small-primary"; approve.textContent = "Approve current script"; approve.onclick = () => void approveCurrentScript(); card.append(approve); }
    wrap.append(card);
  }
  showDialog("Export Check", state.project?.title || "Current project", wrap);
}

async function approveCurrentScript(): Promise<void> {
  if (!state.project?.artifacts.script) return;
  try {
    await api<ProjectState>(`/projects/${state.project.project_id}/script-approval`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ script_revision: state.project.artifacts.script, expected_revision: state.project.revision, approved: true }) });
    $<HTMLDialogElement>("workspace-dialog").close(); await openProject(state.project.project_id); toast("Current external script approved.");
  } catch (error) { toast(error instanceof Error ? error.message : "Script approval failed."); }
}

function showConnection(): void {
  const card = document.createElement("div"); card.className = "workspace-card";
  const live = document.createElement("div");
  connectionDetailsRoot = live;
  const details = document.createElement("details"); const summary = document.createElement("summary"); summary.textContent = "Advanced connection configuration";
  const output = document.createElement("textarea"); output.readOnly = true; output.className = "revision-box"; output.value = "Loading…"; details.append(summary, output);
  card.append(live, details);
  renderMcpStatus();
  void connectionInstruction("claude").then(value=>output.value=value).catch(() => { output.value = "Connection configuration is unavailable in this build."; });
  showDialog("AI Connection", "External AI · local MCP", card);
}

async function connectionSetup(client:string,jevKey=""):Promise<{config:string;steps:string}>{
  const c=await invoke<{command:string;args:string[]}>("mcp_connection_info");
  const serverConfig:{command:string;args:string[];env?:Record<string,string>}={command:c.command,args:c.args};
  if(jevKey)serverConfig.env={TYPESAFE_API_KEY:jevKey};
  const json=JSON.stringify({mcpServers:{atme:serverConfig}},null,2);
  const tomlString=(value:string)=>JSON.stringify(value);
  const toml=`[mcp_servers.atme]\ncommand = ${tomlString(c.command)}\nargs = [${c.args.map(tomlString).join(", ")}]\nstartup_timeout_sec = 20\ntool_timeout_sec = 120${jevKey?`\n\n[mcp_servers.atme.env]\nTYPESAFE_API_KEY = ${tomlString(jevKey)}`:""}`;
  const config=client==="claude"?json:toml;
  const steps=client==="claude"
    ? "Open Claude Desktop → Settings → Developer → Edit Config. Add this atme entry to the existing mcpServers object, save, and restart Claude Desktop."
    : "Open %USERPROFILE%\\.codex\\config.toml in a text editor. Add this TOML block, save, and restart the Windows client. ChatGPT Desktop and Codex use the same Codex MCP configuration on this computer.";
  return {config,steps};
}
async function connectionInstruction(client:string,jevKey=""):Promise<string>{return (await connectionSetup(client,jevKey)).config;}
async function showAiSetup():Promise<void>{const dialog=$<HTMLDialogElement>("ai-setup-dialog"),select=$<HTMLSelectElement>("ai-client"),output=$<HTMLTextAreaElement>("ai-setup-command"),steps=$("ai-setup-steps"),enable=$<HTMLInputElement>("enable-jev"),key=$<HTMLInputElement>("jev-key"),row=$("jev-key-row"),status=$("copy-ai-status"),button=$<HTMLButtonElement>("copy-ai-setup");const refresh=async()=>{row.classList.toggle("hidden",!enable.checked);const setup=await connectionSetup(select.value,enable.checked?key.value.trim():"");output.value=setup.config;steps.replaceChildren();const title=document.createElement("strong");title.textContent="What ATME will update";const copy=document.createElement("span");copy.textContent=setup.steps;steps.append(title,copy);status.textContent="";button.textContent="Copy configuration";button.classList.remove("copied");};select.onchange=()=>void refresh();enable.onchange=()=>void refresh();key.oninput=()=>void refresh();await refresh();dialog.showModal();}

async function installAiConnection(remove=false):Promise<void>{
  const client=$<HTMLSelectElement>("ai-client").value,enable=$<HTMLInputElement>("enable-jev"),key=$<HTMLInputElement>("jev-key").value.trim(),status=$("copy-ai-status"),button=$<HTMLButtonElement>(remove?"remove-ai-setup":"install-ai-setup");
  if(enable.checked&&!key){status.textContent="Enter the TypeSafe Jev key or turn off Jev.";return;}
  button.disabled=true;status.textContent=remove?"Removing ATME connection…":"Installing ATME connection…";
  try{
    const result=await invoke<{path:string;restart_required:boolean}>(remove?"remove_mcp_client":"install_mcp_client",remove?{client}:{client,jevKey:enable.checked?key:null});
    status.textContent=remove?"ATME was removed. Restart the AI client.":`Installed in ${result.path}. Restart the AI client, then ATME will verify the live handshake.`;
    toast(remove?"ATME connection removed.":"ATME connection installed. Restart the selected AI client.");
  }catch(error){status.textContent=typeof error==="string"?error:"ATME could not update the client configuration.";}finally{button.disabled=false;}
}

function showScript(): void {
  const card = document.createElement("div"); card.className = "workspace-card";
  if (!state.project) { card.innerHTML = "<h3>No project open</h3>"; showDialog("Script", "", card); return; }
  if (!state.script) { card.innerHTML = "<h3>No semantic script yet</h3><p>Your connected AI can derive or author the scene structure through MCP.</p>"; showDialog("Script", state.project.title, card); return; }
  const heading = document.createElement("h3"); heading.textContent = state.script.title || state.project.title;
  const copy = document.createElement("p"); copy.className = "script-copy"; copy.textContent = state.script.scenes.map((scene) => scene.spoken_text).join("\n\n");
  const override = document.createElement("details"); const summary = document.createElement("summary"); summary.textContent = "Manual override";
  const note = document.createElement("p"); note.textContent = "Use this only for a targeted correction. External AI remains the primary authoring path.";
  const editor = document.createElement("textarea"); editor.value = JSON.stringify(state.script, null, 2);
  const save = document.createElement("button"); save.className = "small-primary"; save.textContent = "Save manual revision";
  save.onclick = () => void saveScriptOverride(editor.value); override.append(summary, note, editor, save); card.append(heading, copy, override); showDialog("Script", "Externally authored · local override available", card);
}

async function saveScriptOverride(raw: string): Promise<void> {
  if (!state.project) return;
  try {
    const document = JSON.parse(raw) as ScriptDoc;
    await api<ProjectState>(`/projects/${state.project.project_id}/artifacts/script`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ document, expected_revision: state.project.revision }) });
    $<HTMLDialogElement>("workspace-dialog").close(); await openProject(state.project.project_id); toast("Manual script edit saved to this project.");
  } catch (error) { toast(error instanceof Error ? error.message : "Script revision failed."); }
}

function showStoryboard(): void {
  const wrap = document.createElement("div"); const activations = state.layout?.board_timeline?.activations || [];
  if (!activations.length) wrap.innerHTML = "<div class='workspace-card'><h3>No storyboard yet</h3><p>Your connected AI can add the storyboard and production layout through MCP.</p></div>";
  for (const item of activations) { const card = document.createElement("button"); card.className = "workspace-card project-row"; const label = document.createElement("strong"); label.textContent = item.board_id; const meta = document.createElement("small"); meta.textContent = `${formatTime(item.start_ms)} – ${formatTime(item.end_ms)}`; card.append(label, meta); card.onclick = () => { state.playheadMs = item.start_ms; state.selected = { kind: "illustration", id: item.board_id, label: item.board_id, startMs: item.start_ms, endMs: item.end_ms }; $<HTMLDialogElement>("workspace-dialog").close(); updatePlayhead(); renderInspector(); void refreshPreview(); }; wrap.append(card); }
  showDialog("Storyboard", state.project?.title || "Current project", wrap);
}

async function showRenders(): Promise<void> {
  const wrap = document.createElement("div");
  if (!state.project) { wrap.innerHTML = "<div class='workspace-card'><h3>No project open</h3></div>"; showDialog("Renders", "", wrap); return; }
  try {
    const response = await api<{ renders: Array<{ run_id: string; status: string; project_revision: number; manifest?: { duration_ms?: number } }> }>(`/projects/${state.project.project_id}/renders`);
    if (!response.renders.length) wrap.innerHTML = "<div class='workspace-card'><h3>No renders yet</h3><p>Validate the project, then use Render in the project bar.</p></div>";
    for (const run of response.renders) {
      const card = document.createElement("button"); card.className = "workspace-card project-row";
      const label = document.createElement("strong"); label.textContent = run.status === "done" ? "Completed render" : `Render ${run.status}`;
      const meta = document.createElement("small"); meta.textContent = `Revision ${run.project_revision} · ${run.run_id.slice(0, 8)}`; card.append(label, meta);
      if (run.status === "done") card.onclick = () => { $<HTMLDialogElement>("workspace-dialog").close(); void showRenderedVideo(state.project!.project_id, run.run_id); };
      wrap.append(card);
    }
  } catch (error) {
    const card = document.createElement("div"); card.className = "workspace-card"; const heading = document.createElement("h3"); heading.textContent = "Renders unavailable";
    const detail = document.createElement("p"); detail.textContent = error instanceof Error ? error.message : "Try again."; card.append(heading, detail); wrap.append(card);
  }
  showDialog("Renders", state.project.title, wrap);
}

async function setProfile(profile: ProjectState["profile"]): Promise<void> {
  if (!state.project || state.project.profile === profile) return;
  const previous = state.project.profile;
  state.project.profile = profile; applyViewerProfile(profile);
  try {
    const project = await api<ProjectState>(`/projects/${state.project.project_id}/profile`, {
      method: "PUT", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ profile, expected_revision: state.project.revision }),
    });
    await openProject(project.project_id); toast("Output profile changed. The connected AI may need to revise the layout.");
  } catch (error) { state.project.profile = previous; applyViewerProfile(previous); toast(error instanceof Error ? error.message : "Profile change failed."); }
}

async function renderProject(): Promise<void> {
  if (!state.project) return;
  await refreshValidation(false);
  if (!state.validation?.ready) { if(state.sourceTimeline?.document.clips.some(clip=>clip.kind==="video")){await exportManualTimeline();return;} showValidationDialog(); return; }
  if (!window.confirm("Render this exact saved project revision?")) return;
  try {
    const run = await api<{ run_id: string; status: string }>(`/projects/${state.project.project_id}/renders`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ expected_revision: state.project.revision, confirmed: true }) });
    toast("Render queued."); void pollRender(state.project.project_id, run.run_id);
  } catch (error) { toast(error instanceof Error ? error.message : "Render could not start."); }
}

async function exportManualTimeline():Promise<void>{if(!state.project)return;if(!window.confirm("Export the current manually edited timeline as an MP4?"))return;try{const info=await sidecar(),response=await fetch(`http://127.0.0.1:${info.port}/projects/${state.project.project_id}/timeline-export?expected_revision=${state.project.revision}`,{headers:{Authorization:`Bearer ${info.token}`}});if(!response.ok)throw new Error("Timeline export could not be created.");const url=URL.createObjectURL(await response.blob()),link=document.createElement("a");link.href=url;link.download=`ATME-${state.project.title.replace(/[^a-z0-9]+/gi,"-")}-timeline.mp4`;link.click();setTimeout(()=>URL.revokeObjectURL(url),30000);toast("Manual timeline export ready.");}catch(error){toast(error instanceof Error?error.message:"Timeline export failed.");}}

async function pollRender(projectId: number, runId: string): Promise<void> {
  for (let count = 0; count < 720; count++) {
    const run = await api<{ status: string; error?: string }>(`/projects/${projectId}/renders/${runId}`);
    if (run.status === "done") { await showRenderedVideo(projectId, runId); toast("Render complete."); return; }
    if (run.status === "failed") { toast(run.error || "Render failed."); return; }
    await new Promise((resolve) => window.setTimeout(resolve, 1000));
  }
}

async function showRenderedVideo(projectId: number, runId: string): Promise<void> {
  const info = await sidecar(); const response = await fetch(`http://127.0.0.1:${info.port}/projects/${projectId}/renders/${runId}/output`, { headers: { Authorization: `Bearer ${info.token}` } });
  if (!response.ok) return; const url = URL.createObjectURL(await response.blob()); const video = $<HTMLVideoElement>("render-video"); video.src = url;
  $("preview-image").classList.add("hidden"); $("viewer-message").classList.add("hidden"); $<HTMLVideoElement>("source-video").classList.add("hidden"); video.classList.remove("hidden"); void video.play();
}

function navigate(workspace: string): void {
  document.querySelectorAll(".nav-item").forEach((item) => item.classList.toggle("active", (item as HTMLElement).dataset.workspace === workspace));
  if (workspace === "projects") showProjectBrowser(true);
  else if (workspace === "sources" || workspace === "assets") showMediaPanel(workspace);
  else if (workspace === "script") showScript();
  else if (workspace === "storyboard") showStoryboard();
  else if (workspace === "timeline") $("timeline-tracks").focus();
  else if (workspace === "validation") void refreshValidation(true);
  else if (workspace === "renders") void showRenders();
  else if (workspace === "connection") showConnection();
  else if (workspace === "style") { inspectorTab = "style"; renderInspector(); }
  if (workspace !== "projects" && workspace !== "sources" && workspace !== "assets") showProjectBrowser(false);
}

function timelineTime(clientX: number): number {
  const tracks = $("timeline-tracks"); const bounds = tracks.getBoundingClientRect();
  const ratio = Math.max(0, Math.min(1, (clientX - bounds.left - 145 + tracks.scrollLeft) / timelineWidth()));
  return Math.round(ratio * state.durationMs);
}

function beginRange(event: PointerEvent): void {
  if (!state.project || (event.target as HTMLElement).closest(".clip") || event.clientX < $("timeline-tracks").getBoundingClientRect().left + 145) return;
  rangeAnchorMs = timelineTime(event.clientX); $("timeline-tracks").setPointerCapture(event.pointerId);
  updateRangeVisual(rangeAnchorMs, rangeAnchorMs);
}

function moveRange(event: PointerEvent): void { if (rangeAnchorMs !== null) updateRangeVisual(rangeAnchorMs, timelineTime(event.clientX)); }
function finishRange(event: PointerEvent): void {
  if (rangeAnchorMs === null) return;
  const other = timelineTime(event.clientX); const start = Math.min(rangeAnchorMs, other); const end = Math.max(rangeAnchorMs, other); rangeAnchorMs = null;
  if (end - start < 200) { state.playheadMs = start; state.selected = null; $("range-selection").classList.add("hidden"); }
  else { state.playheadMs=start;selectedClipIds.clear();for(const clip of state.sourceTimeline?.document.clips||[]){const clipEnd=clip.timeline_start_ms+clip.source_end_ms-clip.source_start_ms;if(clip.timeline_start_ms<end&&clipEnd>start)selectedClipIds.add(clip.clip_id);}state.selected={kind:"timeline",id:`range-${start}-${end}`,label:`${selectedClipIds.size} selected clips`,startMs:start,endMs:end};updateRangeVisual(start,end); }
  updatePlayhead(); renderInspector(); updateEditCommands(); void refreshPreview();
}

function seekPlayhead(clientX: number): void {
  if (!state.project) return;
  state.playheadMs = timelineTime(clientX); state.selected = null;
  $("range-selection").classList.add("hidden"); updatePlayhead(); renderInspector(); updateEditCommands(); void refreshPreview();
}

function beginPlayheadDrag(event: PointerEvent): void {
  if (!state.project) return;
  event.preventDefault(); event.stopPropagation();
  playheadDragTarget = event.currentTarget as HTMLElement;
  playheadDragTarget.setPointerCapture(event.pointerId); seekPlayhead(event.clientX);
}

function movePlayheadDrag(event: PointerEvent): void { if (playheadDragTarget) seekPlayhead(event.clientX); }

function finishPlayheadDrag(event: PointerEvent): void {
  if (!playheadDragTarget) return;
  seekPlayhead(event.clientX);
  if (playheadDragTarget.hasPointerCapture(event.pointerId)) playheadDragTarget.releasePointerCapture(event.pointerId);
  playheadDragTarget = null;
}

function updateRangeVisual(startMs: number, endMs: number): void {
  const node = $("range-selection"); const start = Math.min(startMs, endMs); const end = Math.max(startMs, endMs);
  const width = timelineWidth(); node.style.left = `${145 + start / state.durationMs * width}px`;
  node.style.width = `${Math.max(2, (end - start) / state.durationMs * width)}px`; node.classList.remove("hidden");
}

function setZoom(value: number, anchorClientX?: number): void {
  const tracks = $("timeline-tracks"); const before = timelineWidth(); const bounds = tracks.getBoundingClientRect();
  const anchor = anchorClientX === undefined ? state.playheadMs / state.durationMs : Math.max(0, Math.min(1, (anchorClientX - bounds.left - 145 + tracks.scrollLeft) / before));
  state.zoom = Math.max(.005, Math.min(8, value)); const after = timelineWidth(); renderTimeline();
  tracks.scrollLeft = Math.max(0, anchor * after - (anchorClientX === undefined ? (tracks.clientWidth - 145) / 2 : anchorClientX - bounds.left - 145));
  updateRulerScroll();
  $("zoom-label").textContent = `${Math.round(state.zoom * 100)}%`;
}

function fitTimeline(): void { const viewport = Math.max(120, $("timeline-tracks").clientWidth - 145); setZoom(viewport / Math.max(120, state.durationMs / 1000 * 80)); $("timeline-tracks").scrollLeft = 0; updateRulerScroll(); }

function runMenuAction(action:string):void{
  const click=(id:string)=>$<HTMLButtonElement>(id).click();
  if(action==="projects")showProjectBrowser(true);else if(action==="new-project")openNewProject();else if(action==="import")click("add-source");else if(action==="render")click("render-project");
  else if(action==="undo")click("undo-edit");else if(action==="redo")click("redo-edit");else if(action==="cut")click("cut-edit");else if(action==="delete")click("delete-edit");else if(action==="ripple")click("ripple-delete");
  else if(["sources","script","storyboard","timeline","assets"].includes(action))navigate(action);else if(action==="fit-timeline")fitTimeline();else if(action==="fullscreen")void $("viewer").requestFullscreen();
  else if(action==="connection")showConnection();else if(action==="setup-ai")void showAiSetup();else if(action==="shortcuts")toast("Shortcuts: V Select · B Blade · S Snap · Ctrl+K Split · Ctrl+Z Undo · Ctrl+Y Redo · Delete Remove");
}

window.addEventListener("DOMContentLoaded", () => {
  void listen("atme://return-to-projects", () => showProjectBrowser(true));
  void getCurrentWindow().onDragDropEvent(async ({payload}) => {
    if (payload.type !== "drop" || !state.project) return;
    const scale=window.devicePixelRatio||1, x=payload.position.x/scale, y=payload.position.y/scale;
    const ontoTimeline=Boolean(document.elementFromPoint(x,y)?.closest("#timeline-tracks"));
    for(const path of payload.paths){
      try { const result=await invoke<{project:ProjectState;media:MediaItem}>("import_dropped_source",{path,projectId:state.project.project_id,expectedRevision:state.project.revision}); await openProject(result.project.project_id); if(ontoTimeline) await insertMedia(result.media.media_id,timelineTime(x)); }
      catch(error){toast(typeof error==="string"?error:"ATME could not import the dropped media.");}
    }
  });
  $("workspace-nav").addEventListener("click", (event) => { const button = (event.target as HTMLElement).closest<HTMLButtonElement>("[data-workspace]"); if (button) navigate(button.dataset.workspace || "sources"); });
  $("return-projects").onclick = () => showProjectBrowser(true); $("project-picker").onclick = () => showProjectBrowser(true);
  $("launcher-new-project").onclick = openNewProject; $("empty-new-project").onclick = openNewProject;
  $("launcher-connect-ai").onclick=()=>void showAiSetup();$("close-ai-setup").onclick=()=> $<HTMLDialogElement>("ai-setup-dialog").close();$("copy-ai-setup").onclick=async()=>{const button=$<HTMLButtonElement>("copy-ai-setup"),status=$("copy-ai-status");try{await navigator.clipboard.writeText($<HTMLTextAreaElement>("ai-setup-command").value);button.textContent="✓ Copied";button.classList.add("copied");status.textContent="Configuration copied to clipboard.";window.setTimeout(()=>{button.textContent="Copy configuration";button.classList.remove("copied");status.textContent="";},2500);}catch{status.textContent="Clipboard access failed. Select the configuration and press Ctrl+C.";}};
  $("install-ai-setup").onclick=()=>void installAiConnection();$("remove-ai-setup").onclick=()=>void installAiConnection(true);
  document.querySelector(".app-menu")?.addEventListener("click",event=>{const button=(event.target as HTMLElement).closest<HTMLButtonElement>("[data-menu-action]");if(!button)return;document.querySelectorAll<HTMLDetailsElement>(".app-menu details[open]").forEach(item=>item.removeAttribute("open"));runMenuAction(button.dataset.menuAction||"");});
  document.addEventListener("pointerdown",event=>{if(!(event.target as HTMLElement).closest(".app-menu"))document.querySelectorAll<HTMLDetailsElement>(".app-menu details[open]").forEach(item=>item.removeAttribute("open"));});
  $("cancel-new-project").onclick = closeNewProject; $("close-new-project").onclick = closeNewProject;
  $<HTMLFormElement>("new-project-form").addEventListener("submit", (event) => void createProject(event));
  $("close-workspace-dialog").onclick = () => $<HTMLDialogElement>("workspace-dialog").close();
  $("add-source").onclick = () => $<HTMLInputElement>("source-file").click();
  document.querySelectorAll<HTMLButtonElement>("[data-media-tab]").forEach((button) => button.onclick = () => selectMediaTab(button.dataset.mediaTab as "sources" | "assets"));
  document.querySelectorAll<HTMLButtonElement>("[data-inspector]").forEach((button) => button.onclick = () => { inspectorTab = button.dataset.inspector as typeof inspectorTab; renderInspector(); });
  $<HTMLInputElement>("source-file").onchange = (event) => { const input = event.currentTarget as HTMLInputElement; if (input.files?.[0]) void uploadSource(input.files[0]); input.value = ""; };
  const drop = $("source-drop"); drop.ondragover = (event) => { event.preventDefault(); drop.classList.add("dragging"); }; drop.ondragleave = () => drop.classList.remove("dragging"); drop.ondrop = (event) => { event.preventDefault(); drop.classList.remove("dragging"); if (event.dataTransfer?.files[0]) void uploadSource(event.dataTransfer.files[0]); };
  const tracks=$("timeline-tracks"); tracks.addEventListener("dragover",event=>event.preventDefault()); tracks.addEventListener("drop",event=>{event.preventDefault();const at=timelineTime(event.clientX);const mediaId=event.dataTransfer?.getData("application/x-atme-media");if(mediaId)void insertMedia(mediaId,at);else if(event.dataTransfer?.files[0])void (async()=>{const media=await uploadSource(event.dataTransfer!.files[0]);if(media)await insertMedia(media.media_id,at)})();});
  $("validation-pill").onclick = () => void refreshValidation(true); $("render-project").onclick = () => void renderProject(); $("open-connection").onclick = showConnection;
  $("play-preview").onclick = togglePreviewPlayback;
  $("undo-edit").onclick = () => void historyAction("undo");
  $("redo-edit").onclick = () => void historyAction("redo");
  $("cut-edit").onclick = cutSelected;
  $("select-tool").onclick=()=>setTool("select"); $("blade-tool").onclick=()=>setTool("blade"); $("snap-toggle").onclick=()=>{snapping=!snapping;$("snap-toggle").classList.toggle("active-tool",snapping);$("snap-toggle").setAttribute("aria-pressed",String(snapping));};
  $("delete-edit").onclick = () => deleteSelected(false); $("ripple-delete").onclick = () => deleteSelected(true);
  $("silence-markers").onclick = () => { state.showSilences = !state.showSilences; $("silence-markers").setAttribute("aria-pressed", String(state.showSilences)); renderTimeline(); };
  $("viewer-fit").onclick = () => { const viewer = $("viewer"); viewer.classList.toggle("fill"); $("viewer-fit").textContent = viewer.classList.contains("fill") ? "Fit" : "Fill"; };
  $("viewer-fullscreen").onclick = () => void $("viewer").requestFullscreen();
  $("timeline-tracks").onpointerdown = beginRange; $("timeline-tracks").onpointermove = moveRange; $("timeline-tracks").onpointerup = finishRange;
  const handle = $("playhead-handle"); handle.onpointerdown = beginPlayheadDrag; handle.onpointermove = movePlayheadDrag; handle.onpointerup = finishPlayheadDrag;
  const ruler = $("timeline-ruler-viewport"); ruler.onpointerdown = beginPlayheadDrag; ruler.onpointermove = movePlayheadDrag; ruler.onpointerup = finishPlayheadDrag;
  $("timeline-tracks").onscroll = updateRulerScroll;
  $("timeline-tracks").addEventListener("pointerdown",event=>{const handle=(event.target as HTMLElement).closest<HTMLButtonElement>(".track-resizer");if(handle)beginTrackResize(event,handle.closest<HTMLElement>(".track")!);},true);
  $("workspace-splitter").onpointerdown=beginWorkspaceResize;
  $("timeline-context-menu").addEventListener("click",event=>{const action=(event.target as HTMLElement).closest<HTMLButtonElement>("[data-action]")?.dataset.action;$("timeline-context-menu").classList.add("hidden");const clip=selectedSourceClip();if(!clip)return;if(action==="remove-clip")void applySourceEdit("remove_clip",{clip_id:clip.clip_id,linked:true});if(action==="detach-audio")void applySourceEdit("detach_audio",{clip_id:clip.clip_id,audio_track_index:0});if(action==="split-clip")cutSelected();if(action==="compound-clips")void applySourceEdit("create_compound",{clip_ids:Array.from(selectedClipIds)});});
  window.addEventListener("pointerdown",event=>{if(!(event.target as HTMLElement).closest("#timeline-context-menu"))$("timeline-context-menu").classList.add("hidden")});
  $("zoom-in").onclick = () => setZoom(state.zoom * 1.25); $("zoom-out").onclick = () => setZoom(state.zoom / 1.25); $("fit-timeline").onclick = fitTimeline;
  $("timeline-tracks").addEventListener("wheel", (event) => { if (event.ctrlKey) { event.preventDefault(); setZoom(state.zoom * Math.exp(-event.deltaY * .002), event.clientX); } else if (event.shiftKey && event.deltaY) { event.preventDefault(); $("timeline-tracks").scrollLeft += event.deltaY; } }, { passive: false });
  document.querySelectorAll<HTMLButtonElement>("[data-profile]").forEach((button) => button.onclick = () => void setProfile(button.dataset.profile as ProjectState["profile"]));
  window.addEventListener("keydown", (event) => {
    const target = event.target as HTMLElement;
    if (target.closest("input, textarea, select") || $<HTMLDialogElement>("workspace-dialog").open || $<HTMLDialogElement>("new-project-dialog").open) return;
    if (event.ctrlKey && !event.shiftKey && event.key.toLowerCase() === "z") { event.preventDefault(); void historyAction("undo"); }
    else if ((event.ctrlKey && event.key.toLowerCase() === "y") || (event.ctrlKey && event.shiftKey && event.key.toLowerCase() === "z")) { event.preventDefault(); void historyAction("redo"); }
    else if (event.ctrlKey && event.key.toLowerCase() === "k" && selectedSourceClip()) { event.preventDefault(); cutSelected(); }
    else if (event.key.toLowerCase()==="v") setTool("select"); else if(event.key.toLowerCase()==="b")setTool("blade");else if(event.key.toLowerCase()==="s")$("snap-toggle").click();
    else if (event.key === "Delete" || event.key === "Backspace") { const clip=selectedSourceClip();if(clip){event.preventDefault();void applySourceEdit("remove_clip",{clip_id:clip.clip_id,linked:true});}else if (state.selected?.kind === "timeline") { event.preventDefault(); deleteSelected(false); } }
  });
  void refreshStudioSync(true).catch((error) => toast(error instanceof Error ? error.message : "Could not load projects."));
  window.setInterval(() => void refreshStudioSync().catch(() => undefined), 2000);
  void watchMcpConnection();
  window.addEventListener("focus", () => void refreshStudioSync(true).catch(() => undefined));
  new ResizeObserver(() => { sizeViewerCanvas(); if (state.project) renderTimeline(); }).observe($("viewer-stage"));
});

function setTool(tool:"select"|"blade"):void{activeTool=tool;$("select-tool").classList.toggle("active-tool",tool==="select");$("blade-tool").classList.toggle("active-tool",tool==="blade");$("select-tool").setAttribute("aria-pressed",String(tool==="select"));$("blade-tool").setAttribute("aria-pressed",String(tool==="blade"));document.querySelector(".timeline")?.classList.toggle("blade-mode",tool==="blade");}
function beginTrackResize(event:PointerEvent,track:HTMLElement):void{event.preventDefault();event.stopPropagation();const handle=event.currentTarget as HTMLElement,startY=event.clientY,start=track.clientHeight;handle.setPointerCapture(event.pointerId);handle.onpointermove=e=>{if(handle.hasPointerCapture(e.pointerId))track.style.height=`${Math.max(38,Math.min(260,start+e.clientY-startY))}px`;};handle.onpointerup=e=>{if(handle.hasPointerCapture(e.pointerId))handle.releasePointerCapture(e.pointerId);handle.onpointermove=null;handle.onpointerup=null;void decorateSourceClips();};}
function beginWorkspaceResize(event:PointerEvent):void{const handle=$("workspace-splitter"),workspace=document.querySelector<HTMLElement>(".workspace")!;handle.setPointerCapture(event.pointerId);handle.classList.add("dragging");handle.onpointermove=e=>{if(!handle.hasPointerCapture(e.pointerId))return;const rect=workspace.getBoundingClientRect(),pct=Math.max(25,Math.min(72,(rect.bottom-e.clientY)/rect.height*100));workspace.style.setProperty("--timeline-row",`${pct}%`);sizeViewerCanvas();};handle.onpointerup=e=>{if(handle.hasPointerCapture(e.pointerId))handle.releasePointerCapture(e.pointerId);handle.classList.remove("dragging");handle.onpointermove=null;handle.onpointerup=null;};}
