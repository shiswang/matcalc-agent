"""显式 session→workflow 绑定信封（S7 第一刀）。

设计约束（与交接文档不变量对齐）：
- state.json 仍是任务唯一真相；本模块只存「会话焦点索引」，不推进、不提交；
- 绑定文件是 sidecar（outputs/knowledge/session_bindings.json），不入 git；
- 不新增 MCP 工具——仅供 dsh_bridge / conversation 内部使用；
- 可变命令建议携带 expected_revision，调用方用 check_revision 做 CAS。
"""
from __future__ import annotations

import json
import os
import time
from typing import Any, Optional

from .common import OUTPUTS_DIR as _OUTPUTS_DIR


def _bindings_path() -> str:
    override = os.environ.get("MATCALC_SESSION_BINDINGS")
    if override:
        return override
    return os.path.join(_OUTPUTS_DIR, "knowledge", "session_bindings.json")


def _load() -> dict:
    path = _bindings_path()
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
    if not isinstance(data["sessions"], dict):
        data["sessions"] = {}
    return data


def _save(data: dict) -> None:
    path = _bindings_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def bind(session_id: str, wf_id: str, project: Optional[str] = None) -> dict:
    """将 workflow 绑定到 session（幂等：同 session+wf 重复 bind 只刷新时间）。"""
    if not session_id or not str(session_id).strip():
        return {"ok": False, "error": "错误: [E_PARAM] session_id 不能为空"}
    if not wf_id or not str(wf_id).strip():
        return {"ok": False, "error": "错误: [E_PARAM] wf_id 不能为空"}
    sid = str(session_id).strip()
    wid = str(wf_id).strip()
    data = _load()
    entry = data["sessions"].setdefault(sid, {"workflows": {}, "updated_at": _now()})
    if not isinstance(entry, dict):
        entry = {"workflows": {}, "updated_at": _now()}
        data["sessions"][sid] = entry
    wfs = entry.setdefault("workflows", {})
    if not isinstance(wfs, dict):
        wfs = {}
        entry["workflows"] = wfs
    prev = wfs.get(wid) if isinstance(wfs.get(wid), dict) else {}
    wfs[wid] = {
        "project": project if project is not None else prev.get("project"),
        "bound_at": prev.get("bound_at") or _now(),
        "last_seen": _now(),
    }
    entry["updated_at"] = _now()
    _save(data)
    return {"ok": True, "session_id": sid, "wf_id": wid, "bindings": entry["workflows"]}


def unbind(session_id: str, wf_id: Optional[str] = None) -> dict:
    """解除绑定：给 wf_id 只解一条；不给则清空该 session 全部绑定。"""
    if not session_id:
        return {"ok": False, "error": "错误: [E_PARAM] session_id 不能为空"}
    sid = str(session_id).strip()
    data = _load()
    if sid not in data["sessions"]:
        return {"ok": True, "session_id": sid, "removed": []}
    entry = data["sessions"][sid]
    wfs = entry.get("workflows") if isinstance(entry, dict) else None
    if not isinstance(wfs, dict):
        wfs = {}
    if wf_id:
        wid = str(wf_id).strip()
        removed = [wid] if wfs.pop(wid, None) is not None else []
    else:
        removed = sorted(wfs.keys())
        wfs.clear()
    entry["workflows"] = wfs
    entry["updated_at"] = _now()
    if not wfs:
        data["sessions"].pop(sid, None)
    _save(data)
    return {"ok": True, "session_id": sid, "removed": removed}


def get_bindings(session_id: str) -> dict:
    """返回该 session 的绑定视图（只读）。"""
    sid = str(session_id or "").strip()
    if not sid:
        return {"session_id": "", "workflows": {}, "wf_ids": []}
    entry = _load()["sessions"].get(sid) or {}
    wfs = entry.get("workflows") if isinstance(entry, dict) else {}
    if not isinstance(wfs, dict):
        wfs = {}
    return {
        "session_id": sid,
        "workflows": wfs,
        "wf_ids": sorted(wfs.keys()),
        "updated_at": entry.get("updated_at") if isinstance(entry, dict) else None,
    }


def bound_workflow_ids(session_id: str) -> list[str]:
    return get_bindings(session_id)["wf_ids"]


def check_revision(state: Optional[dict], expected_revision: Any) -> dict:
    """CAS：expected_revision 与 state.revision 不一致时拒绝，供调用方在 mutate 前检查。

    state 为 None（目标不存在）且 expected 有值时视为冲突，避免对陈旧目标写入。
    """
    if expected_revision is None:
        return {"ok": True, "skipped": True}
    try:
        expected = int(expected_revision)
    except (TypeError, ValueError):
        return {"ok": False, "error": "错误: [E_PARAM] expected_revision 必须是整数"}
    observed = None
    if isinstance(state, dict):
        observed = int(state.get("revision", 0) or 0)
    if observed is None:
        return {
            "ok": False,
            "error": f"错误: [E_PARAM] revision CAS 失败：目标不存在，期望 {expected}",
            "expected_revision": expected,
            "observed_revision": None,
        }
    if observed != expected:
        return {
            "ok": False,
            "error": f"错误: [E_PARAM] revision CAS 失败：期望 {expected}，实际 {observed}",
            "expected_revision": expected,
            "observed_revision": observed,
        }
    return {"ok": True, "observed_revision": observed}
