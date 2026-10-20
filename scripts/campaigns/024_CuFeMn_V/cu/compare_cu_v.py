"""Compare the Cu and V campaigns on the sites they have in common.

Both campaigns were run with the same agreed +U convention, the same PAW potentials,
the same k-mesh and the same neutral-defect formation-energy formulas, so the numbers
are directly comparable.  Eight of the twelve substitutional sites appear in both
campaigns; the remaining four are element-specific (V: MnMnV/VNiMn/VMnTi/VTiNi,
Cu: CuMnTi/CuNiMn/CuTiNi/MnMnCu) and are only listed for information.

Usage: python compare_cu_v.py [--md out.md]
"""
import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from campaign_paths import CU_DATA as HERE, DATA_ROOT as ROOT
CU = ROOT / 'defect_formation_comparison_cu'
V = ROOT / 'defect_formation_comparison_v2'
SHARED = ['FeTiNi', 'MnFeNi', 'MnFeTi', 'MnMnFe', 'MnMnMn', 'MnMnNi', 'MnTiNi', 'TiMnMn']
BRANCHES = ['O-van', 'N-O']


def load(d):
    with (d / 'formation_energies.csv').open(encoding='utf-8-sig') as f:
        rows = list(csv.DictReader(f))
    return {(r['site'], r['branch']): float(r['formation_eV']) for r in rows}


def load_meta(d):
    return json.loads((d / 'formation_energies.json').read_text(encoding='utf-8'))


def main():
    cu, v = load(CU), load(V)
    mcu, mv = load_meta(CU), load_meta(V)
    print(f"Cu parent static : {mcu['parent_static_eV']:.6f} eV")
    print(f"V  parent static : {mv['parent_static_eV']:.6f} eV")
    print(f"mu_O = {mcu['references']['mu_O_eV']:.6f} eV, mu_N = {mcu['references']['mu_N_eV']:.6f} eV (shared)\n")

    out_rows = []
    for br in BRANCHES:
        print(f'== {br} ==')
        print(f"{'site':10s} {'Cu (eV)':>9s} {'V (eV)':>9s} {'Cu-V':>7s} | {'Cu rank':>7s} {'V rank':>7s}")
        cu_sorted = sorted(SHARED, key=lambda s: cu[(s, br)])
        v_sorted = sorted(SHARED, key=lambda s: v[(s, br)])
        for s in cu_sorted:
            d = cu[(s, br)] - v[(s, br)]
            print(f'{s:10s} {cu[(s, br)]:9.3f} {v[(s, br)]:9.3f} {d:+7.3f} | '
                  f'{cu_sorted.index(s) + 1:7d} {v_sorted.index(s) + 1:7d}')
            out_rows.append({'branch': br, 'site': s, 'cu_eV': round(cu[(s, br)], 4),
                             'v_eV': round(v[(s, br)], 4), 'delta_cu_minus_v_eV': round(d, 4),
                             'cu_rank_of_8': cu_sorted.index(s) + 1, 'v_rank_of_8': v_sorted.index(s) + 1})
        # element-specific sites
        extra = sorted({k[0] for k in cu} - set(SHARED)) if br == 'O-van' else []
        if extra:
            print('Cu-only sites:', ', '.join(f'{s} {cu[(s, br)]:.3f}' for s in extra))
            print('V-only sites :', ', '.join(f'{s} {v[(s, br)]:.3f}'
                                              for s in sorted({k[0] for k in v} - set(SHARED))))
        print()

    out = HERE / 'cu_vs_v_comparison.csv'
    with out.open('w', encoding='utf-8-sig', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(out_rows[0]))
        w.writeheader()
        w.writerows(out_rows)
    print('written:', out)

    for br in BRANCHES:
        sub = [r for r in out_rows if r['branch'] == br]
        dc = [r['delta_cu_minus_v_eV'] for r in sub]
        print(f'{br}: mean(Cu-V) = {sum(dc) / len(dc):+.3f} eV, max |Cu-V| = {max(abs(x) for x in dc):.3f} eV')
    if '--md' in sys.argv:
        md = HERE / sys.argv[sys.argv.index('--md') + 1]
        lines = ['# Cu vs V 同约定 +U 结果对比（共同 8 个位点）', '',
                 f"- Cu 母体静态能：{mcu['parent_static_eV']:.6f} eV；V 母体静态能：{mv['parent_static_eV']:.6f} eV",
                 f"- 元素参考（两批共用）：μ_O = {mcu['references']['mu_O_eV']:.6f} eV，"
                 f"μ_N = {mcu['references']['mu_N_eV']:.6f} eV", '']
        for br in BRANCHES:
            lines += [f'## {br}', '', '| 位点 | Cu (eV) | V (eV) | Cu−V (eV) | Cu 排名 | V 排名 |',
                      '|---|---|---|---|---|---|']
            for r in [x for x in out_rows if x['branch'] == br]:
                lines.append(f"| {r['site']} | {r['cu_eV']:.3f} | {r['v_eV']:.3f} | "
                             f"{r['delta_cu_minus_v_eV']:+.3f} | {r['cu_rank_of_8']} | {r['v_rank_of_8']} |")
            lines.append('')
        md.write_text('\n'.join(lines), encoding='utf-8')
        print('markdown written:', md)


if __name__ == '__main__':
    main()
