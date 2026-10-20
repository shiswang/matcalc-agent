"""Independent verification of the 024_CuFeMn_V defect energetics.

Checks, straight from the OUTCARs on disk (not from any workflow bookkeeping):
  1. every solid OUTCAR applies the AGREED per-element DFT+U convention
     (Ti 5.2 / Mn 3.9 / Fe 4.0 / Ni 6.2 / V 3.25, Na/N/O none);
  2. the formation energies in the CSV are reproducible from the statics + the
     molecular references;
  3. the per-branch ranking and the spread.

Usage:
    python verify_defect_energies.py [v1|v2]        # default v2

Running it with `v1` is a self-test: the first campaign's defect OUTCARs must be
flagged as deviating (its parent used the agreed values, its defects did not).
"""
from __future__ import annotations
import csv, re, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from campaign_paths import DATA_ROOT as ROOT
CONVENTION = {'Na': 0.0, 'Ti': 5.2, 'Mn': 3.9, 'Fe': 4.0, 'V': 3.25, 'Ni': 6.2, 'N': 0.0, 'O': 0.0}
TOL_U = 0.06          # VASP prints LDAUU with one decimal in OUTCAR (3.25 -> 3.2)
LABELS = ['VMnTi', 'VNiMn', 'VTiNi', 'FeTiNi', 'MnFeNi', 'MnFeTi',
          'MnMnV', 'MnMnFe', 'MnMnMn', 'MnMnNi', 'MnTiNi', 'TiMnMn']
BRANCHES = ['N-O', 'O-van']
SIGMA0 = re.compile(r'energy\(sigma->0\)\s*=\s*([-+\d.Ee]+)')
LABELS_V2 = ['VMnTi', 'VNiMn', 'VTiNi', 'FeTiNi', 'MnFeNi', 'MnFeTi',
             'MnMnV', 'MnMnFe', 'MnMnMn', 'MnMnNi', 'MnTiNi', 'TiMnMn']
V2 = ROOT / 'workflows' / 'v2_u_convention_20261016' / '00_v2'


def u_of(outcar: Path):
    t = outcar.read_text(errors='replace')
    titels = [x.strip() for x in re.findall(r'TITEL\s*=\s*(.+)', t)]
    species = [x.split()[1].split('_')[0] for x in titels if len(x.split()) > 1]
    m = re.findall(r'LDAUU\s*=\s*(.*)$', t, re.M)
    if not m:
        return species, None
    u = [float(x) for x in m[-1].split()]
    return species, (dict(zip(species, u)) if len(u) == len(species) else None)


def deviates(path: Path):
    species, u = u_of(path)
    if u is None:
        return ['<unparsable>']
    return [f'{s}: {u[s]} != {CONVENTION[s]}' for s in species
            if s in CONVENTION and abs(u[s] - CONVENTION[s]) > TOL_U]


def sigma0(path: Path):
    m = SIGMA0.findall(path.read_text(errors='replace'))
    return float(m[-1]) if m else None


def sources(which: str):
    if which == 'v2':
        relax = [(f'{l}_{b}', V2 / 'defect_relax' / 'collected' / f'{l}_{b}') for l in LABELS for b in BRANCHES]
        statics = [(f'{l}_{b}', V2 / 'statics' / 'collected' / f'{l}_{b}') for l in LABELS for b in BRANCHES]
        return {'parent_relax': V2 / 'parent_relax' / 'collected',
                'relax': relax, 'statics': statics,
                'parent_static': V2 / 'statics' / 'collected' / 'parent_static',
                'formation': ROOT / 'defect_formation_comparison_v2' / 'formation_energies.csv'}
    relax = []
    for l in LABELS:
        for b in BRANCHES:
            relax.append((f'{l}_{b}', ROOT / 'result' / 'result' / 'stage2_defects' / l / b))
    statics = []
    for l in LABELS:
        for b in BRANCHES:
            base = (ROOT / 'workflows' / 'bk_unified_returned_20261014' / '00_unified_batch' / 'collected')
            statics.append((f'{l}_{b}', (base / 'static_guarded' / l / b) if (l, b) == ('VMnTi', 'O-van')
                            else (base / 'static' / l / b)))
    return {'parent_relax': ROOT / 'result' / 'result' / '00_parent_relax',
            'relax': relax, 'statics': statics,
            'parent_static': ROOT / 'workflows' / 'oxygen_formation_refs_20261015' / '00_references' / 'collected' / 'parent_static',
            'formation': ROOT / 'defect_formation_comparison' / 'formation_energies.csv'}


def main(which='v2'):
    src = sources(which)
    print(f'=== data source: {which}')
    bad = []
    seen = set()
    for tag, path in [('parent_relax', src['parent_relax'])] + src['relax'] + src['statics'] + \
                     [('parent_static', src['parent_static'])]:
        o = path / 'OUTCAR'
        if not o.exists():
            bad.append(f'{tag}: OUTCAR missing ({o})')
            continue
        if o.resolve() in seen:
            continue
        seen.add(o.resolve())
        d = deviates(o)
        if d:
            bad.append(f'{tag}: ' + '; '.join(d))
    print(f'OUTCARs checked: {len(seen)}')
    if bad:
        print(f'!! {len(bad)} OUTCAR(s) deviate from the agreed +U convention:')
        for b in bad[:30]:
            print('   -', b)
    else:
        print('+U convention: all OUTCARs match (Ti 5.2 / Mn 3.9 / Fe 4.0 / Ni 6.2 / V 3.25)')

    o2 = sigma0(ROOT / 'workflows' / 'oxygen_formation_refs_20261015' / '00_references' / 'collected' / 'O2_static' / 'OUTCAR')
    n2 = sigma0(ROOT / 'workflows' / 'nitrogen_formation_ref_20261015' / '00_reference' / 'collected' / 'N2_static' / 'OUTCAR')
    e_parent = sigma0(src['parent_static'] / 'OUTCAR')
    mu_o, mu_n = o2 / 2.0, n2 / 2.0
    print(f'references: E(O2)={o2:.8f}  E(N2)={n2:.8f}  mu_O={mu_o:.8f}  mu_N={mu_n:.8f}')
    print(f'parent static: {e_parent:.8f} eV')
    recomputed = {}
    for name, path in src['statics']:
        lab, br = name.split('_', 1)
        e = sigma0(path / 'OUTCAR')
        recomputed[(lab, br)] = e - e_parent + mu_o - (mu_n if br == 'N-O' else 0.0)
    csv_path = src['formation']
    if csv_path.exists():
        rows = list(csv.DictReader(csv_path.open(encoding='utf-8-sig')))
        cols = set(rows[0]) if rows else set()
        mism = []
        n_checked = 0
        for r in rows:
            if 'branch' in cols:                       # long format (v2)
                pairs = [(r['site'], r['branch'], float(r['formation_eV']))]
            else:                                      # wide format (v1 comparison table)
                pairs = [(r['site'], 'O-van', float(r['O_vacancy_formation_eV'])),
                         (r['site'], 'N-O', float(r['N_substitution_formation_eV']))]
            for site, br, expect in pairs:
                got = recomputed.get((site, br))
                n_checked += 1
                if got is None or abs(got - expect) > 1e-6:
                    mism.append(((site, br), got, expect))
        print(f'formation energies recomputed from OUTCARs: {n_checked} values, mismatches={len(mism)}')
        for m in mism[:10]:
            print('   -', m)
    print('\nper-branch table (recomputed):')
    for br in BRANCHES:
        vals = sorted(((lab, recomputed[(lab, br)]) for lab in LABELS_V2), key=lambda t: t[1])
        print(f'  {br}: lowest {vals[0][0]} {vals[0][1]:.3f} eV | highest {vals[-1][0]} {vals[-1][1]:.3f} eV '
              f'| spread {vals[-1][1] - vals[0][1]:.3f} eV')
        for lab, v in vals:
            print(f'      {lab:8s} {v:9.3f}')
    return 1 if bad else 0


if __name__ == '__main__':
    which = sys.argv[1] if len(sys.argv) > 1 else 'v2'
    sys.exit(main(which))
