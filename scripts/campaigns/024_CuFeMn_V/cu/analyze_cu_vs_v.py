"""Cu (zip) vs V (this project) relative energies per branch, plus the Cu energy table."""
from __future__ import annotations
import csv, json, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from campaign_paths import CU_DATA as ROOT, DATA_ROOT as V
CU_LABELS = ['CuMnTi', 'CuNiMn', 'CuTiNi', 'FeTiNi', 'MnFeNi', 'MnFeTi', 'MnMnCu', 'MnMnFe', 'MnMnMn', 'MnMnNi', 'MnTiNi', 'TiMnMn']
V_LABELS = ['VMnTi', 'VNiMn', 'VTiNi', 'FeTiNi', 'MnFeNi', 'MnFeTi', 'MnMnV', 'MnMnFe', 'MnMnMn', 'MnMnNi', 'MnTiNi', 'TiMnMn']

audit = json.loads((ROOT / 'cu_results_audit.json').read_text(encoding='utf-8'))['outcars']
old = json.loads((V / 'old_cu_reference.json').read_text(encoding='utf-8'))
vsum = json.loads((V / 'workflows/bk_unified_returned_20261014/00_unified_batch/collection_status.json').read_text(encoding='utf-8'))
vrel = {}
for x in vsum['results']:
    vrel[(x['branch'], x['label'])] = x['energy_eV']

cu = {}
for r in audit:
    parts = r['outcar'].split('/')
    if parts[0] == 'initial_relax':
        cu['parent'] = r
    elif parts[0] == 'N-O-calc':
        cu[('N-O', parts[1])] = r
    elif parts[0] == 'O-van-calc':
        cu[('O-van', parts[2])] = r

rows = []
print('=== Cu 分支内相对能（TOTEN 与旧工作簿逐个核对）===')
for branch in ['N-O', 'O-van']:
    e = {lab: cu[(branch, lab)]['toten_eV'] for lab in CU_LABELS}
    lo = min(e.values())
    for lab in CU_LABELS:
        rows.append({'label': lab, 'branch': branch, 'toten_eV': e[lab], 'old_xlsx_eV': old[branch][lab],
                     'delta_vs_old_eV': e[lab] - old[branch][lab], 'relative_eV': e[lab] - lo,
                     'atoms': cu[(branch, lab)]['atoms'], 'potcar': ' '.join(cu[(branch, lab)]['potcar_variants']),
                     'u_applied': json.dumps(cu[(branch, lab)]['u_applied_per_element'], ensure_ascii=False)})
    print(f'  {branch}: lowest={min(e, key=e.get)}  spread={max(e.values()) - lo:.4f} eV  '
          f'max|delta vs xlsx|={max(abs(v - old[branch][k]) for k, v in e.items()):.2e}')

with (ROOT / 'cu_energies.csv').open('w', encoding='utf-8-sig', newline='') as f:
    w = csv.DictWriter(f, fieldnames=list(rows[0]))
    w.writeheader()
    w.writerows(rows)

print('\n=== Cu vs V：同分支相对能对照（越低越稳）===')
print(f"  {'Cu 标签':9s} {'V 标签':9s} | {'Cu N-O':>8s} {'V N-O':>8s} | {'Cu O-van':>9s} {'V O-van':>9s}")
comp = []
for cl, vl in zip(CU_LABELS, V_LABELS):
    cu_n = cu[('N-O', cl)]['toten_eV']
    cu_o = cu[('O-van', cl)]['toten_eV']
    e_n = min(cu[('N-O', x)]['toten_eV'] for x in CU_LABELS)
    e_o = min(cu[('O-van', x)]['toten_eV'] for x in CU_LABELS)
    vn = vrel[('N-O', vl)]
    vo = vrel[('O-van', vl)]
    vnmin = min(vrel[('N-O', x)] for x in V_LABELS)
    vomin = min(vrel[('O-van', x)] for x in V_LABELS)
    comp.append({'cu_label': cl, 'v_label': vl,
                 'cu_N-O_relative_eV': cu_n - e_n, 'v_N-O_relative_eV': vn - vnmin,
                 'cu_O-van_relative_eV': cu_o - e_o, 'v_O-van_relative_eV': vo - vomin})
    print(f"  {cl:9s} {vl:9s} | {cu_n - e_n:8.4f} {vn - vnmin:8.4f} | {cu_o - e_o:9.4f} {vo - vomin:9.4f}")

with (ROOT / 'cu_vs_v_relative.csv').open('w', encoding='utf-8-sig', newline='') as f:
    w = csv.DictWriter(f, fieldnames=list(comp[0]))
    w.writeheader()
    w.writerows(comp)

import numpy as np
for br, key in [('N-O', 'N-O'), ('O-van', 'O-van')]:
    a = np.array([c[f'cu_{key}_relative_eV'] for c in comp])
    b = np.array([c[f'v_{key}_relative_eV'] for c in comp])
    ra, rb = np.argsort(np.argsort(a)), np.argsort(np.argsort(b))
    print(f'  {br}：Cu 最稳 {CU_LABELS[int(np.argmin(a))]} / V 最稳 {V_LABELS[int(np.argmin(b))]}；'
          f'秩相关 = {np.corrcoef(ra, rb)[0, 1]:+.3f}')

json.dump({'cu_relative': rows, 'cu_vs_v': comp,
           'warnings': ['Cu 全部 25 个 OUTCAR 的 LDAUU 与物种序错配（母体 Mn/Fe/Ni 错位，24 个缺陷 Cu/Ni 互换），'
                        '母体与缺陷不在同一有效 U 组下，绝对能量差不可用；',
                        'Cu O-van 分支用 Fe_sv/Cu/Ni 势，与母体及 N-O 分支的 *_pv 势不同；',
                        'Cu 缺陷均为静态单点（1 个离子步），未弛豫；V 系列为 ISIF=3 弛豫 + 统一静态。']},
          (ROOT / 'cu_vs_v.json').open('w', encoding='utf-8'), indent=2, ensure_ascii=False)
print('\nwrote cu_energies.csv / cu_vs_v_relative.csv / cu_vs_v.json')
