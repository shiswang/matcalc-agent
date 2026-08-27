"""MCP 注册表完整性 —— 拆包重构的契约测试。

42 个工具名一个不能少、不能多、docstring 描述非空。
（2026-08-26 用户指令移除结构可视化 30->29；S3 集成五模块后 29->42）
R2/R3/集成 每阶段完成后此测试必须保持全绿。
"""
import asyncio

import server.main as mc

EXPECTED_TOOLS = {
    # 建模与结构
    "build_structure", "parse_poscar", "make_supercell", "cleave_surface",
    # 输入生成
    "generate_vasp_inputs", "generate_band_inputs", "generate_dos_inputs",
    "generate_optical_inputs", "generate_elastic_inputs", "generate_eos_inputs",
    "generate_bader_inputs", "generate_sbatch",
    # 解析与诊断
    "parse_vasp_output", "analyze_vasprun", "diagnose_vasp_error", "parse_bader_acf",
    # 绘图与分析
    "plot_dos", "plot_pdos", "plot_band", "fit_eos",
    # 远程与作业守护
    "configure_remote", "check_connection", "ssh_run", "upload", "download",
    "submit_and_watch", "check_job",
    # 数据治理与报告
    "organize_outputs", "export_report",
    # S3：界面建模
    "inspect_interface_match", "build_interface", "stack_slabs",
    # S3：LAMMPS 基础链路
    "build_lammps_data", "generate_lammps_inputs", "parse_lammps_log",
    # S3：NEB 工具集
    "generate_neb_endpoints", "generate_neb_images", "generate_neb_incar",
    # S3：知识沉淀
    "export_result_note",
    # S3：工作流编排
    "start_workflow", "advance_workflow", "workflow_status",
    # S4：结构后处理（键长/配位/对比）
    "analyze_structure", "compare_structures",
    # S4：U 值与磁性智能建议 + 知识回流
    "suggest_u", "suggest_magnetism", "record_feedback",
    # S4：任务状态监控
    "monitor_relax", "monitor_aimd",
}


def _tool_names() -> set[str]:
    tools = asyncio.run(mc.mcp.list_tools())
    return {t.name for t in tools}


def test_registry_exact_tool_set():
    names = _tool_names()
    missing = EXPECTED_TOOLS - names
    extra = names - EXPECTED_TOOLS
    assert not missing, f"缺少工具: {sorted(missing)}"
    assert not extra, f"多出工具: {sorted(extra)}"
    assert len(names) == 49


def test_tools_have_descriptions():
    tools = asyncio.run(mc.mcp.list_tools())
    empty = [t.name for t in tools if not (t.description or "").strip()]
    assert not empty, f"以下工具缺 docstring 描述: {empty}"
