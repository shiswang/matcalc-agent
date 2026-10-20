"""通用件：输出目录约定 / 本地命令执行 / LF 规范化。

从 main.py 抽出的跨模块公共函数（R1）。原 main.py 中的同名副本
将在后续阶段（各消费方迁移完成后的 R4）删除。
"""
from __future__ import annotations

import json
import os
import subprocess
import time
from typing import Optional

# ---------- 输出目录约定 ----------

# outputs 根目录：server/outputs（与 main.py 保持同一落位规则）。
# 测试可用 MATCALC_OUTPUTS_DIR 指向沙箱，避免污染真实项目目录。
OUTPUTS_DIR = os.environ.get("MATCALC_OUTPUTS_DIR") or os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "outputs"
)

# 项目登记表：outputs/projects.json。只是索引，不是真相——真相仍是各项目自己的目录与 state.json。
PROJECTS_JSON = os.path.join(OUTPUTS_DIR, "projects.json")

# 不登记的项目名：下划线开头（内部/沙箱）、pytest_* 测试专用
_NON_PROJECT_PREFIX = ("_", "pytest")


def _register_project(name: str) -> None:
    """把项目名登记进 outputs/projects.json（幂等）。

    只记录"出现过"与最后使用时间，不参与任何校验或清理；
    下划线开头 / pytest_* 视为内部目录，不登记。
    """
    if not name or name.startswith(_NON_PROJECT_PREFIX):
        return
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    data: dict = {}
    if os.path.isfile(PROJECTS_JSON):
        try:
            with open(PROJECTS_JSON, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            data = {}
    projects = data.setdefault("projects", {})
    entry = projects.get(name)
    if entry is None:
        projects[name] = {"created": now, "last_used": now}
    else:
        entry["last_used"] = now
    try:
        os.makedirs(OUTPUTS_DIR, exist_ok=True)
        with open(PROJECTS_JSON, "w", encoding="utf-8", newline="\n") as f:
            json.dump(data, f, ensure_ascii=False, indent=2, sort_keys=True)
            f.write("\n")
    except OSError:  # 登记失败不该阻断计算
        pass


def list_projects() -> str:
    """列出已登记项目（文本表格），用于人工查看/排障。"""
    if not os.path.isfile(PROJECTS_JSON):
        return "（尚无登记；outputs/projects.json 不存在）"
    try:
        with open(PROJECTS_JSON, encoding="utf-8") as f:
            projects = json.load(f).get("projects", {})
    except (OSError, ValueError) as e:
        return f"错误：[E_IO] 读取 projects.json 失败（{e}）"
    if not projects:
        return "（projects.json 为空）"
    rows = ["项目\t创建\t最后使用"]
    for name in sorted(projects):
        e = projects[name]
        rows.append(f"{name}\t{e.get('created', '')}\t{e.get('last_used', '')}")
    return "\n".join(rows)

_KIND_DIRS = {
    "structure": "structures",   # 建模/可视化
    "input": "inputs",           # 计算输入集
    "dos": "dos_pdos",           # DOS/PDOS 图与数据
    "result": "results",         # 解析产物（能带图等）
    "report": "reports",         # 报告
}


def out_dir(project: Optional[str] = None, kind: Optional[str] = None) -> str:
    """输出目录：outputs/[<project>/][<kind>/]，自动创建。project 为空时保持根目录散放（兼容旧行为）。

    首次为一个项目创建目录时，顺手登记到 outputs/projects.json（只登记，不做校验）。
    """
    base = OUTPUTS_DIR
    if project:
        name = project.strip("/\\")
        pdir = os.path.join(base, name)
        if not os.path.isdir(pdir):
            _register_project(name)
        base = pdir
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
