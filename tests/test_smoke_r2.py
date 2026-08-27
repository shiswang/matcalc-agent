"""R2 迁移冒烟：补齐此前无回归覆盖的工具的直接调用验证。

（原 visualize png/cif 用例随 2026-08-26 可视化功能取消一并删除）
"""
from pathlib import Path

from server.matcalc import organize as mc_org
from server.matcalc.common import OUTPUTS_DIR


def test_export_report_markdown(clean_test_project):
    mc_org.export_report(
        "回归测试报告",
        "## 小节一\n内容 A\n\n## 小节二\n内容 B",
        fmt="markdown",
        project=clean_test_project,
    )
    md = list(Path(OUTPUTS_DIR).glob(f"{clean_test_project}/reports/*.md"))
    assert md, "报告未落盘"
    text = md[0].read_text(encoding="utf-8")
    assert "小节一" in text and "内容 B" in text


def test_organize_report_action_runs():
    """action=report 盘点不移动任何文件，只需正常产出统计文本（内容随环境而异）。"""
    out = mc_org.organize_outputs(action="report")
    assert isinstance(out, str) and "项目目录" in out
