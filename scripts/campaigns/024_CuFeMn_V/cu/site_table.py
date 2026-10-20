"""Site table for the Cu campaign: which O, which three TM neighbours, how far from Cu.

Uses the v2 (agreed +U) relaxed Cu parent geometry so the distances match the
structures the defect runs actually started from.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import run_cu_campaign as c
from pymatgen.core import Structure

cont = c.D / 'parent_relax' / 'collected' / 'CONTCAR'
s = Structure.from_file(str(cont))
print('parent:', s.composition.formula, '| n_sites', len(s), '| volume %.3f' % s.volume)
cu_idx = [i for i, site in enumerate(s) if site.species_string == 'Cu']
print('Cu index (0-based):', cu_idx)
cu = s[cu_idx[0]]

rows = []
for lab, (oidx, metals) in c.LABEL_SITES.items():
    o = s[oidx]
    assert o.species_string == 'O', (lab, oidx, o.species_string)
    # three nearest transition metals around this O
    neigh = sorted(((s[j].specie.symbol, s.get_distance(oidx, j), j)
                    for j in range(len(s))
                    if s[j].specie.symbol in ('Ti', 'Mn', 'Fe', 'Cu', 'Ni')),
                   key=lambda t: t[1])[:3]
    names = sorted(n for n, _, _ in neigh)
    d_cu = s.get_distance(oidx, cu_idx[0])
    rows.append((lab, oidx, ' '.join(f'{n} {d:.3f}' for n, d, _ in neigh), d_cu, o.frac_coords[2],
                 names == sorted(metals)))
print()
print(f"{'label':8s} {'O idx':>5s}  {'neighbours (Å)':42s} {'d(Cu)':>7s} {'c':>6s}  match")
for lab, oidx, nb, d_cu, cz, ok in rows:
    print(f'{lab:8s} {oidx:5d}  {nb:42s} {d_cu:7.3f} {cz:6.3f}  {ok}')
