"""session→workflow 绑定信封与 revision CAS 契约（不新增 MCP 工具）。"""
import json
from pathlib import Path

import pytest

from server.matcalc import dsh_bridge, session_binding


@pytest.fixture()
def isolated_bindings(tmp_path, monkeypatch):
    path = tmp_path / "session_bindings.json"
    monkeypatch.setattr(session_binding, "_bindings_path", lambda: str(path))
    return path


def test_bind_unbind_roundtrip(isolated_bindings):
    assert session_binding.bind("sessA", "wf_1", project="P1")["ok"] is True
    assert session_binding.bind("sessA", "wf_2")["ok"] is True
    got = session_binding.get_bindings("sessA")
    assert got["wf_ids"] == ["wf_1", "wf_2"]
    assert got["workflows"]["wf_1"]["project"] == "P1"

    assert session_binding.unbind("sessA", "wf_1")["removed"] == ["wf_1"]
    assert session_binding.bound_workflow_ids("sessA") == ["wf_2"]
    assert session_binding.unbind("sessA")["removed"] == ["wf_2"]
    assert session_binding.bound_workflow_ids("sessA") == []
    assert not Path(isolated_bindings).exists() or json.loads(
        Path(isolated_bindings).read_text(encoding="utf-8")
    )["sessions"] == {}


def test_bind_rejects_empty_ids(isolated_bindings):
    assert session_binding.bind("", "wf")["ok"] is False
    assert session_binding.bind("s", "")["ok"] is False


def test_bridge_bind_route_envelope_includes_bound_ids(isolated_bindings):
    assert dsh_bridge.handle({
        "op": "bind", "session_id": "sessB", "wf_id": "wf_9", "project": "P",
    })["ok"] is True
    result = dsh_bridge.handle({
        "op": "route", "text": "继续", "session_id": "sessB",
        "message_id": "m1", "wf_id": "wf_9",
    })
    assert result["ok"] is True
    ctx = result["context"]
    assert ctx["bound_workflow_ids"] == ["wf_9"]
    assert ctx["idempotency_key"] == "sessB:m1"
    assert ctx["read_only"] is True


def test_bridge_uses_bindings_as_default_scope(isolated_bindings):
    # 绑定后，未显式 workflow_ids 时 scope 来自 session 绑定（route 不推进任务）
    session_binding.bind("sessC", "wf_only")
    result = dsh_bridge.handle({
        "op": "bindings", "session_id": "sessC",
    })
    assert result["binding"]["wf_ids"] == ["wf_only"]


def test_check_revision_cas(isolated_bindings):
    assert session_binding.check_revision({"revision": 3}, 3)["ok"] is True
    assert session_binding.check_revision({"revision": 3}, 4)["ok"] is False
    assert "CAS" in session_binding.check_revision({"revision": 3}, 4)["error"]
    assert session_binding.check_revision(None, 1)["ok"] is False
    assert session_binding.check_revision({"revision": 0}, None)["ok"] is True
    assert session_binding.check_revision({"revision": 1}, "x")["ok"] is False


def test_bridge_check_revision_op(isolated_bindings):
    out = dsh_bridge.handle({
        "op": "check_revision", "state": {"revision": 2}, "expected_revision": 2,
    })
    assert out["ok"] is True
    out2 = dsh_bridge.handle({
        "op": "check_revision", "state": {"revision": 1}, "expected_revision": 9,
    })
    assert out2["ok"] is False


def test_bridge_unknown_op_still_rejected(isolated_bindings):
    assert dsh_bridge.handle({"op": "nope"}) == {"ok": False, "error": "unknown operation"}
