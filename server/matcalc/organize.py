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

def organize_outputs(
    action: str = "report",
    project: Optional[str] = None,
    pattern: str = "*",
    dry_run: bool = True,
) -> str:
    """整理归类 outputs 目录：盘点散落文件、按项目归类移动，或瘦身 vacuum。

    Args:
        action: "report"=列出根目录散落文件与项目目录统计；
            "tidy"=把根目录匹配 pattern 的文件按类型移动到 outputs/<project>/ 下
            （.vasp/.cif→structures, INCAR/KPOINTS/POTCAR/.pbs/.sh→inputs,
             vasprun/OUTCAR→results, dos/pdos/bands 图与 .txt 数据→dos_pdos, .md 报告→reports）；
            "vacuum"=扫描重复大文件与可再生中间产物（默认 dry_run 只报告；
             dry_run=False 时移入 outputs/_vacuum_trash/<stamp>/，不直接删除）。
        project: tidy 的目标项目名；vacuum 可选——只扫该项目，否则扫全部。
        pattern: tidy 时的文件名通配（如 "NaCl_*"），默认 "*"。
        dry_run: vacuum 是否只报告不移动（默认 True）。

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

    if action == "vacuum":
        import hashlib

        # 可再生/可压缩的中间产物（保守：只点名体积大且可重算的）
        regen_prefixes = ("CHGCAR", "WAVECAR", "AECCAR0", "AECCAR1", "AECCAR2")
        scan_root = os.path.join(_OUTPUTS_DIR, project) if project else _OUTPUTS_DIR
        if not os.path.isdir(scan_root):
            return f"错误: [E_PARAM] 路径不存在: {scan_root}"

        files: list[tuple[int, str, str]] = []  # (size, abs, rel)
        for dirpath, _dirnames, filenames in os.walk(scan_root):
            if "_vacuum_trash" in dirpath:
                continue
            for name in filenames:
                ap = os.path.join(dirpath, name)
                try:
                    files.append((os.path.getsize(ap), ap, os.path.relpath(ap, _OUTPUTS_DIR)))
                except OSError:
                    continue
        files.sort(reverse=True)

        def _sha1(path: str, limit: int = 8 * 1024 * 1024) -> str:
            h = hashlib.sha1()
            with open(path, "rb") as f:
                remaining = limit
                while remaining > 0:
                    chunk = f.read(min(1 << 20, remaining))
                    if not chunk:
                        break
                    h.update(chunk)
                    remaining -= len(chunk)
            return h.hexdigest()

        # 1) 同大小+同前缀哈希 → 重复候选（保留路径字典序最小的一份）
        by_sig: dict[tuple[int, str], list[str]] = {}
        for sz, ap, rel in files:
            if sz < 1_000_000:  # 只关心 ≥1MB
                continue
            try:
                sig = (sz, _sha1(ap))
            except OSError:
                continue
            by_sig.setdefault(sig, []).append(rel)
        dups: list[str] = []
        keep_rel: list[str] = []
        for _sig, rels in sorted(by_sig.items(), key=lambda kv: -kv[0][0]):
            if len(rels) < 2:
                continue
            ordered = sorted(rels)
            keep_rel.append(ordered[0])
            dups.extend(ordered[1:])

        # 2) 可再生大文件（>50MB，basename 以前缀命中，兼容 CHGCAR_pure/doped）
        regen: list[str] = []
        for sz, _ap, rel in files:
            base = os.path.basename(rel).upper()
            if sz > 50_000_000 and any(base.startswith(p) for p in regen_prefixes):
                regen.append(rel)

        total_dup = sum(os.path.getsize(os.path.join(_OUTPUTS_DIR, r)) for r in dups)
        total_regen = sum(
            os.path.getsize(os.path.join(_OUTPUTS_DIR, r))
            for r in regen
            if r not in dups  # 已计入重复的不再叠加
        )
        lines = [
            "== vacuum 扫描 ==",
            f"扫描根: {scan_root}",
            f"文件数: {len(files)}  总计 {sum(s for s, _, _ in files) / 1e6:.1f} MB",
            f"\n-- 重复大文件候选（≥1MB，保留每组字典序首份）: {len(dups)} 个 / {total_dup / 1e6:.1f} MB --",
        ]
        for r in dups[:20]:
            lines.append(f"  DUP  {os.path.getsize(os.path.join(_OUTPUTS_DIR, r)) / 1e6:8.1f} MB  {r}")
        if len(dups) > 20:
            lines.append(f"  ... 另 {len(dups) - 20} 个")
        lines.append(f"\n-- 可再生中间产物（>50MB）: {len(regen)} 个 / {total_regen / 1e6:.1f} MB --")
        for r in regen[:20]:
            lines.append(f"  REGEN {os.path.getsize(os.path.join(_OUTPUTS_DIR, r)) / 1e6:8.1f} MB  {r}")

        if dry_run:
            lines.append("\n(dry_run=True，未移动任何文件；dry_run=False 时移入 _vacuum_trash/)")
            lines.append(f"预估可回收 ≈ {(total_dup + total_regen) / 1e6:.1f} MB")
            return "\n".join(lines)

        stamp = time.strftime("%Y%m%d_%H%M%S")
        trash = os.path.join(_OUTPUTS_DIR, "_vacuum_trash", stamp)
        os.makedirs(trash, exist_ok=True)
        moved = []
        for rel in dups + [r for r in regen if r not in dups]:
            src = os.path.join(_OUTPUTS_DIR, rel)
            if not os.path.isfile(src):
                continue
            dst = os.path.join(trash, rel.replace("\\", "__").replace("/", "__"))
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.move(src, dst)
            moved.append(rel)
        lines.append(f"\n已移入回收目录 {trash}：{len(moved)} 个文件")
        lines.append("提示: 确认无误后可手动删除 _vacuum_trash/；未做永久删除。")
        return "\n".join(lines)

    return f"错误: [E_PARAM] action 仅支持 report|tidy|vacuum，收到 '{action}'"
