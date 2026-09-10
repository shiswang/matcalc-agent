"""DSH bridge 协议与 bundle 元数据的最小契约测试。"""
import json
import subprocess
import sys
from pathlib import Path

from server.matcalc import dsh_bridge


def test_bridge_routes_without_side_effects():
    result = dsh_bridge.handle({"op": "route", "text": "解释一下 DFT+U"})
    assert result["ok"] is True
    assert result["result"]["action"] == "pass_through"
    assert result["result"]["mutates_workflow"] is False


def test_bridge_startup_is_silent_without_session_scope():
    result = dsh_bridge.handle({"op": "startup"})
    assert result == {"ok": True, "summary": ""}


def test_bridge_emits_non_mutating_route_envelope():
    result = dsh_bridge.handle({
        "op": "route", "text": "继续", "session_id": "s1",
        "message_id": "m9", "wf_id": "wf_9", "expected_revision": 4,
    })
    context = result["context"]
    assert context == {
        "session_id": "s1", "message_id": "m9", "workflow_id": "wf_9",
        "intent": "task_continue", "observed_revision": None,
        "expected_revision": 4, "idempotency_key": "s1:m9", "read_only": True,
        "bound_workflow_ids": [],
    }


def test_bridge_exposes_new_task_to_existing_tool_chain():
    result = dsh_bridge.handle({"op": "route", "text": "NaCl VASP relax_dos_standard"})
    task = result["result"]
    assert task["action"] == "create_required"
    assert task["next_tool"] == "build_structure"
    assert task["mutates_workflow"] is False


def test_bridge_cli_keeps_utf8_intent(tmp_path):
    request = json.dumps({"op": "route", "text": "继续"}, ensure_ascii=False) + "\n"
    proc = subprocess.run(
        [sys.executable, "-m", "server.matcalc.dsh_bridge"],
        input=request, text=True, encoding="utf-8", capture_output=True,
        cwd=Path(__file__).parents[1], check=True,
    )
    result = json.loads(proc.stdout.strip())
    assert result["result"]["intent"] == "task_continue"
    assert result["result"]["action"] == "pass_through"


def test_bridge_rejects_unknown_operation():
    result = dsh_bridge.handle({"op": "nope"})
    assert result == {"ok": False, "error": "unknown operation"}


def test_dsh_bundle_declares_patch():
    manifest = json.loads((Path(__file__).parents[1] / "dsh-plugin" / "package.json").read_text())
    assert manifest["dsh"]["bundle"]["patch"] == "./cordis.patch.yml"
    assert manifest["main"] == "index.js"
    patch = (Path(__file__).parents[1] / "dsh-plugin" / "cordis.patch.yml").read_text()
    assert "@matcalc/dsh-continuity" in patch
    assert "matcalcRoot" in patch
