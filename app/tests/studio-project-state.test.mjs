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
  const context = { exports: {}, fetch, document, Headers, structuredClone, window: {
    addEventListener() {}, setTimeout,
  }, require: () => ({ invoke: async () => ({ ready: true, port: 1234, token: "test" }) }),
  URL: { createObjectURL: (value) => "blob:" + value, revokeObjectURL() {} } };
  vm.runInNewContext(compiled + "\nglobalThis.driver = {state, api, optionalArtifact, showScript, showStoryboard, refreshPreview, showSpeechModel, deriveLayoutDuration};", context);
  context.driver.retimeBoardVisit = vm.runInNewContext("typeof retimeBoardVisit === 'function' && retimeBoardVisit", context);
  return { ...context.driver, nodes };
}

const project = { project_id: 7, title: "Test", revision: 8, artifacts: { script: 3 },
  authoritative_narrative_source: { mode: "script_authority" } };

test("retiming a board return preserves its opening, earlier visibility and other boards", () => {
  const ui = studio();
  const layout = {board_timeline:{activations:[
    {activation_id:"first",board_id:"A",start_ms:0,end_ms:1000},
    {activation_id:"proof",board_id:"B",start_ms:1000,end_ms:2000},
    {activation_id:"return",board_id:"A",start_ms:2000,end_ms:3000}]},
    elements:[{id:"old",board_id:"A",appear_at_ms:100,visibility_intervals:[
      {start_ms:250,end_ms:750},{start_ms:2200,end_ms:2600}]},
      {id:"new",board_id:"A",appear_at_ms:2300}]};
  const saved = ui.retimeBoardVisit(layout,"return",2400,3400);
  assert.equal(layout.board_timeline.activations[2].start_ms,2000);
  assert.equal(saved.board_timeline.activations[2].start_ms,2400);
  assert.equal(saved.elements[0].appear_at_ms,100);
  assert.deepEqual(saved.elements[0].visibility_intervals.map(x=>[x.start_ms,x.end_ms]),[[250,750],[2600,3000]]);
  assert.equal(saved.elements[1].appear_at_ms,2700);
  assert.throws(()=>ui.retimeBoardVisit(layout,"return",1950,2950),/overlap/i);
});

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

test("Studio compiles the reviewed storyboard once and displays its repair point", async () => {
  const requests = [];
  const ui = studio(async (url, init) => {
    requests.push([url, JSON.parse(init.body)]);
    return {ok: false, status: 400, json: async () => ({detail: {message: "Review spoken cues",
      errors: [{action_id: "return-1", code: "low_confidence"}]}})};
  });
  ui.state.project = project;
  ui.state.storyboard = {contract_version:"2.0.0", beats:[]};
  ui.showStoryboard();
  const wrap = ui.nodes.get("workspace-dialog-content").children[0];
  const compile = wrap.children.find(node => node.textContent === "Compile storyboard");
  await compile.onclick();
  assert.deepEqual(requests, [["http://127.0.0.1:1234/projects/7/compile-storyboard", {expected_revision:8}]]);
  assert.match(ui.nodes.get("toast").textContent, /return-1/);
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
