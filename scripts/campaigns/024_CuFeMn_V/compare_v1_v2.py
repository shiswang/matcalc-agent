"""Compare the v1 (wrong +U mapping, retracted) and v2 (agreed +U) formation energies.

Usage: python compare_v1_v2.py
Missing campaign data is reported rather than fatal, so it can be run at any stage.
"""
from __future__ import annotations
import csv, json, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from campaign_paths import DATA_ROOT as ROOT
LABELS = ['VMnTi', 'VNiMn', 'VTiNi', 'FeTiNi', 'MnFeNi', 'MnFeTi',
          'MnMnV', 'MnMnFe', 'MnMnMn', 'MnMnNi', 'MnTiNi', 'TiMnMn']
BRANCHES = ['O-van', 'N-O']
U_V1 = {'Ti': 5.2, 'Mn': 6.2, 'Fe': 3.9, 'Ni': 4.0, 'V': 3.25}
U_V2 = {'Ti': 5.2, 'Mn': 3.9, 'Fe': 4.0, 'Ni': 6.2, 'V': 3.25}


def load_v1():
    p = ROOT / 'defect_formation_comparison' / 'formation_energies.json'
    if not p.exists():
        return {}
    conf = json.loads(p.read_text(encoding='utf-8'))
    out = {}
    for r in conf['sites']:
        out[(r['site'], 'O-van')] = r['O_vacancy_formation_eV']
        out[(r['site'], 'N-O')] = r['N_substitution_formation_eV']
    return out


def load_v2():
    p = ROOT / 'defect_formation_comparison_v2' / 'formation_energies.json'
    if not p.exists():
        return {}, {}
    conf = json.loads(p.read_text(encoding='utf-8'))
    out = {(r['site'], r['branch']): r['formation_eV'] for r in conf['sites']}
    return out, conf


def table(name, data, u):
    print(f'\n=== {name} (U: ' + ' / '.join(f'{k} {v}' for k, v in u.items()) + ')')
    for br in BRANCHES:
        rows = [(l, data[(l, br)]) for l in LABELS if (l, br) in data]
        if not rows:
            print(f'  {br}: (no data)')
            continue
        rows.sort(key=lambda t: t[1])
        print(f'  {br}: spread {rows[-1][1] - rows[0][1]:.3f} eV | ' +
              ', '.join(f'{l} {v:.3f}' for l, v in rows))
    return


def main():
    v1, v2 = load_v1(), load_v2()[0]
    table('v1 (RETRACTED: U mapping deviates from the agreed convention)', v1, U_V1)
    table('v2 (agreed convention)', v2, U_V2)
    if not v2:
        print('\nv2 formation energies not available yet (statics not finished)')
        return 0
    print('\n=== per-site comparison (eV)')
    print(f"  {'site':8s} {'v1 O-vac':>9s} {'v2 O-vac':>9s} {'Δ':>7s} | {'v1 N-O':>8s} {'v2 N-O':>8s} {'Δ':>7s}")
    for l in LABELS:
        a, b = v1.get((l, 'O-van')), v2.get((l, 'O-van'))
        c, d = v1.get((l, 'N-O')), v2.get((l, 'N-O'))
        f = lambda x: f'{x:9.3f}' if x is not None else '        -'
        g = lambda x, y: f'{(y - x):7.3f}' if (x is not None and y is not None) else '      -'
        print(f'  {l:8s} {f(a)} {f(b)} {g(a, b)} | {f(c)} {f(d)} {g(c, d)}')
    import numpy as np
    for br in BRANCHES:
        pairs = [(v1[(l, br)], v2[(l, br)]) for l in LABELS if (l, br) in v1 and (l, br) in v2]
        if len(pairs) < 3:
            continue
        x = np.array([p[0] for p in pairs]); y = np.array([p[1] for p in pairs])
        rx, ry = np.argsort(np.argsort(x)), np.argsort(np.argsort(y))
        lo1 = LABELS[min(range(len(LABELS)), key=lambda i: v1.get((LABELS[i], br), 9e9))]
        lo2 = LABELS[min(range(len(LABELS)), key=lambda i: v2.get((LABELS[i], br), 9e9))]
        print(f'  {br}: lowest site v1={lo1} v2={lo2} | rank correlation={np.corrcoef(rx, ry)[0, 1]:+.3f} '
              f'| mean |Δ|={np.abs(y - x).mean():.3f} eV')
    return 0


if __name__ == '__main__':
    sys.exit(main())
