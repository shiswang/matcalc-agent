"""数据治理：outputs 归类整理与 Markdown/HTML 报告导出。

（R2 自 main.py 原样迁移，函数体未改动）"""

from __future__ import annotations

import glob
import os
import re
import shutil
import time
from typing import Optional

from .common import out_dir as _out_dir, OUTPUTS_DIR as _OUTPUTS_DIR

def export_report(title: str, sections: str, fmt: str = "markdown", project: Optional[str] = None) -> str:
    """将计算结果整理为报告文件并保存到 outputs 目录。

    Args:
        title: 报告标题。
        sections: 报告正文（Markdown 文本；小节以 '## ' 开头组织）。
        fmt: 导出格式 markdown|html（html 会做最小样式包装便于打印成 PDF）。

    Returns:
        保存路径与预览信息。
    """
    stamp = time.strftime("%Y-%m-%d %H:%M")
    header = f"# {title}\n\n> 由 MatCalcAgent 生成 · {stamp}\n\n"
    body = sections if sections.strip().startswith("#") else header + sections
    if fmt.lower() == "html":
        html = (
            "<!DOCTYPE html><html><head><meta charset='utf-8'>"
            "<style>body{font-family:'Segoe UI',sans-serif;max-width:820px;margin:32px auto;"
            "color:#222;line-height:1.65}table{border-collapse:collapse}td,th{border:1px solid #ccc;"
            "padding:6px 10px}code{background:#f4f4f4;padding:2px 5px;border-radius:3px}</style>"
            "</head><body>" + body.replace("\n", "<br>") + "</body></html>"
        )
        path = os.path.join(_out_dir(project, "report"), f"report_{int(time.time())}.html")
        with open(path, "w", encoding="utf-8") as f:
            f.write(html)
    else:
        path = os.path.join(_out_dir(project, "report"), f"report_{int(time.time())}.md")
        with open(path, "w", encoding="utf-8") as f:
            f.write(body)
    return f"报告已保存: {path}\n标题: {title}\n正文长度: {len(body)} 字符"

def organize_outputs(action: str = "report", project: Optional[str] = None, pattern: str = "*") -> str:
    """整理归类 outputs 目录：盘点散落文件或按项目归类移动。

    Args:
        action: "report"=列出根目录散落文件与项目目录统计；
            "tidy"=把根目录匹配 pattern 的文件按类型移动到 outputs/<project>/ 下
            （.vasp/.cif→structures, INCAR/KPOINTS/POTCAR/.pbs/.sh→inputs,
             vasprun/OUTCAR→results, dos/pdos/bands 图与 .txt 数据→dos_pdos, .md 报告→reports）。
        project: tidy 时的目标项目名（如 "NMO_NaBattery"）。
        pattern: tidy 时的文件名通配（如 "NaCl_*"），默认 "*"。

    Returns:
        盘点报告或移动结果清单。
    """
    if action == "report":
        lines = ["== 根目录散落文件 =="]
        loose = [f for f in os.listdir(_OUTPUTS_DIR) if os.path.isfile(os.path.join(_OUTPUTS_DIR, f))]
        for f in sorted(loose):
            sz = os.path.getsize(os.path.join(_OUTPUTS_DIR, f))
            lines.append(f"  {sz / 1e6:8.2f} MB  {f}")
        if not loose:
            lines.append("  (无，根目录干净)")
        lines.append("\n== 项目目录 ==")
        for d in sorted(os.listdir(_OUTPUTS_DIR)):
            p = os.path.join(_OUTPUTS_DIR, d)
            if os.path.isdir(p):
                n_files = sum(len(fs) for _, _, fs in os.walk(p))
                lines.append(f"  {d}/  ({n_files} 文件)")
                for sub in sorted(os.listdir(p)):
                    if os.path.isdir(os.path.join(p, sub)):
                        lines.append(f"      {sub}/")
        return "\n".join(lines)

    if action == "tidy":
        import fnmatch
        import shutil

        if not project:
            return "错误: [E_PARAM] tidy 需要 project 参数（目标项目名）"
        rules = [
            (("INCAR", "KPOINTS", "POTCAR", ".pbs", ".sh"), "inputs"),
            (("vasprun", "OUTCAR", "CHGCAR", "AECCAR"), "results"),
            (("dos", "pdos", "bands"), "dos_pdos"),
            ((".vasp", ".cif"), "structures"),
            ((".md",), "reports"),
        ]

        def _classify(name: str) -> str:
            low = name.lower()
            for keys, kind in rules:
                if any(k.lower() in low or low.endswith(k) for k in keys):
                    return kind
            return ""

        moved, skipped = [], []
        for f in sorted(os.listdir(_OUTPUTS_DIR)):
            src = os.path.join(_OUTPUTS_DIR, f)
            if not os.path.isfile(src) or not fnmatch.fnmatch(f, pattern):
                continue
            kind = _classify(f)
            if not kind:
                skipped.append(f)
                continue
            dst_dir = _out_dir(project, kind)
            dst = os.path.join(dst_dir, f)
            shutil.move(src, dst)
            moved.append(f"{f} → {os.path.relpath(dst, _OUTPUTS_DIR)}")
        msg = [f"已移动 {len(moved)} 个文件到 {project}/:"]
        msg += [f"  {m}" for m in moved] or ["  (无匹配文件)"]
        if skipped:
            msg.append(f"无法识别类型（保留原位）{len(skipped)} 个: {', '.join(skipped[:6])}")
        return "\n".join(msg)

    return f"错误: [E_PARAM] action 仅支持 report|tidy，收到 '{action}'"
