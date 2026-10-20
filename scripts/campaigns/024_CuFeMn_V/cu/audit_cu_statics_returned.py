"""Four-point post-submission check on collected Cu static OUTCARs.

1. rank count (mpirun -np), 2. LDAUL/LDAUU/LDAUJ length + values, 3. POTCAR TITEL order
vs POSCAR species, 4. NKPTS / ISMEAR / ENCUT / IVDW.
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import run_cu_campaign as c

col = c.D / 'statics' / 'collected'
dirs = sorted(p for p in col.glob('*') if (p / 'OUTCAR').exists())
print('collected statics with OUTCAR:', len(dirs))
bad = []
for d in dirs:
    txt = (d / 'OUTCAR').read_text(errors='ignore')
    vout = (d / 'vasp.out').read_text(errors='ignore') if (d / 'vasp.out').exists() else ''
    cores = re.findall(r'running\s+(\d+)\s+mpi-ranks', vout) or re.findall(r'running on\s+(\d+)\s+total cores', txt)
    titels = [x.strip() for x in re.findall(r'TITEL\s*=\s*(.+)', txt)]
    species = [t.split()[1].split('_')[0] for t in titels if len(t.split()) > 1]
    kv = {}
    for k in ('LDAUL', 'LDAUU', 'LDAUJ', 'ISMEAR', 'ENCUT', 'IVDW'):
        m = re.findall(rf'^\s*{k}\s*=\s*([-\d\.\s]+)', txt, re.M)
        if m:
            kv[k] = m[-1].split()
    m = re.findall(r'NKPTS\s*=\s*(\d+)', txt)
    if m:
        kv['NKPTS'] = [m[-1]]
    pos = (d / 'POSCAR').read_text().splitlines()
    order = pos[5].split()
    problems = []
    if not cores:
        problems.append('no rank count in vasp.out/OUTCAR')
    elif cores[-1] != '16':
        problems.append(f'cores={cores[-1]}')
    if species != order:
        problems.append(f'POTCAR order {species} != POSCAR {order}')
    for key in ('LDAUL', 'LDAUU', 'LDAUJ'):
        if len(kv.get(key, [])) != len(order):
            problems.append(f'{key} length {len(kv.get(key, []))} != {len(order)}')
    if not problems:
        for sp, u in zip(order, [float(x) for x in kv['LDAUU']]):
            if abs(u - c.CONVENTION[sp]) > c.TOL_U:
                problems.append(f'U[{sp}]={u} want {c.CONVENTION[sp]}')
    if kv.get('NKPTS', ['0'])[-1] != '13':
        problems.append(f"NKPTS={kv.get('NKPTS')}")
    if abs(float(kv.get('ENCUT', ['0'])[-1]) - 520.0) > 1e-6:
        problems.append(f"ENCUT={kv.get('ENCUT')}")
    if kv.get('IVDW', ['0'])[-1] != '11':
        problems.append(f"IVDW={kv.get('IVDW')}")
    if set(kv.get('ISMEAR', [])) - {'-5'}:
        problems.append(f"ISMEAR={kv.get('ISMEAR')}")
    ism = [x for x in kv.get('ISMEAR', [])]
    print(f'{d.name:16s} cores={cores[-1] if cores else "?"} species={" ".join(species)} '
          f'nkpts={kv.get("NKPTS")} {" OK" if not problems else " FAIL " + str(problems)}')
    if problems:
        bad.append((d.name, problems))
print()
if bad:
    for n, p in bad:
        print('FAIL', n, p)
    sys.exit(1)
print(f'PASS: all {len(dirs)} collected statics match the agreed protocol (16 ranks, U map, POTCAR order, k-mesh)')
