"""通用件：输出目录约定 / 本地命令执行 / LF 规范化。

从 main.py 抽出的跨模块公共函数（R1）。原 main.py 中的同名副本
将在后续阶段（各消费方迁移完成后的 R4）删除。
"""
from __future__ import annotations

import os
import subprocess
from typing import Optional

# ---------- 输出目录约定 ----------

# outputs 根目录：server/outputs（与 main.py 保持同一落位规则）
OUTPUTS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "outputs")

_KIND_DIRS = {
    "structure": "structures",   # 建模/可视化
    "input": "inputs",           # 计算输入集
    "dos": "dos_pdos",           # DOS/PDOS 图与数据
    "result": "results",         # 解析产物（能带图等）
    "report": "reports",         # 报告
}


def out_dir(project: Optional[str] = None, kind: Optional[str] = None) -> str:
    """输出目录：outputs/[<project>/][<kind>/]，自动创建。project 为空时保持根目录散放（兼容旧行为）。"""
    base = OUTPUTS_DIR
    if project:
        base = os.path.join(base, project.strip("/\\"))
        if kind:
            base = os.path.join(base, _KIND_DIRS.get(kind, kind))
    os.makedirs(base, exist_ok=True)
    return base


# 兼容别名：迁移期与历史调用习惯保持一致
_out_dir = out_dir
_OUTPUTS_DIR = OUTPUTS_DIR


# ---------- 本地命令执行 ----------

def run_local(cmd: list, timeout: int = 120) -> tuple[int, str]:
    """本地子进程执行，返回 (returncode, stdout+stderr 合并文本)。"""
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    return r.returncode, (r.stdout or "") + (r.stderr or "")


_run_local = run_local


# ---------- 文本规范化 ----------

def normalize_lf(path: str) -> None:
    """文件内容统一为 LF（Torque/sbatch 拒绝 CRLF；上传远端前的兜底）。"""
    with open(path, "rb") as f:
        data = f.read()
    data = data.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    with open(path, "wb") as f:
        f.write(data)


_normalize_lf = normalize_lf
