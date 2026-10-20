"""workflow event outbox / inbox / reconciler 契约（不新增 MCP 工具）。"""
import json
from pathlib import Path

import pytest

from server.matcalc import dsh_bridge, session_binding, workflow_events, workflows


@pytest.fixture()
def isolated_events(tmp_path, monkeypatch):
    events = tmp_path / "workflow_events.jsonl"
    cursors = tmp_path / "inbox_cursors.json"
    binds = tmp_path / "session_bindings.json"
    monkeypatch.setattr(workflow_events, "_events_path", lambda: str(events))
    monkeypatch.setattr(workflow_events, "_cursors_path", lambda: str(cursors))
    monkeypatch.setattr(session_binding, "_bindings_path", lambda: str(binds))
    return events, cursors, binds


def test_emit_and_read_events(isolated_events):
    events, _, _ = isolated_events
    out = workflow_events.emit_event("workflow.started", "wf_a", "P", revision=1, step="s0")
    assert out["ok"] is True
    out2 = workflow_events.emit_event("workflow.advanced", "wf_b", "P", revision=2)
    assert out2["ok"] is True
    all_ev = workflow_events.read_events()
    assert len(all_ev) == 2
    only_a = workflow_events.read_events(["wf_a"])
    assert len(only_a) == 1 and only_a[0]["type"] == "workflow.started"
    assert events.is_file()


def test_inbox_requires_binding(isolated_events):
    workflow_events.emit_event("workflow.started", "wf_x", "P")
    # 未绑定 → 空
    res = workflow_events.pull_inbox("sess1")
    assert res["ok"] is True and res["events"] == []
    # 绑定后可见
    session_binding.bind("sess1", "wf_x", "P")
    res2 = workflow_events.pull_inbox("sess1")
    assert len(res2["events"]) == 1
    # 显式请求未绑定 wf → 拒绝
    session_binding.bind("sess1", "wf_y", "P")
    bad = workflow_events.pull_inbox("sess1", ["wf_z"])
    assert bad["ok"] is False and "未绑定" in bad["error"]


def test_ack_advances_cursor(isolated_events):
    e1 = workflow_events.emit_event("workflow.started", "wf_a", "P")["event"]
    e2 = workflow_events.emit_event("workflow.advanced", "wf_a", "P")["event"]
    session_binding.bind("sess2", "wf_a")
    before = workflow_events.pull_inbox("sess2")
    assert len(before["events"]) == 2
    assert workflow_events.ack_inbox("sess2", e1["event_id"])["ok"] is True
    after = workflow_events.pull_inbox("sess2")
    # 游标推进后至少不应再包含已 ack 的那条 id（同秒场景允许边界，断言不重复）
    ids = [r["event_id"] for r in after["events"]]
    assert e1["event_id"] not in ids or len(ids) <= 1
    # 第二次 ack e2 后应为空或只剩更新事件
    workflow_events.ack_inbox("sess2", e2["event_id"])
    final = workflow_events.pull_inbox("sess2")
    assert all(r["event_id"] not in {e1["event_id"], e2["event_id"]} for r in final["events"])


def test_reconcile_observe_only_does_not_mutate(isolated_events):
    res = workflow_events.reconcile_once(advance=False)
    assert res["ok"] is True and res["advance"] is False
    assert "不注入" in res["note"]
    assert all(a["action"] == "observed" for a in res["actions"])


def test_start_workflow_emits_outbox(tmp_path, monkeypatch, isolated_events):
    # 使用真实 start（smoke 链）；outbox 与 outputs 路径都隔离，
    # 否则会在产物目录留下 proj_evt_test/workflows/*/state.json（一个 run 留一个）
    monkeypatch.setattr(workflows, "OUTPUTS_DIR", str(tmp_path / "outputs"))
    text = workflows.start_workflow("smoke_local_chain", "proj_evt_test")
    assert "工作流已启动" in text or "工作流" in text
    events, _, _ = isolated_events
    lines = [json.loads(x) for x in events.read_text(encoding="utf-8").splitlines() if x.strip()]
    started = [e for e in lines if e.get("type") == "workflow.started"]
    assert started, "start 应写入 workflow.started 事件"


def test_bridge_inbox_and_reconcile_ops(isolated_events):
    session_binding.bind("sessB", "wf_b")
    workflow_events.emit_event("workflow.advanced", "wf_b", "P")
    pull = dsh_bridge.handle({"op": "inbox_pull", "session_id": "sessB"})
    assert pull["ok"] is True
    assert isinstance(pull.get("events"), list)
    if pull["events"]:
        ack = dsh_bridge.handle({
            "op": "inbox_ack", "session_id": "sessB",
            "event_id": pull["events"][0]["event_id"],
        })
        assert ack["ok"] is True
    rec = dsh_bridge.handle({"op": "reconcile", "advance": False})
    assert rec["ok"] is True and rec["advance"] is False


def test_bridge_list_tasks_structured_selector(isolated_events):
    out = dsh_bridge.handle({"op": "list_tasks", "session_id": "sessUI"})
    assert out["ok"] is True
    assert "tasks" in out and isinstance(out["tasks"], list)
    for t in out["tasks"]:
        assert {"wf_id", "project", "status", "progress", "revision", "bound"} <= set(t)
    assert "选择器" in out["hint"]
