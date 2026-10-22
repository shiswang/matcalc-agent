"""MatCalcAgent MCP Server（M1 里程碑）。

确定性工具层（Python / pymatgen / ASE）：
- build_structure:      由化学式生成晶体结构（原型建模：rocksalt/perovskite/zincblende/
                        fluorite/bcc/fcc/hcp；或初始粗略结构；可选晶格参数与空间群校验）
- parse_poscar:         解析 POSCAR 文本，返回结构摘要
- visualize_structure:  3D 球棍图渲染（matplotlib，PNG）
- generate_vasp_inputs: VASP 输入文件生成（INCAR 按计算类型 / KPOINTS 自动网格 /
                        POTCAR 拼接脚本 + 元素与参数校验）

运行方式（stdio 传输）：
    .venv\\Scripts\\python.exe server\\main.py
"""

from __future__ import annotations

import math
import os
import time
from typing import Optional

import matplotlib

matplotlib.use("Agg")  # 无 GUI 环境（headless 会话）需要非交互后端
import matplotlib.pyplot as plt  # noqa: E402
from mcp.server.fastmcp import FastMCP
from pymatgen.core import Composition, Element, Structure
from pymatgen.core.lattice import Lattice
from pymatgen.io.vasp import Poscar
from pymatgen.symmetry.groups import SpaceGroup

try:  # 兼容 python server/main.py（脚本）与 from server import main（包）两种运行方式
    from . import remote  # type: ignore[no-redef]
except ImportError:  # pragma: no cover
    import remote  # type: ignore[no-redef]

mcp = FastMCP("matcalc-agent")


# ══════════ M5-R2/R3: 工具实现已迁至 matcalc 包，此处仅组装注册（行为不变） ══════════

try:  # 兼容 python server/main.py（脚本）与 from server import main（包）两种运行方式
    from .matcalc import (
        analysis, analysis_ext, interfaces, lammps, materials_project, monitor, mp_thermo, neb, organize,
        parsing, plotting, structures, suggest, vault_note, vasp_inputs, workflows, xrd,
    )
except ImportError:  # pragma: no cover
    from matcalc import (
        analysis, analysis_ext, interfaces, lammps, materials_project, monitor, mp_thermo, neb, organize,
        parsing, plotting, structures, suggest, vault_note, vasp_inputs, workflows, xrd,
    )

for _fn in (
    *structures.TOOLS,
    *materials_project.TOOLS,
    *mp_thermo.TOOLS,
    parsing.parse_vasp_output, parsing.diagnose_vasp_error,
    parsing.analyze_vasprun, parsing.parse_bader_acf,
    plotting.plot_dos, plotting.plot_pdos, plotting.plot_band,
    analysis.fit_eos,
    organize.organize_outputs, organize.export_report,
    vasp_inputs.generate_vasp_inputs, vasp_inputs.generate_sbatch,
    vasp_inputs.generate_band_inputs, vasp_inputs.generate_dos_inputs,
    vasp_inputs.generate_optical_inputs, vasp_inputs.generate_elastic_inputs,
    vasp_inputs.generate_eos_inputs, vasp_inputs.generate_bader_inputs,
    vasp_inputs.generate_aimd_inputs,
    # S3 扩展：界面建模 / LAMMPS / NEB / 知识片段 / 工作流编排
    *interfaces.TOOLS,
    *lammps.TOOLS,
    *neb.TOOLS,
    *vault_note.TOOLS,
    *workflows.TOOLS,
    # S4 扩展：结构后处理 / U·磁性智能建议 / 任务状态监控
    *analysis_ext.TOOLS,
    *suggest.TOOLS,
    *monitor.TOOLS,
    # S9：XRD 模拟与实验谱对照
    *xrd.TOOLS,
):
    mcp.tool()(_fn)

@mcp.tool()
def configure_remote(
    host: str,
    user: str,
    port: int = 22,
    ssh_key: Optional[str] = None,
    partition: Optional[str] = None,
    modules: Optional[str] = None,
    vasp_cmd: Optional[str] = None,
    remote_workdir: Optional[str] = None,
    node: Optional[str] = None,
) -> str:
    """配置远程 HPC 连接信息（SSH key 认证，不保存任何密码/私钥内容）。

    R4 起 写入目标为项目根 clusters.json（机器字段唯一真源），
    读-改-写回指定节点的连接字段，不触碰 notes 等其余内容。

    Args:
        host: 远程主机（域名或 IP；也可给 "user@ip" 合并形式）。
        user: SSH 用户名。
        port: SSH 端口（默认 22）。
        ssh_key: 私钥路径（如 ~/.ssh/id_ed25519_xxx）；留空用 ssh 默认 key。
        partition: Slurm 分区 / Torque 队列名。
        modules: 模块加载命令（或环境 source 命令），如 "module load apps/vasp/5.4.4"。
        vasp_cmd: VASP 命令，如 "vasp_std" 或完整路径。
        remote_workdir: 远程工作根目录，如 "~/matcalc"。
        node: 目标节点名（master/hzw...）；缺省写 default_node。

    Returns:
        保存后的配置摘要（不含敏感信息）。
    """
    cfg = remote.save_config(
        node=node,
        host=host, user=user, port=port, ssh_key=ssh_key, partition=partition,
        modules=modules, vasp_cmd=vasp_cmd, remote_workdir=remote_workdir,
    )
    masked = {k: ("***" if k in ("password", "key") else v) for k, v in cfg.items()}
    return (
        f"远程配置已写入 clusters.json（机器字段唯一真源，无凭据；节点={cfg.get('node_name')}）。\n"
        f"当前配置视图: {masked}\n"
        "下一步建议调用 check_connection 验证 SSH key 连通性。"
    )


@mcp.tool()
def check_connection() -> str:
    """测试远程 SSH 连接（key 认证）并探测 squeue / vasp_std 可用性。"""
    r = remote.check_connection()
    parts = [
        f"退出码: {r.get('exit')}",
        f"stdout: {r.get('stdout', '').strip() or '(空)'}",
        f"stderr: {r.get('stderr', '').strip() or '(空)'}",
        r.get("note", ""),
    ]
    return "\n".join(parts)


@mcp.tool()
def ssh_run(command: str, remote_dir: Optional[str] = None) -> str:
    """在远程执行白名单命令（安全限制：sbatch/squeue/tail/cat 等）。

    Args:
        command: 远程命令（如 "sbatch run.sh"、"tail -30 OUTCAR"）。
        remote_dir: 可选，远程工作目录（缺省用配置的 remote_workdir）。

    Returns:
        远程执行结果（退出码 / stdout / stderr）。
    """
    r = remote.ssh_run(command, remote_dir)
    return (
        f"远程命令: {command}\n退出码: {r.get('exit')}\n"
        f"stdout:\n{r.get('stdout', '').strip() or '(空)'}\n"
        f"stderr:\n{r.get('stderr', '').strip() or '(空)'}"
    )


@mcp.tool()
def upload(local_path: str, remote_path: Optional[str] = None) -> str:
    """上传本地文件到远程（scp）。

    Args:
        local_path: 本地文件路径（如 server/outputs/NaCl_xxx.vasp）。
        remote_path: 远程目标路径；缺省为 remote_workdir 下同名。

    Returns:
        上传结果。
    """
    r = remote.upload(local_path, remote_path)
    return (
        f"上传 {local_path} → 远程\n退出码: {r.get('exit')}\n"
        f"stdout: {r.get('stdout', '').strip() or '(空)'}\n"
        f"stderr: {r.get('stderr', '').strip() or '(空)'}"
    )


@mcp.tool()
def download(remote_path: str, local_path: Optional[str] = None) -> str:
    """从远程下载文件到本地（scp）。

    Args:
        remote_path: 远程文件路径。
        local_path: 本地保存路径；缺省保存到 outputs 目录。

    Returns:
        下载结果。
    """
    r = remote.download(remote_path, local_path)
    return (
        f"下载 {remote_path} → 本地\n退出码: {r.get('exit')}\n"
        f"stdout: {r.get('stdout', '').strip() or '(空)'}\n"
        f"stderr: {r.get('stderr', '').strip() or '(空)'}"
    )


# ==================== M3：常用性质工作流工具（借鉴 VASPKIT / atomate 功能集） ====================

# ==================== M4: 作业守护 —— 实现落包 matcalc/jobs.py，此处仅薄封装 ====================

try:
    from .matcalc import jobs as _jobs
except ImportError:  # pragma: no cover
    from matcalc import jobs as _jobs

# 兼容别名（test_jobs 等既有调用方沿 main 入口断言）
NODES = _jobs.NODES
LOCAL_POTCAR_LIB = _jobs.LOCAL_POTCAR_LIB


def _ssh_base(node: str) -> list:
    return _jobs.ssh_base(node)


def _scp_base(node: str) -> list:
    return _jobs.scp_base(node)


def _run_local(cmd: list, timeout: int = 120) -> tuple[int, str]:
    return _jobs.run_local(cmd, timeout=timeout)


def _make_run_pbs(node: str, job_name: str, ppn: int) -> str:
    return _jobs.make_run_pbs(node, job_name, ppn)


def _normalize_lf(path: str) -> None:
    return _jobs.normalize_lf(path)


@mcp.tool()
def submit_and_watch(
    project: str,
    local_dir: str,
    node: str = "master",
    ppn: int = 48,
    job_name: Optional[str] = None,
    potcar_elements: Optional[str] = None,
    poll_seconds: int = 120,
    max_polls: int = 3,
) -> str:
    """一键提交 VASP 作业到集群并开始守护：输入校验→POTCAR本地拼接→LF规范→上传→qsub→轮询。

    Args:
        project: 项目名（决定远端与本地归档路径）。
        local_dir: 本地输入目录，需含 INCAR/KPOINTS/POSCAR（POTCAR 可由 potcar_elements 自动拼接）。
        node: 目标节点 "master" 或 "hzw"。
        ppn: 核数（不超过节点上限）。
        job_name: 作业名（缺省用目录名）。
        potcar_elements: 如 "Na_pv,Mn_pv,Ni_pv,O" —— 从本地 potpaw_PBE 库按 POSCAR 元素序拼接。
        poll_seconds: 守护轮询间隔秒。
        max_polls: 本次调用内轮询次数（超时后可稍后再用 check_job 查询）。

    Returns:
        提交结果与作业状态摘要。
    """
    return _jobs.submit_and_watch_impl(
        project, local_dir, node=node, ppn=ppn, job_name=job_name,
        potcar_elements=potcar_elements, poll_seconds=poll_seconds, max_polls=max_polls,
    )


@mcp.tool()
def check_job(job_id: str, node: str = "master", remote_dir: Optional[str] = None) -> str:
    """查询已提交 VASP 作业的状态、最新能量与收敛情况。

    Args:
        job_id: 作业 ID（如 "3687.master"，匹配按数字部分）。
        node: 节点名 master|hzw。
        remote_dir: 远端工作目录（缺省尝试 ~/matcalc 下自动定位失败时必须提供）。

    Returns:
        队列状态 + OSZICAR 尾行 + 收敛标记计数。
    """
    return _jobs.check_job_impl(job_id, node=node, remote_dir=remote_dir)


if __name__ == "__main__":
    mcp.run()
