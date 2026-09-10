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


def test_organize_vacuum_dry_run_and_trash(tmp_path, monkeypatch):
    """vacuum 默认 dry_run；dry_run=False 时移入 _vacuum_trash 而非删除。"""
    root = tmp_path / "outputs"
    proj = root / "projA" / "results"
    proj.mkdir(parents=True)
    payload = b"X" * (1_200_000)  # ≥1MB 才进入重复扫描
    # vacuum 保留每组字典序最小路径；命名使 keep < dup
    (proj / "a_keep_vasprun.xml").write_bytes(payload)
    (proj / "b_dup_vasprun.xml").write_bytes(payload)
    (proj / "CHGCAR").write_bytes(b"C" * (51 * 1000 * 1000))  # >50MB 可再生

    monkeypatch.setattr(mc_org, "_OUTPUTS_DIR", str(root))

    dry = mc_org.organize_outputs(action="vacuum", project="projA", dry_run=True)
    assert "DUP" in dry and "REGEN" in dry and "dry_run=True" in dry
    assert (proj / "b_dup_vasprun.xml").is_file()  # dry-run 不移动

    wet = mc_org.organize_outputs(action="vacuum", project="projA", dry_run=False)
    assert "已移入回收目录" in wet
    assert (proj / "a_keep_vasprun.xml").is_file()
    assert not (proj / "b_dup_vasprun.xml").is_file()
    assert not (proj / "CHGCAR").is_file()
    trash_hits = list((root / "_vacuum_trash").rglob("*"))
    assert any(p.is_file() for p in trash_hits)
