"""Workflow 事件 outbox / session inbox 与后台 reconciler 原语（S7.2）。

设计约束：
- state.json 仍是任务唯一真相；事件只是变更流水，可重建可丢弃；
- outbox 为追加 JSONL（outputs/knowledge/workflow_events.jsonl），不入 git；
- inbox 用 session 游标只读拉取「已绑定 workflow」的未消费事件；
- reconciler 只推进状态机、写 outbox，**绝不向任何会话注入提示**；
- 不新增 MCP 工具。
"""
from __future__ import annotations

import json
import os
import time
import uuid
from typing import Any, Iterable, Optional

from .common import OUTPUTS_DIR as _OUTPUTS_DIR

try:
    from . import session_binding
    from . import workflows
except ImportError:  # pragma: no cover
    from matcalc import session_binding
    from matcalc import workflows


def _events_path() -> str:
    override = os.environ.get("MATCALC_WORKFLOW_EVENTS")
    if override:
        return override
    return os.path.join(_OUTPUTS_DIR, "knowledge", "workflow_events.jsonl")


def _cursors_path() -> str:
    override = os.environ.get("MATCALC_INBOX_CURSORS")
    if override:
        return override
    return os.path.join(_OUTPUTS_DIR, "knowledge", "workflow_inbox_cursors.json")


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def emit_event(
    event_type: str,
    wf_id: str,
    project: str,
    revision: Optional[int] = None,
    **payload: Any,
) -> dict:
    """追加一条 outbox 事件；失败时吞掉 IO 错误但返回 ok=False（不阻断主流程）。"""
    if not wf_id:
        return {"ok": False, "error": "错误: [E_PARAM] wf_id 不能为空"}
    rec = {
        "event_id": uuid.uuid4().hex,
        "ts": _now(),
        "type": str(event_type or "unknown"),
        "wf_id": str(wf_id),
        "project": str(project or ""),
        "revision": revision,
        "payload": {k: v for k, v in payload.items() if v is not None},
    }
    path = _events_path()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        return {"ok": True, "event": rec}
    except OSError as exc:
        return {"ok": False, "error": f"outbox 写入失败: {exc}"}


def read_events(
    wf_ids: Optional[Iterable[str]] = None,
    since_ts: Optional[str] = None,
    limit: int = 500,
) -> list[dict]:
    """只读扫描 outbox；可按 wf_id 集合与时间下界过滤。"""
    path = _events_path()
    if not os.path.isfile(path):
        return []
    wanted = set(wf_ids or [])
    out: list[dict] = []
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(rec, dict):
                continue
            if wanted and rec.get("wf_id") not in wanted:
                continue
            if since_ts and str(rec.get("ts") or "") <= str(since_ts):
                continue
            out.append(rec)
            if len(out) >= limit:
                break
    return out


def _load_cursors() -> dict:
    path = _cursors_path()
    if not os.path.isfile(path):
        return {"version": 1, "sessions": {}}
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return {"version": 1, "sessions": {}}
    if not isinstance(data, dict):
        return {"version": 1, "sessions": {}}
    data.setdefault("version", 1)
    data.setdefault("sessions", {})
    return data


def _save_cursors(data: dict) -> None:
    path = _cursors_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def pull_inbox(session_id: str, wf_ids: Optional[list[str]] = None,
               limit: int = 50) -> dict:
    """拉取该 session 应看到的未消费事件。

    默认范围 = session 绑定的 workflows；显式 wf_ids 必须是绑定子集，
    防止跨会话广播。只读，不推进 cursor。
    """
    sid = str(session_id or "").strip()
    if not sid:
        return {"ok": False, "error": "错误: [E_PARAM] session_id 不能为空"}
    bound = set(session_binding.bound_workflow_ids(sid))
    if wf_ids:
        extra = set(wf_ids) - bound
        if extra:
            return {
                "ok": False,
                "error": f"错误: [E_PARAM] 会话未绑定的 workflow: {sorted(extra)}",
            }
        scope = set(wf_ids)
    else:
        scope = bound
    if not scope:
        return {"ok": True, "session_id": sid, "events": [], "cursor": None}

    cursors = _load_cursors()["sessions"]
    cursor = cursors.get(sid) if isinstance(cursors.get(sid), dict) else {}
    last_ts = cursor.get("last_ts") or ""
    last_id = cursor.get("last_event_id") or ""

    events = []
    for rec in read_events(scope, since_ts=last_ts, limit=max(limit * 5, 100)):
        # 同秒内用 event_id 顺序兜底（ts 精度到秒）
        if last_ts and rec.get("ts") == last_ts and last_id:
            # 保留同 ts 但 id > last_id 的；简化：同 ts 且已见 id 全跳过
            if rec.get("event_id") == last_id:
                continue
        events.append(rec)
    # 二次过滤：last_id 之前的同 ts 事件
    if last_id and last_ts:
        seen = False
        filtered = []
        for rec in events:
            if rec.get("event_id") == last_id:
                seen = True
                continue
            if rec.get("ts") == last_ts and not seen:
                # last_id 尚未出现——可能是乱序，保守保留
                filtered.append(rec)
            else:
                filtered.append(rec)
        events = filtered
    events = events[:limit]
    return {
        "ok": True,
        "session_id": sid,
        "cursor": {"last_ts": last_ts, "last_event_id": last_id},
        "events": events,
    }


def ack_inbox(session_id: str, event_id: str) -> dict:
    """推进 session 游标到指定 event（必须是 outbox 中存在的事件）。"""
    sid = str(session_id or "").strip()
    eid = str(event_id or "").strip()
    if not sid or not eid:
        return {"ok": False, "error": "错误: [E_PARAM] session_id 与 event_id 必填"}
    match = None
    for rec in read_events(limit=10000):
        if rec.get("event_id") == eid:
            match = rec
            break
    if match is None:
        return {"ok": False, "error": "错误: [E_PARAM] event_id 不在 outbox 中"}
    data = _load_cursors()
    sessions = data.setdefault("sessions", {})
    sessions[sid] = {"last_ts": match.get("ts"), "last_event_id": eid, "acked_at": _now()}
    _save_cursors(data)
    return {"ok": True, "session_id": sid, "cursor": sessions[sid]}


def reconcile_once(advance: bool = False) -> dict:
    """后台对账一轮：扫描 active workflow；advance=True 时对 waiting_submit
    做幂等 advance（OUTCAR 缺失时 advance 自身会保持等待）。

    绝不读写 session 绑定、绝不向 inbox 推送、绝不 ssh 提交。
    """
    records = workflows._active_workflow_records(None)
    actions: list[dict] = []
    for rec in records:
        wf_id = rec["wf_id"]
        project = rec["project"]
        if not advance:
            actions.append({"wf_id": wf_id, "project": project, "action": "observed"})
            continue
        if rec.get("current_status") == "waiting_submit":
            text = workflows.advance_workflow(wf_id, project)
            emitted = emit_event(
                "reconcile.advance", wf_id, project,
                revision=rec.get("revision"),
                head=(text.splitlines()[0] if text else ""),
            )
            actions.append({
                "wf_id": wf_id,
                "project": project,
                "action": "advanced_or_waited",
                "emitted": emitted.get("ok", False),
            })
        else:
            actions.append({"wf_id": wf_id, "project": project, "action": "skipped"})
    return {
        "ok": True,
        "advance": bool(advance),
        "active_count": len(records),
        "actions": actions,
        "note": "reconciler 不注入任何会话；查询请用 pull_inbox",
    }

