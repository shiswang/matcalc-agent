"""DSH bridge CLI：供 DSH profile plugin 通过 stdin/stdout 调用。

协议为一行一个 JSON 请求/响应，不使用网络、不保存凭据；所有任务事实仍来自
workflows 的 state.json。"""
from __future__ import annotations

import json
import sys

try:
    from . import conversation
except ImportError:  # python server/matcalc/dsh_bridge.py
    from matcalc import conversation


def _route_context(request: dict, result: dict) -> dict:
    """构造只读路由信封；它是审计/并发契约，不是第二份任务状态。"""
    workflow = result.get("workflow") if isinstance(result, dict) else None
    workflow = workflow if isinstance(workflow, dict) else {}
    session_id = request.get("session_id")
    message_id = request.get("message_id")
    key = request.get("idempotency_key")
    if not key and message_id:
        key = f"{session_id or 'local'}:{message_id}"
    return {
        "session_id": session_id,
        "message_id": message_id,
        "workflow_id": workflow.get("wf_id") or request.get("wf_id"),
        "intent": result.get("intent") if isinstance(result, dict) else None,
        "observed_revision": workflow.get("revision"),
        "expected_revision": request.get("expected_revision"),
        "idempotency_key": key,
        "read_only": not bool(result.get("mutates_workflow", False)),
    }


def handle(request: dict) -> dict:
    op = request.get("op")
    scope = request.get("workflow_ids")
    if not isinstance(scope, list):
        scope = None
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
