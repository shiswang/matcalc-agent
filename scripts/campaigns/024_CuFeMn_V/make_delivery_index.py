"""生成交付清单：两个数据包的目录结构、校验和与复核方式。

产出（都在数据目录的 package/ 下，不入 git）：
    package/交付清单.md        给接收方看的交付说明
    package/SHA256SUMS.txt     两个 zip 的校验和（sha256sum -c 可验）

用法:
    python make_delivery_index.py
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import zipfile
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from campaign_paths import DATA_ROOT, REPO  # noqa: E402

PKG = DATA_ROOT / 'package'
PACKAGES = [
    ('024_CuFeMn_V_VASP_data.zip', 'V 系列（v2：按约定 +U 重算）'),
    ('024_CuFeMn_Cu_VASP_data.zip', 'Cu 系列（约定 +U，与 v2 同协议）'),
]
# 跨线对照: 不属于任何一个包, 作为独立交付物放在交付目录的 cu_vs_v/ 下
CROSS_LINE = [
    ('cu_vs_v_comparison.csv', 'Cu 与 V 在 8 个共同位点上的逐值对照'),
    ('cu_vs_v_relative.csv', '相对排名与差值'),
    ('cu_vs_v.json', '机器可读的对照载荷'),
]


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def describe(zip_path: Path) -> dict:
    with zipfile.ZipFile(zip_path) as z:
        names = [n for n in z.namelist() if not n.endswith('/')]
        top = sorted({n.split('/')[1] for n in names if n.count('/') >= 1})
        has = lambda pat: any(pat in n for n in names)
        return {
            'entries': len(names),
            'top': top,
            'has_manifest': has('manifest.csv'),
            'has_readme': has('README.md'),
            'has_methods': has('METHODS.md'),
            'has_case': has('case_summary.md'),
            'n_scripts': sum(1 for n in names if '/results/scripts/' in n),
            'n_results': sum(1 for n in names if '/results/' in n and n.endswith(('.json', '.csv', '.md'))),
        }


def main() -> None:
    rows = []
    for name, desc in PACKAGES:
        p = PKG / name
        if not p.exists():
            print('缺少交付包:', p)
            continue
        d = describe(p)
        rows.append({'name': name, 'desc': desc, 'size_mb': p.stat().st_size / 1e6,
                     'sha256': sha256(p), **d})

    # 跨线对照: 从数据目录拷到交付目录的 cu_vs_v/ (独立交付物, 不进任何包)
    cross_dir = PKG / 'cu_vs_v'
    cross_dir.mkdir(exist_ok=True)
    cross_rows = []
    for name, desc in CROSS_LINE:
        src = DATA_ROOT / 'cu' / name
        if not src.exists():
            print('缺少跨线对照文件:', src)
            continue
        dst = cross_dir / name
        shutil.copy2(src, dst)
        cross_rows.append({'name': f'cu_vs_v/{name}', 'desc': desc,
                           'size_mb': dst.stat().st_size / 1e6, 'sha256': sha256(dst)})

    # 跨线汇总: 案例总结 (仓库里的那份), 放在交付层, 不进任何包
    case = REPO / 'docs' / '024_CuFeMn_案例总结.md'
    if case.exists():
        dst = PKG / '案例总结.md'
        shutil.copy2(case, dst)
        cross_rows.append({'name': '案例总结.md', 'desc': '两条线的结论汇总（协议 / 逐位点形成能 / 对照 / 可靠性）',
                           'size_mb': dst.stat().st_size / 1e6, 'sha256': sha256(dst)})

    lines = [
        '# 024_CuFeMn 交付清单',
        '',
        f'> 生成时间：{datetime.now():%Y-%m-%d %H:%M}（由 `scripts/campaigns/024_CuFeMn_V/make_delivery_index.py` 生成）',
        '',
        '本清单对应 **两条线的精简版 VASP 数据包**。包内结构固定为：',
        '',
        '```text',
        '<包名>/',
        '├── README.md            包说明：协议、参考能、形成能表、误差提示',
        '├── METHODS.md           完整计算方法书',
        '├── manifest.csv         每个计算目录：文件数 / 物种 / 原子数 / TOTEN / sigma0',
        '├── relax/parent/        母体结构优化（64 原子，ISIF=3）',
        '├── relax/defects/<位点>/<分支>/   24 个缺陷结构优化（ISIF=3）',
        '├── relax/references/     O2_relax、N2_relax（分子参考态）',
        '├── static/defects/<位点>/<分支>/  24 个统一静态单点（NSW=0, IBRION=-1, ISIF=2）',
        '├── static/references/    parent_static、O2_static、N2_static',
        '└── results/             本线能量数据：形成能 CSV/JSON + 对比图、参考态能量',
        '```',
        '',
        '**每个计算目录只保留 6 个文件**：`INCAR` `KPOINTS` `POSCAR` `CONTCAR` `OUTCAR` `XDATCAR`。',
        '其余（OSZICAR、vasp.out、DOSCAR、PROCAR、EIGENVAL、IBZKPT、REPORT、vasprun.xml、POTCAR、WAVECAR、CHG）一律不入包。',
        '',
        '## 交付物',
        '',
        '| 包 | 内容 | 大小 | 文件数 | 校验和 (sha256) |',
        '|---|---|---:|---:|---|',
    ]
    for r in rows:
        lines.append(f"| `{r['name']}` | {r['desc']} | {r['size_mb']:.1f} MB | {r['entries']} | `{r['sha256']}` |")

    lines += ['', '### 跨线对照（独立交付物，不在任何一个包里）', '',
              '| 文件 | 内容 | 大小 | 校验和 (sha256) |', '|---|---|---:|---|']
    for r in cross_rows:
        lines.append(f"| `{r['name']}` | {r['desc']} | {r['size_mb']*1000:.0f} KB | `{r['sha256']}` |")

    lines += ['', '## 完整性检查', '', '| 包 | README | METHODS | manifest | 案例总结 | results 能量数据文件 |', '|---|---|---|---|---|---:|']
    for r in rows:
        lines.append(
            f"| `{r['name']}` | {'✅' if r['has_readme'] else '❌'} | {'✅' if r['has_methods'] else '❌'} "
            f"| {'✅' if r['has_manifest'] else '❌'} | {'✅' if r['has_case'] else '❌'} | {r['n_results']} |"
        )

    lines += [
        '',
        '## 怎么验（接收方视角）',
        '',
        '```bash',
        '# 1) 校验和',
        'sha256sum -c SHA256SUMS.txt          # 或 PowerShell: Get-FileHash *.zip -Algorithm SHA256',
        '',
        '# 2) 目录结构',
        'unzip -l 024_CuFeMn_V_VASP_data.zip | head -40',
        '',
        '# 3) 形成能自检（不依赖任何外部文件，只看包内 manifest + results）',
        '#    results/formation_energies.csv 与 results/formation_energies.json 必须一致；',
        '#    manifest.csv 里的 sigma0_eV 应与形成能 JSON 用的能量口径一致（energy(sigma->0)）',
        '',
        '# 4) 结论与可靠性判据',
        '#    results/case_summary.md',
        '```',
        '',
        '## 复核脚本（不随包分发）',
        '',
        '产出与复核这些数字的脚本在仓库 `scripts/campaigns/024_CuFeMn_V/`（入 git），'
        '**按原始数据目录布局运行**（需要完整的 workflow 目录树，不是解压后的包）：',
        '',
        '```powershell',
        'cd <repo>\\scripts\\campaigns\\024_CuFeMn_V',
        '..\\..\\..\\.venv\\Scripts\\python.exe cu\\verify_cu_defect_energies.py   # 24 个形成能逐 OUTCAR 复算，零偏差',
        '..\\..\\..\\.venv\\Scripts\\python.exe verify_defect_energies.py v2',
        '```',
        '',
        '## 交付目录里有什么',
        '',
        '这个目录**只放交付物**，整个目录拷走即可：',
        '',
        '| 名字 | 说明 |',
        '|---|---|',
        '| `024_CuFeMn_V_VASP_data.zip` | V 系列数据包 |',
        '| `024_CuFeMn_Cu_VASP_data.zip` | Cu 系列数据包 |',
        '| `交付清单.md` | 本文件 |',
        '| `SHA256SUMS.txt` | 两个 zip 的 sha256 |',
        '| `案例总结.md` | 两条线的结论汇总（跨线文档，**不在任何一个包里**） |',
        '| `cu_vs_v/` | 跨线对照（Cu 与 V 逐位点），**独立交付物，不在任何一个包里** |',
        '',
        '> 打包脚本的解压暂存目录用完即删（不再残留）；历史对照通道 `VCALC_CAMPAIGN=v1`',
        '> 写到 `024_CuFeMn_V_v1_VASP_data.zip`，**不会覆盖交付包**，且不属于交付物。',
        '',
        '## 两包的关系',
        '',
        '- 两条线**协议完全一致**（VASP 6.6.0 / ENCUT 520 / Γ 5×5×1 / 同一套 +U 约定 / 同一套 O2-N2 分子参考），',
        '  所以**形成能可以横向比较**；绝对能量不行（元素不同、+U 组合不同）。',
        '- 结论与逐位点表见 `results/case_summary.md`（两个包里都有同一份）。',
        '- 详细的工程细节与不变量在仓库 `HANDOFF.md` §7；脚本在 `scripts/campaigns/024_CuFeMn_V/`（入 git）。',
        '',
        '> 原始数据（workflows、OUTCAR、结果目录）**不在 git 里**，在 `server/outputs/024_CuFeMn_V/`；',
        '> 本清单与两个 zip 即对外交付物。',
    ]
    (PKG / '交付清单.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')

    sums = ''.join(f"{r['sha256']}  {r['name']}\n" for r in rows)
    sums += ''.join(f"{r['sha256']}  {r['name']}\n" for r in cross_rows)
    (PKG / 'SHA256SUMS.txt').write_text(sums, encoding='utf-8')

    print('交付清单 ->', PKG / '交付清单.md')
    for r in rows:
        print(f"  {r['name']}: {r['size_mb']:.1f} MB, {r['entries']} 条目, "
              f"README={r['has_readme']} METHODS={r['has_methods']} manifest={r['has_manifest']} "
              f"案例总结={r['has_case']} 脚本={r['n_scripts']}")


if __name__ == '__main__':
    main()
