"""vault_note 回归：Obsidian 结果笔记片段的渲染、落盘与 MCP 包装。

全部离线；落盘用例走 clean_test_project（outputs/pytest_tmp），开始清空、结束删除。
"""
import time
from pathlib import Path

from server.matcalc.common import OUTPUTS_DIR
from server.matcalc.vault_note import (
    export_result_note,
    render_result_note,
    save_result_note,
)

ROWS_SIMPLE = [("TOTEN", "-27.25"), ("带隙(eV)", "5.18")]


def _frontmatter(note: str) -> str:
    """截取 YAML frontmatter 正文（去掉首尾 --- 定界行）。"""
    assert note.startswith("---\n"), "片段必须以 frontmatter 开头"
    end = note.index("\n---\n", 4)
    return note[4:end]


# ---------- frontmatter ----------

def test_frontmatter_fields_complete_and_candidate():
    note = render_result_note("NaCl_project", "3687.master", ROWS_SIMPLE)
    fm = _frontmatter(note)
    assert "type: result-note" in fm
    assert "status: candidate" in fm  # 固定 candidate，不因入参变化
    assert f"created: {time.strftime('%Y-%m-%d')}" in fm
    assert 'project: "[[MatCalcAgent]]"' in fm
    assert 'source_job: "3687.master"' in fm
    assert "NaCl_project" in fm  # title 含 project
    tags_block = fm.split("tags:", 1)[1]
    assert "- candidate" in tags_block and "- result-note" in tags_block


def test_status_stays_candidate_even_with_experience():
    """即使补写了经验候选，状态也必须是 candidate（未经核验不晋升）。"""
    note = render_result_note(
        "p", "j", ROWS_SIMPLE, extra_experience=["SIGMA=0.05 时 DOS 更平滑"]
    )
    assert "status: candidate" in _frontmatter(note)


# ---------- 计算摘要表格 ----------

def test_table_row_count_matches_rows_and_escapes():
    rows = [("TOTEN", "-27.25"), ("备注", "a|b\nc")]
    note = render_result_note("p", "j", rows)
    data_rows = [
        ln for ln in note.splitlines()
        if ln.startswith("| ") and "---" not in ln
    ]
    # 表头 1 行 + 数据 2 行
    assert len(data_rows) == 3
    assert data_rows[0] == "| 量 | 值 |"
    # 竖线转 \|、换行转 <br>，同一数据行内不出现裸换行
    esc_line = next(ln for ln in data_rows if "a\\|b" in ln)
    assert "<br>" in esc_line
    assert "| 备注 | a\\|b<br>c |" in note


# ---------- 参数链 / 复现指引 / 经验候选 ----------

def test_params_chain_none_vs_list():
    without = render_result_note("p", "j", ROWS_SIMPLE)
    assert "（未提供）" in without
    with_chain = render_result_note("p", "j", ROWS_SIMPLE, params_chain=["bulk-relax", "dos"])
    assert "- bulk-relax" in with_chain
    assert "- dos" in with_chain


def test_repro_hint_switches_on_wf_id():
    plain = render_result_note("proj", "j", ROWS_SIMPLE)
    assert "outputs/proj/" in plain
    assert "workflows/" not in plain
    with_wf = render_result_note("proj", "j", ROWS_SIMPLE, wf_id="wf_123")
    assert "workflows/wf_123/" in with_wf


def test_experience_placeholder_vs_bullets():
    default = render_result_note("p", "j", ROWS_SIMPLE)
    assert "（待补写；未经核验不晋升）" in default
    filled = render_result_note(
        "p", "j", ROWS_SIMPLE, extra_experience=["经验一", "经验二"]
    )
    assert "- 经验一" in filled and "- 经验二" in filled
    assert "（待补写" not in filled


def test_all_sections_present_in_order():
    note = render_result_note(
        "p", "j", ROWS_SIMPLE,
        params_chain=["x"], wf_id="w", extra_experience=["e"],
    )
    heads = [ln for ln in note.splitlines() if ln.startswith("## ")]
    assert heads == ["## 计算摘要", "## 参数链", "## 复现指引", "## 经验候选"]


# ---------- save 落盘 ----------

def test_save_writes_readable_note_under_reports(clean_test_project):
    msg = save_result_note(
        clean_test_project, "3687.master", ROWS_SIMPLE, params_chain=["scf"]
    )
    assert msg.startswith("已保存: ")
    notes = list(Path(OUTPUTS_DIR).glob(f"{clean_test_project}/reports/note_*.md"))
    assert len(notes) == 1, "应恰好落盘一个 note_<时间戳>.md"
    text = notes[0].read_text(encoding="utf-8")
    # 落盘内容与渲染结果逐字一致（可读回）
    expected = render_result_note(
        clean_test_project, "3687.master", ROWS_SIMPLE, params_chain=["scf"]
    )
    assert text == expected


# ---------- export_result_note（MCP 包装） ----------

def test_export_happy_path_saves_file(clean_test_project):
    out = export_result_note(
        clean_test_project,
        "3687.master",
        rows_json='[["TOTEN","-27.25"]]',
        params_chain_json='["scf","dos"]',
    )
    assert out.startswith("已保存: ")
    notes = list(Path(OUTPUTS_DIR).glob(f"{clean_test_project}/reports/note_*.md"))
    assert len(notes) == 1
    text = notes[0].read_text(encoding="utf-8")
    assert "| TOTEN | -27.25 |" in text
    assert "- scf" in text and "- dos" in text


def test_export_invalid_json_returns_error_prefix_and_no_file(clean_test_project):
    bad_rows = export_result_note(clean_test_project, "j", rows_json="{not-json")
    assert bad_rows.startswith("错误：")
    ok_rows_bad_chain = export_result_note(
        clean_test_project, "j",
        rows_json='[["a","b"]]', params_chain_json="[oops",
    )
    assert ok_rows_bad_chain.startswith("错误：")
    # 非法输入不得产生任何落盘文件
    assert not list(Path(OUTPUTS_DIR).glob(f"{clean_test_project}/reports/note_*.md"))


def test_export_wrong_shape_returns_error_prefix():
    # 合法 JSON 但形状不对（对象 / 三元素行）也要报错
    out1 = export_result_note("p", "j", rows_json='{"TOTEN": "-27.25"}')
    assert out1.startswith("错误：")
    out2 = export_result_note("p", "j", rows_json='[["a","b","c"]]')
    assert out2.startswith("错误：")
