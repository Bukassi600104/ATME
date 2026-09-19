interface Proposal {
  proposal_id: string;
  timeline: { activations: { board_id: string; start_ms: number; end_ms: number }[] };
  reasons: string[];
  assignments: { id: string; scene_id: number; board_id: string; appear_at_ms: number }[];
}

export function mountBoardProposal(root: HTMLElement, jobId: number, revision: string,
  info: { port: number; token: string }): void {
  const url = `http://127.0.0.1:${info.port}/jobs/${jobId}/board-proposal`;
  const headers = { Authorization: `Bearer ${info.token}` };
  const note = document.createElement("p");
  note.textContent = "Export the final-audio planning context for your preferred external AI, then import its proposal. " +
    "ATME validates and previews locally without API keys. Geometry and camera stay unchanged. " +
    "Acceptance replaces board/object timing and phrase links with measured times.";
  const generate = document.createElement("button"); generate.textContent = "Import external board proposal";
  const file = document.createElement("input"); file.type = "file"; file.accept = ".json,application/json";
  file.setAttribute("aria-label", "External board proposal JSON");
  const download = document.createElement("button"); download.textContent = "Export planning context";
  const load = document.createElement("button"); load.textContent = "Review saved proposal";
  const feedback = document.createElement("p"); feedback.setAttribute("role", "status");
  const review = document.createElement("div"); root.append(note, download, file, generate, load, feedback, review);
  const request = async (generateNew: boolean) => {
    generate.disabled = load.disabled = true; review.replaceChildren();
    feedback.textContent = generateNew ? "Validating imported proposal against final audio…" : "Loading saved proposal…";
    try {
      const selected = file.files?.[0];
      if (generateNew && !selected) throw new Error("Choose an external proposal JSON file.");
      if (selected && selected.size > 1024 * 1024) throw new Error("Proposal exceeds 1 MiB.");
      const response = await fetch(url + (generateNew ? `?revision=${encodeURIComponent(revision)}` : ""),
        { method: generateNew ? "POST" : "GET", headers: { ...headers, "Content-Type": "application/json" },
          body: generateNew ? await selected!.text() : undefined });
      const body = await response.json(); if (!response.ok) throw new Error(body.detail || "Proposal request failed.");
      if (!root.isConnected) return;
      const proposal = body as Proposal;
      const sequence = document.createElement("ol");
      proposal.timeline.activations.forEach((a, i) => {
        const item = document.createElement("li");
        item.textContent = `${a.board_id}: ${a.start_ms}–${a.end_ms} ms. ${proposal.reasons[i]}`;
        sequence.append(item);
      });
      const assignments = document.createElement("ul");
      for (const a of proposal.assignments) {
        const item = document.createElement("li");
        item.textContent = `Scene ${a.scene_id} · ${a.id} → ${a.board_id} at ${a.appear_at_ms} ms`;
        assignments.append(item);
      }
      const accept = document.createElement("button"); accept.textContent = "Accept this board proposal";
      const previewPanel = document.createElement("fieldset");
      const previewLegend = document.createElement("legend"); previewLegend.textContent = "Compare rendered frames before accepting";
      const timeLabel = document.createElement("label"); timeLabel.textContent = "Final-audio time (ms)";
      const time = document.createElement("input"); time.type = "number"; time.min = "0"; time.step = "1";
      time.max = String(proposal.timeline.activations.at(-1)!.end_ms - 1); time.value = "0";
      timeLabel.append(time);
      const landmarks = document.createElement("select"); landmarks.setAttribute("aria-label", "Board preview landmark");
      for (const a of proposal.timeline.activations) {
        for (const [label, value] of [["start", a.start_ms], ["end", a.end_ms - 1]] as const) {
          const option = document.createElement("option"); option.value = String(value);
          option.textContent = `${a.board_id} ${label} · ${value} ms`; landmarks.append(option);
        }
      }
      landmarks.onchange = () => { time.value = landmarks.value; };
      const render = document.createElement("button"); render.textContent = "Compare frames (no API charge)";
      const frames = document.createElement("div");
      const previewStatus = document.createElement("p"); previewStatus.setAttribute("role", "status");
      previewPanel.append(previewLegend, timeLabel, landmarks, render, previewStatus, frames);
      render.onclick = async () => {
        if (!time.reportValidity() || !time.value) return;
        render.disabled = true; frames.replaceChildren(); previewStatus.textContent = "Rendering saved and proposed layouts…";
        try {
          const at = Number(time.value);
          const results = await Promise.all((["current", "proposed"] as const).map(async version => {
            const response = await fetch(`${url}/preview?proposal_id=${encodeURIComponent(proposal.proposal_id)}&at_ms=${at}&version=${version}`, { headers });
            if (!response.ok) { const error = await response.json(); throw new Error(error.detail || "Preview failed."); }
            return { version, blob: await response.blob() };
          }));
          if (!previewPanel.isConnected) return;
          for (const result of results) {
            const figure = document.createElement("figure"); const caption = document.createElement("figcaption");
            caption.textContent = `${result.version === "current" ? "Saved layout" : "Proposed layout"} · ${at} ms`;
            const img = document.createElement("img"); img.alt = caption.textContent;
            img.style.width = "100%"; img.style.maxWidth = "960px";
            const objectUrl = URL.createObjectURL(result.blob);
            img.onload = img.onerror = () => URL.revokeObjectURL(objectUrl); img.src = objectUrl;
            figure.append(caption, img); frames.append(figure);
          }
          previewStatus.textContent = "Static frames from the production renderer. This does not verify full-motion pacing or narration sync.";
        } catch (error) { previewStatus.textContent = error instanceof Error ? error.message : "Preview failed."; }
        finally { render.disabled = false; }
      };
      review.append(sequence, assignments, previewPanel, accept);
      feedback.textContent = "Proposal only — saved project unchanged. Review the sequence and every assignment before accepting.";
      accept.onclick = async () => {
        accept.disabled = generate.disabled = load.disabled = true;
        try {
          const result = await fetch(`${url}/accept?proposal_id=${encodeURIComponent(proposal.proposal_id)}`,
            { method: "POST", headers });
          const data = await result.json(); if (!result.ok) throw new Error(data.detail || "Acceptance failed.");
          feedback.textContent = "Accepted with a backup; job paused for realignment. Reopen visual review before further edits, then resume to render.";
        } catch (error) {
          feedback.textContent = error instanceof Error ? error.message : "Acceptance failed.";
          accept.disabled = generate.disabled = load.disabled = false;
        }
      };
    } catch (error) { feedback.textContent = error instanceof Error ? error.message : "Proposal request failed."; }
    finally { generate.disabled = load.disabled = false; }
  };
  download.onclick = async () => {
    download.disabled = true;
    try {
      const response = await fetch(url + "/context", { headers });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || "Context export failed.");
      const objectUrl = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], { type: "application/json" }));
      const link = document.createElement("a"); link.href = objectUrl; link.download = "atme-board-planning-context.json";
      link.click(); setTimeout(() => URL.revokeObjectURL(objectUrl), 1000);
      feedback.textContent = "Context exported. Return JSON containing the unchanged source_hashes and a proposal matching proposal_schema.";
    } catch (error) { feedback.textContent = error instanceof Error ? error.message : "Context export failed."; }
    finally { download.disabled = false; }
  };
  generate.onclick = () => void request(true);
  load.onclick = () => void request(false);
}
