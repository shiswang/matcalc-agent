"""长任务连续性回归：active workflow 扫描、项目过滤、损坏状态隔离。"""
import json
import shutil
from pathlib import Path

from server.matcalc import workflows as wf
from server.matcalc.common import OUTPUTS_DIR


def _wfid(text: str) -> str:
    return text.split("工作流 ID:")[1].split()[0].strip()


def test_list_active_workflows_filters_done(clean_test_project):
    try:
        active_id = _wfid(wf.start_workflow("nmo_parent_compare", clean_test_project))
        done_id = _wfid(wf.start_workflow("smoke_local_chain", "active_done_proj"))
        wf.advance_workflow(done_id, "active_done_proj")

        out = wf.list_active_workflows()
        assert active_id in out
        # wf_id 只在单个 project 内唯一（秒级时间戳），全局扫描必须带上 project 才能判"不存在"
        assert f"{done_id} | project=active_done_proj" not in out
        assert "waiting_submit" in out
        assert "下一步" in out
    finally:
        shutil.rmtree(Path(OUTPUTS_DIR) / "active_done_proj", ignore_errors=True)


def test_list_active_workflows_project_filter(clean_test_project):
    active_id = _wfid(wf.start_workflow("nmo_parent_compare", clean_test_project))
    out = wf.list_active_workflows(clean_test_project)
    assert active_id in out
    assert f"project={clean_test_project}" in out
    assert "暂无未完成工作流" not in out


def test_active_listing_exposes_job_and_auto_submit(clean_test_project):
    active_id = _wfid(wf.start_workflow("nmo_parent_compare", clean_test_project,
        params_json=json.dumps({"auto_submit": True})))
    state = wf._load_state(active_id, clean_test_project)
    state["steps"][0]["submitted_job"] = "1234.example"
    wf._save_state(state)
    out = wf.list_active_workflows(clean_test_project)
    assert "job=1234.example" in out
    assert "auto_submit=True" in out


def test_active_listing_skips_corrupt_state(tmp_path, monkeypatch):
    root = tmp_path / "outputs"
    monkeypatch.setattr(wf, "OUTPUTS_DIR", str(root))
    bad = root / "bad_project" / "workflows" / "broken"
    bad.mkdir(parents=True)
    (bad / "state.json").write_text("{not-json", encoding="utf-8")
    assert "暂无未完成工作流" in wf.list_active_workflows()


def test_active_listing_empty_scope(clean_test_project):
    # 该 fixture 项目开始时为空，确认空结果是只读友好提示
    assert "暂无未完成工作流" in wf.list_active_workflows(clean_test_project)
