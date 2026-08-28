"""导入模式回归：脚本直跑（python server/main.py）与包导入必须双通。

背景（账本 37）：jobs.py 的脚本回退分支曾写成顶层名 `from clusters import`，
而 clusters 实住在 matcalc 包内——脚本模式下 matcalc 是顶层包时 `..` 相对
导入越界，回退又找不到顶层 clusters，导致 main.py 脚本直跑必炸。
此处用真实子进程复现文档化启动方式，防止回归。
"""
import os
import re
import subprocess
import sys

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SERVER = os.path.join(ROOT, "server")


def _run_script_mode(code: str, tmp_path) -> tuple[int, str]:
    out = tmp_path / "boot_out.txt"
    with open(out, "wb") as f:
        r = subprocess.run(
            [sys.executable, "-c", code],
            cwd=ROOT, stdout=f, stderr=subprocess.STDOUT, timeout=180,
        )
    return r.returncode, out.read_text(encoding="utf-8", errors="replace")


def test_script_mode_boot_registers_full_toolset(tmp_path):
    """python -c（等价 python server/main.py 的 sys.path 布局）→ 49 工具全注册。"""
    from tests.test_registry import EXPECTED_TOOLS  # noqa: PLC0415
    code = (
        "import sys, os, asyncio\n"
        "sys.path.insert(0, os.path.abspath('server'))\n"
        "import main as m\n"
        f"tools = asyncio.run(m.mcp.list_tools())\n"
        f"print('TOOLCOUNT', len(tools))\n"
    )
    rc, out = _run_script_mode(code, tmp_path)
    assert rc == 0, f"脚本模式启动失败:\n{out}"
    assert f"TOOLCOUNT {len(EXPECTED_TOOLS)}" in out


def test_script_mode_jobs_import(tmp_path):
    """脚本模式下 matcalc.jobs 双路径回退分支可用（NODES 来自 matcalc.clusters）。

    注意：CI 用 clusters.example.json 引导（节点仅 example），故不断言具体节点名，
    只验证加载成功且节点表非空——与环境拓扑解耦。
    """
    code = (
        "import sys, os\n"
        "sys.path.insert(0, os.path.abspath('server'))\n"
        "import matcalc.jobs as j\n"
        "print('JOBS_OK', len(j.NODES))\n"
    )
    rc, out = _run_script_mode(code, tmp_path)
    assert rc == 0, f"jobs 脚本模式导入失败:\n{out}"
    m = re.search(r"JOBS_OK (\d+)", out)
    assert m and int(m.group(1)) >= 1, f"NODES 未加载:\n{out}"
