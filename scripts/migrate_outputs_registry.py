"""一次性迁移：把测试遗留目录归档，并给真实项目登记 projects.json。

背景（2026-10-20）：server/outputs/ 下 163 个顶层目录里 140 个是测试生成的
`<Formula>_<calc_type>_<ts>` 空壳。测试侧已改为写入临时沙箱（MATCALC_OUTPUTS_DIR），
本脚本负责收拾历史遗留。

动作（幂等，可重复执行）：
1. 匹配 `<Formula>_<relax|static|bands|dos|elastic|aimd|optical>_<时间戳>` 的目录
   → 移到 outputs/_archive_test_runs/legacy_20261020/（不删除）。
2. 其余真实目录登记进 outputs/projects.json（_ 前缀与 pytest_* 自动跳过）。

用法：
    python scripts/migrate_outputs_registry.py [--dry-run]
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from server.matcalc.common import OUTPUTS_DIR, PROJECTS_JSON, _register_project  # noqa: E402

OUT = Path(OUTPUTS_DIR)
ARCHIVE = OUT / "_archive_test_runs" / "legacy_20261020"

# 测试遗留：<Formula>_<calc_type>_<unix ts>
_TEST_DIR = re.compile(r"^[A-Za-z][A-Za-z0-9]*_[a-z]+_\d{9,}$")

# 已知的非项目脚手架（保留原位，但不登记为项目）
_NON_PROJECT = {
    "_archive_test_runs", "_tools", "pytest_tmp",
    "demos", "knowledge", "mp_gallery",
    "smoke_r4", "proj_evt_test", "s8_model_test",
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    entries = sorted(p for p in OUT.iterdir() if p.is_dir())
    leftover = [p for p in entries if _TEST_DIR.match(p.name)]
    rest = [p for p in entries if p not in leftover]

    print(f"顶层目录 {len(entries)} 个：测试遗留 {len(leftover)}，其余 {len(rest)}")

    if leftover:
        print(f"\n归档到 {ARCHIVE.relative_to(OUT)}/：")
        for p in leftover:
            dest = ARCHIVE / p.name
            print(f"  {p.name}")
            if not args.dry_run:
                ARCHIVE.mkdir(parents=True, exist_ok=True)
                if dest.exists():
                    shutil.rmtree(dest, ignore_errors=True)
                shutil.move(str(p), str(dest))

    print("\n登记为项目（写入 projects.json）：")
    for p in rest:
        if p.name in _NON_PROJECT or p.name.startswith(("_", "pytest")):
            print(f"  [跳过] {p.name}")
            continue
        print(f"  {p.name}")
        if not args.dry_run:
            _register_project(p.name)

    print(f"\n登记表：{PROJECTS_JSON}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
