"""Compare the applied DFT+U per element: old Cu runs vs the V recompute (OUTCAR evidence)."""
from __future__ import annotations
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from campaign_paths import DATA_ROOT as V


def applied(path: Path):
    t = path.read_text(errors='replace')
    titels = [x.strip() for x in re.findall(r'TITEL\s*=\s*(.+)', t)]
    species = [x.split()[1].split('_')[0] for x in titels if len(x.split()) > 1]
    m = re.findall(r'LDAUU\s*=\s*(.*)$', t, re.M)
    u = [float(x) for x in m[-1].split()] if m else []
    counts = re.findall(r'ions per type =\s*([\d ]+)', t)
    return species, u, (counts[-1].split() if counts else [])


CASES = [
    ('旧 Cu 母体', V / 'cu/cu_original/initial_relax/OUTCAR'),
    ('旧 Cu N-O (CuMnTi)', V / 'cu/cu_original/N-O-calc/CuMnTi/OUTCAR'),
    ('旧 Cu O-van (CuMnTi)', V / 'cu/cu_original/O-van-calc/sturcture/CuMnTi/OUTCAR'),
    ('V 母体弛豫', V / 'result/result/00_parent_relax/OUTCAR'),
    ('V 缺陷弛豫 (MnFeNi/O-van)', V / 'result/result/stage2_defects/MnFeNi/O-van/OUTCAR'),
    ('V 母体静态', V / 'workflows/oxygen_formation_refs_20261015/00_references/collected/parent_static/OUTCAR'),
    ('V 统一静态 (MnFeNi/O-van)', V / 'workflows/bk_unified_returned_20261014/00_unified_batch/collected/static/MnFeNi/O-van/OUTCAR'),
]

for tag, p in CASES:
    if not p.exists():
        print(f'{tag:28s} MISSING {p}')
        continue
    sp, u, counts = applied(p)
    per = dict(zip(sp, u)) if len(sp) == len(u) else {}
    shown = ' '.join(f'{e}={per.get(e, "?")}' for e in ['Ti', 'Mn', 'Fe', 'Ni', 'Cu', 'V'] if e in per)
    print(f'{tag:28s} 物种序={" ".join(sp)}')
    print(f'{"":28s} LDAUU={u}')
    print(f'{"":28s} 每元素: {shown}')
    print()
