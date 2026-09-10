"""对话消息分类与 workflow 隔离测试。"""
import json

from server.matcalc import conversation, workflows


def _state(root, project, wf_id):
    d = root / project / "workflows" / wf_id
    d.mkdir(parents=True)
    (d / "state.json").write_text(json.dumps({
        "wf_id": wf_id, "project": project, "template": "smoke_local_chain",
        "status": "running", "current": 0,
        "steps": [{"name": "demo", "status": "waiting_submit", "submitted_job": "1.x"}],
        "params": {},
    }), encoding="utf-8")


def test_classify_message_prioritizes_continue():
    assert conversation.classify_message("继续 NMO 的计算") == "task_continue"
    assert conversation.classify_message("看看当前作业状态") == "task_status"
    assert conversation.classify_message("帮我计算 LiFePO4") == "task_create"
    assert conversation.classify_message("NaCl VASP relax_dos_standard") == "task_create"
    assert conversation.classify_message("解释一下带隙") == "general_chat"


def test_general_chat_never_mutates_workflow():
    result = conversation.route_message("解释一下 DFT+U")
    assert result == {"intent": "general_chat", "action": "pass_through",
                      "mutates_workflow": False}


def test_workflow_explanation_is_not_task_recovery():
    result = conversation.route_message("解释一下 workflow 状态机怎么设计")
    assert result["action"] == "pass_through"
    assert result["mutates_workflow"] is False


def test_new_task_never_reuses_old_workflow():
    result = conversation.route_message("帮我计算一个 NaCl")
    assert result["action"] == "create_required"
    assert result["composition"] == "NaCl"
    assert result["mutates_workflow"] is False


def test_explicit_vasp_template_points_model_to_existing_tools():
    result = conversation.route_message("NaCl VASP relax_dos_standard")
    assert result["intent"] == "task_create"
    assert result["composition"] == "NaCl"
    assert result["template"] == "relax_dos_standard"
    assert result["next_tool"] == "build_structure"
    assert result["requires_confirmation"] is False


def test_bare_continue_without_session_focus_is_silent(tmp_path, monkeypatch):
    _state(tmp_path, "p1", "wf_one")
    monkeypatch.setattr(workflows, "OUTPUTS_DIR", str(tmp_path))
    result = conversation.route_message("继续")
    assert result["action"] == "pass_through"
    assert result["reason"] == "no_task_focus"


def test_focus_without_binding_cannot_fall_back_to_global(tmp_path, monkeypatch):
    _state(tmp_path, "p1", "wf_one")
    monkeypatch.setattr(workflows, "OUTPUTS_DIR", str(tmp_path))
    result = conversation.route_message("继续", session_focused=True)
    assert result["action"] == "pass_through"
    assert result["reason"] == "no_task_focus"


def test_focused_continue_routes_from_persisted_state(tmp_path, monkeypatch):
    _state(tmp_path, "p1", "wf_one")
    monkeypatch.setattr(workflows, "OUTPUTS_DIR", str(tmp_path))
    result = conversation.route_message("继续", workflow_ids=["wf_one"],
                                        session_focused=True)
    assert result["intent"] == "task_continue"
    assert result["action"] == "selected"
    assert result["workflow"]["wf_id"] == "wf_one"
    assert result["mutates_workflow"] is False


def test_explicit_global_status_is_not_limited_by_session_scope(tmp_path, monkeypatch):
    _state(tmp_path, "p1", "wf_one")
    _state(tmp_path, "p2", "wf_two")
    monkeypatch.setattr(workflows, "OUTPUTS_DIR", str(tmp_path))
    result = conversation.route_message(
        "查看所有任务状态", workflow_ids=["wf_one"], session_focused=True)
    assert result["action"] == "overview"
    assert {r["wf_id"] for r in result["candidates"]} == {"wf_one", "wf_two"}


def test_multiple_session_bindings_never_guess_target(tmp_path, monkeypatch):
    _state(tmp_path, "p1", "wf_one")
    _state(tmp_path, "p2", "wf_two")
    monkeypatch.setattr(workflows, "OUTPUTS_DIR", str(tmp_path))
    result = conversation.route_message(
        "继续", workflow_ids=["wf_one", "wf_two"], session_focused=True)
    assert result["action"] == "choose"
    assert {r["wf_id"] for r in result["candidates"]} == {"wf_one", "wf_two"}
    explicit = conversation.route_message(
        "继续 wf_two", workflow_ids=["wf_one", "wf_two"], session_focused=True)
    assert explicit["action"] == "selected"
    assert explicit["workflow"]["wf_id"] == "wf_two"
