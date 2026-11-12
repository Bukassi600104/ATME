import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";
import ts from "typescript";

const source = readFileSync(new URL("../src/studio.ts", import.meta.url), "utf8");
const compiled = ts.transpileModule(source, { compilerOptions: {
  module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022,
} }).outputText;

function studio(fetch, setTimeout = () => {}) {
  const nodes = new Map();
  const element = () => ({
    children: [], isConnected: true, classList: { add() {}, remove() {}, contains() { return true; } },
    setAttribute() {},
    append(...children) { this.children.push(...children); },
    replaceChildren(...children) { this.children = children; },
    showModal() { this.open = true; },
  });
  const document = {
    createElement: element,
    getElementById(id) {
      if (!nodes.has(id)) nodes.set(id, element());
      return nodes.get(id);
    },
  };
  const context = { exports: {}, fetch, document, Headers, window: {
    addEventListener() {}, setTimeout,
  }, require: () => ({ invoke: async () => ({ ready: true, port: 1234, token: "test" }) }),
  URL: { createObjectURL: (value) => "blob:" + value, revokeObjectURL() {} } };
  vm.runInNewContext(compiled + "\nglobalThis.driver = {state, api, optionalArtifact, showScript, showStoryboard, refreshPreview, showSpeechModel, deriveLayoutDuration};", context);
  return { ...context.driver, nodes };
}

const project = { project_id: 7, title: "Test", revision: 8, artifacts: { script: 3 },
  authoritative_narrative_source: { mode: "script_authority" } };

test("the displayed script is fetched by saved revision and a stale approval cannot write", async () => {
  const urls = [];
  const ui = studio(async (url) => {
    urls.push(url);
    return { ok: true, json: async () => ({ document: { scenes: [{ spoken_text: "Reviewed text" }] } }) };
  });
  ui.state.project = project;
  ui.state.script = await ui.optionalArtifact(project, "script");
  ui.showScript();
  const approve = ui.nodes.get("workspace-dialog-content").children[0].children[2];
  ui.state.project = { ...project, revision: 9 };
  approve.onclick();
  assert.match(ui.nodes.get("toast").textContent, /project changed/i);
  assert.deepEqual(urls, ["http://127.0.0.1:1234/projects/7/artifacts/script?revision=3"]);
});

test("a stored storyboard can be reviewed while its layout is pending", () => {
  const ui = studio();
  ui.state.project = project;
  ui.state.storyboard = { beats: [{ beat_id: "opening", narration_summary: "Trace the relay." }] };
  ui.showStoryboard();
  const card = ui.nodes.get("workspace-dialog-content").children[0].children[0];
  assert.deepEqual(card.children.map(node => node.textContent), ["opening", "Trace the relay."]);
});

test("Studio reads board times and navigation from both stored layout formats", () => {
  const activations = [{board_id: "diagram", start_ms: 100, end_ms: 2800}];
  for (const layout of [{activations}, {board_timeline: {activations}}]) {
    const ui = studio();
    ui.state.project = project;
    ui.state.layout = layout;
    ui.showStoryboard();
    const board = ui.nodes.get("workspace-dialog-content").children[0].children[0];
    assert.equal(board.children[0].textContent, "diagram");
    assert.equal(typeof board.onclick, "function");
    assert.equal(ui.deriveLayoutDuration(layout), 2800);
  }
});

test("seeking twice cannot paint a delayed frame over the newer frame", async () => {
  let finishOld, began;
  const started = new Promise(resolve => { began = resolve; });
  const ui = studio(async (url) => ({
    ok: true, blob: async () => {
      if (url.endsWith("at_ms=0")) {
        began();
        return new Promise(resolve => { finishOld = resolve; });
      }
      return "next";
    },
  }));
  ui.state.project = project; ui.state.layout = {};
  const old = ui.refreshPreview();
  await started;
  ui.state.playheadMs = 1000;
  await ui.refreshPreview();
  finishOld("old"); await old;
  assert.equal(ui.nodes.get("preview-image").src, "blob:next");
});

test("first-run speech setup shows the local model status and prepares on demand", async () => {
  const methods = [];
  const ui = studio(async (_url, init) => {
    methods.push(init.method);
    return {ok: true, json: async () => ({status: init.method === "POST" ? "ready" : "not_ready"})};
  });
  ui.showSpeechModel();
  await new Promise(resolve => setImmediate(resolve));
  const [, status, prepare] = ui.nodes.get("workspace-dialog-content").children[0].children;
  assert.equal(prepare.textContent, "Prepare speech model");
  prepare.onclick();
  await new Promise(resolve => setImmediate(resolve));
  assert.deepEqual(methods, ["GET", "POST"]);
  assert.match(status.textContent, /ready for local timing/i);
  assert.equal(prepare.disabled, true);
});

test("a transient busy response retries one read and never submits a mutation twice", async () => {
  const methods = [];
  const ui = studio(async (_url, init) => {
    const method = init.method || "GET";
    methods.push(method);
    if (methods.length === 2) return {ok: true, status: 200, json: async () => ({ready: true})};
    return {ok: false, status: 503, headers: new Headers({"Retry-After": "1"}),
      json: async () => ({detail: {message: "Project storage is busy"}})};
  }, callback => callback());
  assert.equal((await ui.api("/projects")).ready, true);
  await assert.rejects(ui.api("/projects", {method: "POST"}), /storage is busy/);
  assert.deepEqual(methods, ["GET", "GET", "POST"]);
});
