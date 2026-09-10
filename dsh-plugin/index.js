import { spawn } from "node:child_process";
import { createUserMessage } from "@deepseek-ai/dsh-llm";

export const name = "matcalc-continuity";

/**
 * 兼容部分 Windows Web/stdio 边界把 UTF-8 字节按 Latin-1 解码的历史消息。
 * 仅在可无损还原为 CJK 且无替换字符时修复，避免改变正常拉丁文本。
 */
export function normalizeTransportText(value) {
  const text = String(value ?? "");
  if (!/[ÃÂÇÈÉÊËÌÍÎÏÐÑÒÓÔÕÖÙÚÛÜÝà-ÿ]/.test(text)) return text;
  try {
    const repaired = Buffer.from(text, "latin1").toString("utf8");
    if (repaired !== text && !repaired.includes("\uFFFD") && /[\u3400-\u9fff]/.test(repaired)) {
      return repaired;
    }
  } catch { /* 保留原文，让 bridge/模型继续处理 */ }
  return text;
}

function textOf(message) {
  if (!message || message.role !== "user") return "";
  return normalizeTransportText((message.content ?? []).filter((block) => block?.type === "text")
    .map((block) => block.text ?? "").join("\n").trim());
}

function eventText(data) {
  return normalizeTransportText((data?.message?.content ?? []).filter((block) => block?.type === "text")
    .map((block) => block.text ?? "").join("\n").trim());
}

const TASK_FOCUS_RE = /(?:VASP|LAMMPS|workflow|POSCAR|OUTCAR|DOS|PDOS|弛豫|作业|集群|提交|材料|结构)/i;
const CONTROL_RE = /(?:继续|恢复|接着|推进|跑下去|往下做|(?:查看|查询|列出|显示|看看).*(?:状态|进度|任务|工作流|workflow|作业)|(?:任务|工作流)\s*(?:状态|进度)|wf[_-]?id\s*[:=]?\s*[A-Za-z0-9_.-]+)/i;

function eventUserText(event) {
  const data = event?.data;
  if (event?.type !== "user/message" || data?.source?.kind !== "user") return "";
  return normalizeTransportText((data.content ?? []).filter((block) => block?.type === "text")
    .map((block) => block.text ?? "").join("\n").trim());
}

/** 只有最近一个直接人类消息仍是材料任务时，裸控制词才继承焦点。 */
export function sessionTaskFocused(events = []) {
  let taskActivitySinceUser = false;
  for (const event of [...(events ?? [])].reverse()) {
    const data = event?.data ?? {};
    if ((event.type === "tool/call" || event.type === "tool/result") &&
        isMatcalcTool(data.name)) {
      taskActivitySinceUser = true;
      continue;
    }
    const text = eventUserText(event);
    if (text) return TASK_FOCUS_RE.test(text) || taskActivitySinceUser;
  }
  return false;
}

function isControlCandidate(text) {
  return CONTROL_RE.test(text || "");
}

/** 从持久化 session 事件重建焦点，重启后不依赖内存。 */
function isWorkflowTool(name) {
  return ["start_workflow", "advance_workflow", "workflow_status"]
    .some((suffix) => String(name ?? "").endsWith(suffix));
}

function isMatcalcTool(name) {
  const value = String(name ?? "").toLowerCase();
  return value.includes("matcalc") || isWorkflowTool(name) ||
    ["build_structure", "generate_vasp_inputs", "submit_and_watch", "check_job"]
      .some((suffix) => value.endsWith(suffix));
}

export function deriveSessionScope(events = [], config = {}) {
  let project = config.project;
  let wfId = config.wfId;
  const workflowIds = new Set();
  // 保留“当前最近任务轮次”的局部候选，避免并行/历史结果把前台焦点倒写。
  let turnWorkflowIds = [];
  for (const event of events ?? []) {
    const data = event?.data ?? {};
    if (event.type === "user/message" && data?.source?.kind === "user") {
      turnWorkflowIds = [];
    }
    if (event.type === "tool/call" && isWorkflowTool(data.name)) {
      try {
        const args = JSON.parse(data.arguments ?? "{}");
        project = args.project ?? project;
        if (args.wf_id) {
          wfId = args.wf_id;
          workflowIds.add(args.wf_id);
          turnWorkflowIds.push(args.wf_id);
        }
      } catch { /* 损坏的历史参数不阻塞新会话 */ }
    }
    if (event.type === "tool/result") {
      const match = eventText(data).match(/工作流 ID:\s*(\S+)/);
      if (match) {
        wfId = match[1];
        workflowIds.add(match[1]);
        turnWorkflowIds.push(match[1]);
      }
    }
  }
  if (turnWorkflowIds.length > 0) wfId = turnWorkflowIds.at(-1);
  if (wfId) workflowIds.add(wfId);
  return { project, wfId, workflowIds: [...workflowIds] };
}

function callBridge(config, request, signal) {
  const command = config.python ?? "python";
  const args = [...(config.pythonArgs ?? ["-m", "server.matcalc.dsh_bridge"])];
  const child = spawn(command, args, {
    cwd: config.matcalcRoot,
    stdio: ["pipe", "pipe", "pipe"],
    windowsHide: true,
    env: { ...process.env, ...(config.env ?? {}) },
  });
  return new Promise((resolve, reject) => {
    let out = "";
    let err = "";
    const abort = () => child.kill();
    signal?.addEventListener("abort", abort, { once: true });
    child.stdout.on("data", (chunk) => { out += chunk; });
    child.stderr.on("data", (chunk) => { err += chunk; });
    child.on("error", reject);
    child.on("close", (code) => {
      signal?.removeEventListener("abort", abort);
      if (code !== 0) return reject(new Error(err || `bridge exited ${code}`));
      try { resolve(JSON.parse(out.trim().split("\n").pop() ?? "{}")); }
      catch (error) { reject(error); }
    });
    child.stdin.end(JSON.stringify(request) + "\n");
  });
}

/** 尽力绑定 session→workflow；失败不阻断对话。 */
export async function bindWorkflow(config, signal, sessionId, wfId, project) {
  if (!sessionId || !wfId) return null;
  try {
    return await callBridge(config, {
      op: "bind", session_id: sessionId, wf_id: wfId, project,
    }, signal);
  } catch {
    return null;
  }
}

/** 拉取未读后台事件并 ack；无事件返回空数组。 */
export async function drainInbox(config, signal, sessionId, wfIds, limit = 5) {
  if (!sessionId) return [];
  try {
    const res = await callBridge(config, {
      op: "inbox_pull", session_id: sessionId,
      wf_ids: Array.isArray(wfIds) && wfIds.length ? wfIds : undefined,
      limit,
    }, signal);
    const events = res?.events ?? [];
    for (const ev of events) {
      if (ev?.event_id) {
        await callBridge(config, {
          op: "inbox_ack", session_id: sessionId, event_id: ev.event_id,
        }, signal).catch(() => null);
      }
    }
    return events;
  } catch {
    return [];
  }
}

function contextMessage(text) {
  return createUserMessage({
    content: [{ type: "text", text }],
    source: {
      kind: "plugin", plugin: name, form: "snapshot",
      sections: [{ name, text }],
    },
  });
}

export function apply(ctx, config = {}) {
  const seen = new WeakMap();
  ctx.on("agent/pre-step", async ({ agent, messages, step, signal }, next) => {
    const decision = await next();
    if (decision.kind === "reject" || step !== 1) return decision;
    const latest = [...messages].reverse().find((message) => message.source?.kind === "user");
    if (!latest) return decision;
    let keys = seen.get(agent);
    if (!keys) { keys = new Set(); seen.set(agent, keys); }
    if (keys.has(latest.id)) return decision;
    keys.add(latest.id);
    try {
      const currentText = textOf(latest);
      // 新任务与普通话题直接交给 DSH 模型；bridge 只处理显式控制面请求。
      // 这样不会把“NaCl VASP …”改写成 bridge 指令，也不妨碍模型调用已有 MCP 工具。
      if (!isControlCandidate(currentText)) return decision;
      const scope = deriveSessionScope(agent.session?.events, config);
      const focused = sessionTaskFocused(agent.session?.events);
      const response = await callBridge(config, {
        op: "route", text: currentText,
        project: focused ? scope.project : undefined,
        wf_id: focused ? scope.wfId : undefined,
        workflow_ids: focused ? scope.workflowIds : undefined,
        session_id: agent.session?.id,
        message_id: latest.id,
        session_focused: focused,
      }, signal);
      const result = response.result;
      // 普通消息完全静默：不召回、不注入、不污染当前会话。
      if (!result || result.action === "pass_through") return decision;
      const contexts = [];
      if (result.action === "choose" || result.action === "overview") {
        contexts.push(result.message);
      } else if (result.action === "selected") {
        const w = result.workflow;
        const tool = result.intent === "task_status" ? "workflow_status" : "advance_workflow";
        contexts.push(`MatCalcAgent 路由：当前会话选择 ${w.project}/${w.wf_id}。按用户意图调用 ${tool}。`);
        // 持久化 session 焦点，并只向本会话投递该任务的未读后台事件。
        await bindWorkflow(config, signal, agent.session?.id, w.wf_id, w.project);
        if (result.intent === "task_continue" || result.intent === "task_status") {
          const events = await drainInbox(config, signal, agent.session?.id, [w.wf_id], 5);
          if (events.length) {
            const lines = events.map((ev) => {
              const payload = ev.payload && Object.keys(ev.payload).length
                ? ` ${JSON.stringify(ev.payload).slice(0, 120)}` : "";
              return `- [${ev.type}] ${ev.wf_id}${payload}`;
            });
            contexts.push(
              `后台事件（本会话已绑定任务，未读 ${events.length} 条，已 ack）：\n${lines.join("\n")}`);
          }
        }
      }
      if (contexts.length === 0) return decision;
      return {
        kind: "enter",
        messages: decision.messages.toSpliced(
          decision.messages.length, 0, contextMessage(contexts.join("\n\n"))),
      };
    } catch (error) {
      ctx.logger.warn("matcalc continuity bridge unavailable: %o", error);
      return decision;
    }
  });
}
