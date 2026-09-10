"""DSH bridge CLI：供 DSH profile plugin 通过 stdin/stdout 调用。

协议为一行一个 JSON 请求/响应，不使用网络、不保存凭据；所有任务事实仍来自
workflows 的 state.json。"""
from __future__ import annotations

import json
import sys

try:
    from . import conversation
    from . import session_binding
    from . import workflow_events
    from . import workflows
except ImportError:  # python server/matcalc/dsh_bridge.py
    from matcalc import conversation
    from matcalc import session_binding
    from matcalc import workflow_events
    from matcalc import workflows


def _route_context(request: dict, result: dict) -> dict:
    """构造只读路由信封；它是审计/并发契约，不是第二份任务状态。"""
    workflow = result.get("workflow") if isinstance(result, dict) else None
    workflow = workflow if isinstance(workflow, dict) else {}
    session_id = request.get("session_id")
    message_id = request.get("message_id")
    key = request.get("idempotency_key")
    if not key and message_id:
        key = f"{session_id or 'local'}:{message_id}"
    bound = session_binding.bound_workflow_ids(session_id) if session_id else []
    return {
        "session_id": session_id,
        "message_id": message_id,
        "workflow_id": workflow.get("wf_id") or request.get("wf_id"),
        "intent": result.get("intent") if isinstance(result, dict) else None,
        "observed_revision": workflow.get("revision"),
        "expected_revision": request.get("expected_revision"),
        "idempotency_key": key,
        "read_only": not bool(result.get("mutates_workflow", False)),
        "bound_workflow_ids": bound,
    }


def handle(request: dict) -> dict:
    op = request.get("op")
    scope = request.get("workflow_ids")
    if not isinstance(scope, list):
        scope = None
    session_id = request.get("session_id")
    # 未显式传 scope 时，用 session 绑定作默认焦点（仍是只读索引，不推进任务）。
    if scope is None and session_id:
        bound = session_binding.bound_workflow_ids(session_id)
        scope = bound or None
    if op == "startup":
        return {"ok": True, "summary": conversation.startup_context(
            request.get("project"), scope)}
    if op == "route":
        result = conversation.route_message(
            str(request.get("text", "")), request.get("project"),
            request.get("wf_id"), scope,
            bool(request.get("session_focused", False)))
        return {"ok": True, "result": result,
                "context": _route_context(request, result)}
    if op == "bind":
        return session_binding.bind(
            session_id or "", request.get("wf_id") or "",
            request.get("project"))
    if op == "unbind":
        return session_binding.unbind(session_id or "", request.get("wf_id"))
    if op == "bindings":
        return {"ok": True, "binding": session_binding.get_bindings(session_id or "")}
    if op == "check_revision":
        return session_binding.check_revision(
            request.get("state") if isinstance(request.get("state"), dict) else None,
            request.get("expected_revision"))
    if op == "inbox_pull":
        wf_ids = request.get("wf_ids")
        if wf_ids is not None and not isinstance(wf_ids, list):
            wf_ids = None
        return workflow_events.pull_inbox(
            session_id or "", wf_ids, int(request.get("limit") or 50))
    if op == "inbox_ack":
        return workflow_events.ack_inbox(session_id or "", request.get("event_id") or "")
    if op == "reconcile":
        return workflow_events.reconcile_once(advance=bool(request.get("advance")))
    if op == "list_tasks":
        # UI 任务选择器：结构化只读列表；include_bound 时标注 session 是否已绑定。
        project = request.get("project")
        rows = workflows._active_workflow_records(project if project else None)
        bound = set(session_binding.bound_workflow_ids(session_id)) if session_id else set()
        tasks = []
        for r in rows:
            item = {
                "wf_id": r["wf_id"],
                "project": r["project"],
                "template": r["template"],
                "status": r["status"],
                "progress": r["progress"],
                "current_step": r["current_step"],
                "current_status": r["current_status"],
                "job_id": r["job_id"] or None,
                "auto_submit": r["auto_submit"],
                "revision": r["revision"],
                "bound": r["wf_id"] in bound,
            }
            tasks.append(item)
        return {
            "ok": True,
            "session_id": session_id,
            "count": len(tasks),
            "tasks": tasks,
            "hint": "UI 可按 bound/progress 渲染选择器；选中后 bind + inbox_pull",
        }
    return {"ok": False, "error": "unknown operation"}


def main() -> int:
    # DSH 通过 Windows pipe 传 UTF-8；不要让系统 code page 把中文意图解码成 �。
    if hasattr(sys.stdin, "reconfigure"):
        sys.stdin.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
    for line in sys.stdin:
        try:
            request = json.loads(line)
            result = handle(request if isinstance(request, dict) else {})
        except (TypeError, ValueError) as exc:
            result = {"ok": False, "error": f"invalid request: {exc}"}
        # ASCII 转义避免 Windows 子进程 code page 在 DSH bridge 边界破坏中文；
        # JSON.parse 会在 Node 侧还原为 Unicode。
        sys.stdout.write(json.dumps(result, ensure_ascii=True) + "\n")
        sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
