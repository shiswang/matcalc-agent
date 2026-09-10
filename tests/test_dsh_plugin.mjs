import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import {
  apply, bindWorkflow, deriveSessionScope, drainInbox,
  normalizeTransportText, sessionTaskFocused,
} from "../dsh-plugin/index.js";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const python = path.join(root, ".venv", "Scripts", "python.exe");

function isolatedConfig() {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "matcalc-dsh-"));
  return {
    matcalcRoot: root,
    python,
    env: {
      MATCALC_SESSION_BINDINGS: path.join(dir, "session_bindings.json"),
      MATCALC_WORKFLOW_EVENTS: path.join(dir, "workflow_events.jsonl"),
      MATCALC_INBOX_CURSORS: path.join(dir, "inbox_cursors.json"),
    },
    _dir: dir,
  };
}

function fakeContext() {
  const handlers = new Map();
  return {
    handlers,
    logger: { warn() {} },
    on(event, handler) { handlers.set(event, handler); },
  };
}

function user(id, text) {
  return { id, role: "user", source: { kind: "user" },
    content: [{ type: "text", text }] };
}

function decision() {
  return { kind: "enter", messages: [user("old", "历史消息")] };
}

test("transport mojibake is repaired only when it round-trips to CJK", () => {
  const mojibake = Buffer.from("继续处理", "utf8").toString("latin1");
  assert.equal(normalizeTransportText(mojibake), "继续处理");
  assert.equal(normalizeTransportText("plain ASCII"), "plain ASCII");
  assert.equal(normalizeTransportText("café"), "café");
});

test("session scope is rebuilt from durable tool events", () => {
  const scope = deriveSessionScope([
    { type: "tool/call", data: { name: "start_workflow", arguments: "{}" } },
    { type: "tool/result", data: { message: { role: "user", content: [
      { type: "text", text: "工作流 ID: relax_dos_standard_42" },
    ] } } },
  ], { project: "NaCl_demo" });
  assert.deepEqual(scope, {
    project: "NaCl_demo", wfId: "relax_dos_standard_42",
    workflowIds: ["relax_dos_standard_42"],
  });
});

test("unrelated conversation is passed through without recovery injection", async () => {
  const ctx = fakeContext();
  const config = isolatedConfig();
  apply(ctx, config);
  const handler = ctx.handlers.get("agent/pre-step");
  const original = decision();
  const result = await handler({
    agent: { session: { events: [] } }, messages: [user("u1", "帮我写会议纪要")],
    step: 1,
  }, async () => original);
  assert.strictEqual(result, original);
});

test("bare control after an unrelated turn is not routed to an old task", async () => {
  const ctx = fakeContext();
  const config = isolatedConfig();
  apply(ctx, config);
  const handler = ctx.handlers.get("agent/pre-step");
  const events = [{ type: "user/message", data: user("old", "帮我写会议纪要") }];
  assert.equal(sessionTaskFocused(events), false);
  const original = decision();
  const result = await handler({
    agent: { session: { events } }, messages: [user("u3", "继续")], step: 1,
  }, async () => original);
  assert.strictEqual(result, original);
});

test("focused continue receives only its task routing context", async () => {
  const ctx = fakeContext();
  const config = isolatedConfig();
  apply(ctx, config);
  const handler = ctx.handlers.get("agent/pre-step");
  const events = [
    { type: "user/message", data: user("old-task", "NaCl VASP relax_dos_standard") },
    { type: "tool/call", data: {
      name: "mcp__matcalc__start_workflow",
      arguments: JSON.stringify({ project: "NaCl_demo", wf_id: "relax_dos_standard_1788074143" }),
    } },
  ];
  assert.equal(sessionTaskFocused(events), true);
  const result = await handler({
    agent: { session: { events } }, messages: [user("u4", "继续")], step: 1,
  }, async () => decision());
  assert.equal(result.kind, "enter");
  assert.equal(result.messages.length, 2);
  assert.match(result.messages[1].content[0].text, /relax_dos_standard_1788074143/);
});

test("mojibake continue is normalized before routing", async () => {
  const ctx = fakeContext();
  const config = isolatedConfig();
  apply(ctx, config);
  const handler = ctx.handlers.get("agent/pre-step");
  const events = [
    { type: "user/message", data: user("old-task", "NaCl VASP relax_dos_standard") },
    { type: "tool/call", data: {
      name: "mcp__matcalc__start_workflow",
      arguments: JSON.stringify({ project: "NaCl_demo", wf_id: "relax_dos_standard_1788074143" }),
    } },
  ];
  const result = await handler({
    agent: { session: { events } }, messages: [user("u5", "ç»§ç»­")], step: 1,
  }, async () => decision());
  assert.equal(result.messages.length, 2);
  assert.match(result.messages[1].content[0].text, /advance_workflow/);
});

test("explicit new task is passed to the existing MCP tool chain unchanged", async () => {
  const ctx = fakeContext();
  const config = isolatedConfig();
  apply(ctx, config);
  const handler = ctx.handlers.get("agent/pre-step");
  const original = decision();
  const result = await handler({
    agent: { session: { events: [] } },
    messages: [user("u2", "NaCl VASP relax_dos_standard")], step: 1,
  }, async () => original);
  assert.strictEqual(result, original);
});

test("bindWorkflow and drainInbox talk to isolated bridge paths", async () => {
  const config = isolatedConfig();
  const bound = await bindWorkflow(config, undefined, "sess-plugin", "wf_demo", "P");
  assert.equal(bound?.ok, true);
  const raw = JSON.parse(fs.readFileSync(config.env.MATCALC_SESSION_BINDINGS, "utf8"));
  assert.ok(raw.sessions["sess-plugin"].workflows.wf_demo);

  // emit via python bridge
  const { spawnSync } = await import("node:child_process");
  const emit = spawnSync(python, ["-c",
    "from server.matcalc import workflow_events as e; print(e.emit_event('workflow.advanced','wf_demo','P')['ok'])",
  ], { cwd: root, env: { ...process.env, ...config.env }, encoding: "utf8" });
  assert.match(emit.stdout, /True/);

  const events = await drainInbox(config, undefined, "sess-plugin", ["wf_demo"], 5);
  assert.equal(events.length, 1);
  assert.equal(events[0].wf_id, "wf_demo");
  const after = await drainInbox(config, undefined, "sess-plugin", ["wf_demo"], 5);
  assert.equal(after.length, 0);
});
