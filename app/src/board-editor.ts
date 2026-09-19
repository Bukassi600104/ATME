import { mountBoardProposal } from "./board-proposal";

interface Activation { activation_id: string; board_id: string; start_ms: number; end_ms: number; }
interface NarrationTrigger { phrase: string; occurrence?: number; offset_ms?: number; min_confidence?: number; }
interface BoardDraft {
  revision: string; duration_ms: number;
  timeline: { version: string; boards: { board_id: string }[]; activations: Activation[] } | null;
  elements: { id: string; scene_id: number; type: string; board_id?: string; appear_at_ms: number; narration_trigger?: NarrationTrigger }[];
}

export function mountBoardEditor(root: HTMLElement, jobId: number, info: { port: number; token: string }): void {
  root.replaceChildren();
  const generation = crypto.randomUUID(); root.dataset.generation = generation;
  const load = document.createElement("button"); load.textContent = "Load board timeline editor";
  const content = document.createElement("div"); root.append(load, content);
  const url = `http://127.0.0.1:${info.port}/jobs/${jobId}/boards`;
  const headers = { Authorization: `Bearer ${info.token}`, "Content-Type": "application/json" };
  load.onclick = async () => {
    load.disabled = true; content.textContent = "Loading…";
    try {
      const response = await fetch(url, { headers }); const data = await response.json();
      if (!response.ok) throw new Error(data.detail || "Could not load board timeline.");
      if (root.dataset.generation !== generation) return;
      const draft = data as BoardDraft;
      content.replaceChildren();
      const note = document.createElement("p");
      note.textContent = `Final audio: ${draft.duration_ms} ms. Intervals are start-inclusive and end-exclusive. ` +
        "Use the same board name in a later row to return to it. Gaps render blank. Phrase links override object times after realignment to final audio. Blank phrase uses fixed time. Camera cues are unchanged. " +
        (draft.timeline ? "" : "This legacy layout starts as an unsaved single-board proposal.");
      content.append(note);
      const proposalPanel = document.createElement("details");
      const proposalTitle = document.createElement("summary"); proposalTitle.textContent = "External board proposal — import and review";
      const proposalContent = document.createElement("div"); proposalPanel.append(proposalTitle, proposalContent);
      content.append(proposalPanel); mountBoardProposal(proposalContent, jobId, draft.revision, info);
      const intervals = document.createElement("div"); content.append(intervals);
      const input = (value: string | number, label: string, numeric = false): HTMLInputElement => {
        const el = document.createElement("input"); el.value = String(value); el.setAttribute("aria-label", label);
        if (numeric) { el.type = "number"; el.min = "0"; el.step = "1"; }
        return el;
      };
      const addRow = (a: Activation) => {
        const row = document.createElement("fieldset"); row.dataset.activationId = a.activation_id;
        const legend = document.createElement("legend"); legend.textContent = "Board name · start (ms) · end (ms)";
        const board = input(a.board_id, "Board name"); board.dataset.field = "board";
        const start = input(a.start_ms, "Activation start milliseconds", true); start.dataset.field = "start";
        const end = input(a.end_ms, "Activation end milliseconds", true); end.dataset.field = "end";
        const remove = document.createElement("button"); remove.textContent = "Remove interval";
        remove.onclick = () => row.remove(); row.append(legend, board, start, end, remove); intervals.append(row);
      };
      for (const a of draft.timeline?.activations || [{ activation_id: "main-first", board_id: "main", start_ms: 0, end_ms: draft.duration_ms }]) addRow(a);
      const add = document.createElement("button"); add.textContent = "Add board interval / return";
      add.onclick = () => addRow({ activation_id: crypto.randomUUID(), board_id: "", start_ms: 0, end_ms: draft.duration_ms });
      content.append(add);
      const assignments: Record<string, { board: HTMLInputElement; time: HTMLInputElement; phrase: HTMLInputElement; occurrence: HTMLInputElement; offset: HTMLInputElement; confidence: HTMLInputElement }> = {};
      for (const element of draft.elements) {
        const row = document.createElement("fieldset"); const legend = document.createElement("legend");
        legend.textContent = `Scene ${element.scene_id} · ${element.id} · ${element.type}`;
        const board = input(element.board_id || "main", "Object board name");
        const time = input(element.appear_at_ms, "Object creation milliseconds", true);
        const trigger = element.narration_trigger;
        const phrase = input(trigger?.phrase || "", "Narration trigger phrase");
        const occurrence = input(trigger?.occurrence ?? "", "Phrase occurrence (blank requires a unique match)", true); occurrence.min = "1";
        const offset = input(trigger?.offset_ms ?? 0, "Timing offset milliseconds", true); offset.removeAttribute("min");
        const confidence = input(trigger?.min_confidence ?? 0.65, "Minimum alignment confidence", true); confidence.max = "1"; confidence.step = "0.01";
        row.append(legend);
        for (const [caption, control] of [["Object board", board], ["Fixed / provisional time (ms)", time],
          ["Spoken phrase in this scene (optional)", phrase], ["Occurrence (1-based; blank = unique)", occurrence],
          ["Offset from phrase start (ms)", offset], ["Minimum confidence (0–1)", confidence]] as const) {
          const label = document.createElement("label"); label.textContent = caption; label.append(control); row.append(label);
        }
        content.append(row); assignments[element.id] = { board, time, phrase, occurrence, offset, confidence };
      }
      const save = document.createElement("button"); save.textContent = "Save board timeline";
      const feedback = document.createElement("p"); feedback.setAttribute("role", "status"); content.append(save, feedback);
      save.onclick = async () => {
        save.disabled = true;
        try {
          const activations = Array.from(intervals.children).map((row) => {
            const value = (field: string) => (row.querySelector(`[data-field='${field}']`) as HTMLInputElement).value;
            return { activation_id: (row as HTMLElement).dataset.activationId, board_id: value("board").trim(),
              start_ms: Number(value("start")), end_ms: Number(value("end")) };
          });
          const result = await fetch(url, { method: "PUT", headers, body: JSON.stringify({
            revision: draft.revision,
            timeline: { version: "1", boards: Array.from(new Set(activations.map(a => a.board_id))).map(board_id => ({ board_id })), activations },
            assignments: Object.fromEntries(Object.entries(assignments).map(([id, fields]) => [id, {
              board_id: fields.board.value.trim(), appear_at_ms: Number(fields.time.value),
              narration_trigger: fields.phrase.value.trim() ? {
                phrase: fields.phrase.value.trim(), offset_ms: Number(fields.offset.value),
                min_confidence: Number(fields.confidence.value),
                ...(fields.occurrence.value.trim() ? { occurrence: Number(fields.occurrence.value) } : {}),
              } : null,
            }])),
          }) });
          const body = await result.json(); if (!result.ok) throw new Error(body.detail || "Save failed.");
          feedback.textContent = "Saved with a layout backup. Resume to resolve phrases against final narration; ambiguous, missing or low-confidence matches block rendering for review. Reopen visual review to refresh controls and previews.";
        } catch (error) {
          feedback.textContent = error instanceof Error ? error.message : "Could not save timeline."; save.disabled = false;
        }
      };
    } catch (error) { content.textContent = error instanceof Error ? error.message : "Could not load editor."; }
    finally { load.disabled = false; }
  };
}
