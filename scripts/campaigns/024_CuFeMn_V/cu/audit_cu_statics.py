"""Local protocol audit of the prepared Cu static inputs (no cluster access)."""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import run_cu_campaign as c

stage = c.D / 'statics' / 'collected'
dirs = sorted([p for p in stage.iterdir() if p.is_dir()])
print('statics dirs:', len(dirs))
EXPECT = c.CONVENTION
bad = []
for p in dirs:
    inc = (p / 'INCAR').read_text()
    kv = {}
    for line in inc.splitlines():
        line = line.split('#')[0].split('!')[0].strip()
        if '=' in line:
            k, v = line.split('=', 1)
            kv[k.strip().upper()] = v.strip()
    pos = (p / 'POSCAR').read_text().splitlines()
    species = pos[5].split()
    problems = []
    for k, want in [('NSW', '0'), ('IBRION', '-1'), ('ISIF', '2'), ('ISPIN', '2'),
                    ('ENCUT', '520'), ('IVDW', '11'), ('ISMEAR', '-5'),
                    ('ISTART', '0'), ('ICHARG', '2')]:
        if kv.get(k) != want:
            problems.append(f'{k}={kv.get(k)} (want {want})')
    if kv.get('LREAL', '').upper() not in ('F', '.FALSE.', 'FALSE'):
        problems.append(f"LREAL={kv.get('LREAL')} (want F)")
    for k in ('LWAVE', 'LCHARG'):
        if kv.get(k, '').upper() not in ('F', '.FALSE.', 'FALSE'):
            problems.append(f'{k}={kv.get(k)} (want .FALSE.)')
    if kv.get('LDAUTYPE') != '2':
        problems.append(f"LDAUTYPE={kv.get('LDAUTYPE')} (want 2)")
    for key in ('LDAUL', 'LDAUU', 'LDAUJ'):
        vals = kv.get(key, '').split()
        if len(vals) != len(species):
            problems.append(f'{key} length {len(vals)} != species {len(species)}')
    if not problems:
        uu = [float(x) for x in kv['LDAUU'].split()]
        for sp, u in zip(species, uu):
            if abs(u - EXPECT[sp]) > c.TOL_U:
                problems.append(f'U[{sp}]={u} want {EXPECT[sp]}')
    nato = sum(int(x) for x in pos[6].split())
    if nato not in (63, 64):
        problems.append(f'natoms={nato}')
    print(f'{p.name:18s} natoms={nato:3d} species={" ".join(species)} nnodes_ok={not problems}')
    if problems:
        bad.append((p.name, problems))
print()
if bad:
    for n, pr in bad:
        print('FAIL', n, pr)
    sys.exit(1)
print(f'PASS: all {len(dirs)} static inputs conform to the agreed protocol')
