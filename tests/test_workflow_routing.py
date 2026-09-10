"""任务恢复与路由策略的纯只读回归。"""
import json

from server.matcalc import workflows as wf


def _state(root, project, wf_id, status="running", current=0):
    d = root / project / "workflows" / wf_id
    d.mkdir(parents=True)
    data = {
        "wf_id": wf_id, "project": project, "template": "relax_dos_standard",
        "status": status, "current": current,
        "steps": [
            {"name": "relax", "type": "vasp_relax", "status": "waiting_submit",
             "submitted_job": "1234.example", "key_results": {}, "note": ""},
            {"name": "dos", "type": "vasp_static_dos", "status": "pending",
             "key_results": {}, "note": ""},
        ],
        "params": {"auto_submit": True},
    }
    (d / "state.json").write_text(json.dumps(data), encoding="utf-8")
    return data


def test_startup_summary_is_read_only_and_actionable(tmp_path, monkeypatch):
    _state(tmp_path, "p1", "wf_one")
    monkeypatch.setattr(wf, "OUTPUTS_DIR", str(tmp_path))
    before = (tmp_path / "p1" / "workflows" / "wf_one" / "state.json").read_text()
    out = wf.startup_recovery_summary()
    after = (tmp_path / "p1" / "workflows" / "wf_one" / "state.json").read_text()
    assert "发现 1 个未完成工作流" in out
    assert "wf_one" in out and "1234.example" in out
    assert before == after


def test_router_selects_single_candidate(tmp_path, monkeypatch):
    _state(tmp_path, "p1", "wf_one")
    monkeypatch.setattr(wf, "OUTPUTS_DIR", str(tmp_path))
    result = wf.route_workflow_request("继续")
    assert result["action"] == "selected"
    assert result["workflow"]["wf_id"] == "wf_one"


def test_router_requires_choice_for_multiple(tmp_path, monkeypatch):
    _state(tmp_path, "p1", "wf_one")
    _state(tmp_path, "p2", "wf_two")
    monkeypatch.setattr(wf, "OUTPUTS_DIR", str(tmp_path))
    result = wf.route_workflow_request("继续")
    assert result["action"] == "choose"
    assert {x["wf_id"] for x in result["candidates"]} == {"wf_one", "wf_two"}


def test_router_explicit_project_or_id_is_safe(tmp_path, monkeypatch):
    _state(tmp_path, "p1", "wf_one")
    _state(tmp_path, "p2", "wf_two")
    monkeypatch.setattr(wf, "OUTPUTS_DIR", str(tmp_path))
    by_project = wf.route_workflow_request("继续", project="p2")
    by_id = wf.route_workflow_request("继续", wf_id="wf_one")
    assert by_project["workflow"]["wf_id"] == "wf_two"
    assert by_id["workflow"]["project"] == "p1"


def test_router_explicit_text_target_overrides_candidate_order(tmp_path, monkeypatch):
    _state(tmp_path, "p1", "wf_one")
    _state(tmp_path, "p2", "wf_two")
    monkeypatch.setattr(wf, "OUTPUTS_DIR", str(tmp_path))
    result = wf.route_workflow_request(
        "请继续 workflow wf_two", workflow_ids=["wf_one", "wf_two"])
    assert result["action"] == "selected"
    assert result["reason"] == "explicit_text_target"
    assert result["workflow"]["wf_id"] == "wf_two"


def test_explicit_text_target_overrides_old_project_scope(tmp_path, monkeypatch):
    _state(tmp_path, "p1", "wf_one")
    _state(tmp_path, "p2", "wf_two")
    monkeypatch.setattr(wf, "OUTPUTS_DIR", str(tmp_path))
    result = wf.route_workflow_request("继续 p2", project="p1", wf_id="wf_one",
                                      workflow_ids=["wf_one"])
    assert result["action"] == "selected"
    assert result["workflow"]["project"] == "p2"
    assert result["workflow"]["wf_id"] == "wf_two"


def test_router_none_when_no_active(tmp_path, monkeypatch):
    _state(tmp_path, "p1", "wf_done", status="done")
    monkeypatch.setattr(wf, "OUTPUTS_DIR", str(tmp_path))
    result = wf.route_workflow_request("继续")
    assert result["action"] == "none"
    assert result["reason"] == "no_active_workflow"


def test_session_scope_does_not_leak_other_workflows(tmp_path, monkeypatch):
    _state(tmp_path, "p1", "wf_one")
    _state(tmp_path, "p2", "wf_two")
    monkeypatch.setattr(wf, "OUTPUTS_DIR", str(tmp_path))
    summary = wf.startup_recovery_summary(project="p1", workflow_ids=["wf_one"])
    assert "wf_one" in summary
    assert "wf_two" not in summary
    result = wf.route_workflow_request("继续", workflow_ids=["wf_one"])
    assert result["action"] == "selected"
    assert result["workflow"]["wf_id"] == "wf_one"
