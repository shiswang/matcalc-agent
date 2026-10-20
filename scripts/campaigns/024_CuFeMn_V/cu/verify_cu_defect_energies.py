"""Independent verification of the 024_CuFeMn_Cu defect energetics.

Straight from the OUTCARs on disk (no workflow bookkeeping):
  1. every solid OUTCAR applies the agreed per-element DFT+U convention
     (Ti 5.2 / Mn 3.9 / Fe 4.0 / Ni 6.2 / Cu 1.9, Na/N/O none);
  2. the formation energies in formation_energies.csv are reproducible from the
     statics and the shared molecular references;
  3. the per-branch ranking and spread.

Usage: python verify_cu_defect_energies.py
"""
from __future__ import annotations
import csv, re, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from campaign_paths import CU_DATA as ROOT, DATA_ROOT as VROOT
WF = VROOT / 'workflows' / 'cu_u_convention_20261017' / '00_cu'
CONVENTION = {'Na': 0.0, 'Ti': 5.2, 'Mn': 3.9, 'Fe': 4.0, 'Cu': 1.9, 'Ni': 6.2, 'N': 0.0, 'O': 0.0}
TOL_U = 0.06          # VASP prints LDAUU with one decimal in OUTCAR
LABELS = ['CuMnTi', 'CuNiMn', 'CuTiNi', 'FeTiNi', 'MnFeNi', 'MnFeTi',
          'MnMnCu', 'MnMnFe', 'MnMnMn', 'MnMnNi', 'MnTiNi', 'TiMnMn']
BRANCHES = ['N-O', 'O-van']
SIGMA0 = re.compile(r'energy\(sigma->0\)\s*=\s*([-+\d.Ee]+)')


def species_and_u(outcar: Path):
    t = outcar.read_text(errors='replace')
    titels = [x.strip() for x in re.findall(r'TITEL\s*=\s*(.+)', t)]
    species = [x.split()[1].split('_')[0] for x in titels if len(x.split()) > 1]
    m = re.findall(r'LDAUU\s*=\s*(.*)$', t, re.M)
    if not m:
        return species, None
    u = [float(x) for x in m[-1].split()]
    return species, (dict(zip(species, u)) if len(u) == len(species) else None)


def deviates(path: Path):
    species, u = species_and_u(path)
    if u is None:
        return ['<unparsable LDAUU>']
    return [f'{s}: {u[s]} != {CONVENTION[s]}' for s in species
            if s in CONVENTION and abs(u[s] - CONVENTION[s]) > TOL_U]


def sigma0(path: Path):
    m = SIGMA0.findall(path.read_text(errors='replace'))
    return float(m[-1]) if m else None


def main():
    relax = [(f'{l}_{b}', WF / 'defect_relax' / 'collected' / f'{l}_{b}') for l in LABELS for b in BRANCHES]
    statics = [(f'{l}_{b}', WF / 'statics' / 'collected' / f'{l}_{b}') for l in LABELS for b in BRANCHES]
    targets = ([('parent_relax', WF / 'parent_relax' / 'collected')] + relax + statics
               + [('parent_static', WF / 'statics' / 'collected' / 'parent_static')])
    bad, seen, missing = [], set(), []
    for tag, path in targets:
        o = path / 'OUTCAR'
        if not o.exists():
            missing.append(tag)
            continue
        if o.resolve() in seen:
            continue
        seen.add(o.resolve())
        d = deviates(o)
        if d:
            bad.append(f'{tag}: ' + '; '.join(d))
    print(f'OUTCARs checked: {len(seen)}  (missing: {len(missing)})')
    if missing:
        print('  missing:', missing[:8], '...' if len(missing) > 8 else '')
    if bad:
        print(f'!! {len(bad)} OUTCAR(s) deviate from the agreed +U convention:')
        for b in bad[:30]:
            print('   -', b)
    else:
        print('+U convention: all OUTCARs match (Ti 5.2 / Mn 3.9 / Fe 4.0 / Ni 6.2 / Cu 1.9)')

    o2 = sigma0(VROOT / 'workflows' / 'oxygen_formation_refs_20261015' / '00_references' / 'collected' / 'O2_static' / 'OUTCAR')
    n2 = sigma0(VROOT / 'workflows' / 'nitrogen_formation_ref_20261015' / '00_reference' / 'collected' / 'N2_static' / 'OUTCAR')
    pstat = WF / 'statics' / 'collected' / 'parent_static' / 'OUTCAR'
    e_parent = sigma0(pstat) if pstat.exists() else None
    if e_parent is None:
        print('!! parent static OUTCAR not collected yet; aborting energy check')
        return 1
    mu_o, mu_n = o2 / 2.0, n2 / 2.0
    print(f'references: E(O2)={o2:.8f}  E(N2)={n2:.8f}  mu_O={mu_o:.8f}  mu_N={mu_n:.8f}')
    print(f'parent static: {e_parent:.8f} eV')
    recomputed = {}
    for name, path in statics:
        o = path / 'OUTCAR'
        if not o.exists():
            continue
        lab, br = name.split('_', 1)
        e = sigma0(o)
        recomputed[(lab, br)] = e - e_parent + mu_o - (mu_n if br == 'N-O' else 0.0)

    csv_path = VROOT / 'defect_formation_comparison_cu' / 'formation_energies.csv'
    if csv_path.exists():
        rows = list(csv.DictReader(csv_path.open(encoding='utf-8-sig')))
        mism, n_checked = [], 0
        for r in rows:
            got = recomputed.get((r['site'], r['branch']))
            n_checked += 1
            if got is None or abs(got - float(r['formation_eV'])) > 1e-6:
                mism.append(((r['site'], r['branch']), got, float(r['formation_eV'])))
        print(f'formation energies recomputed from OUTCARs: {n_checked} values, mismatches={len(mism)}')
        for m in mism[:10]:
            print('   -', m)
    else:
        print(f'(no {csv_path.name} yet)')

    print('\nper-branch table (recomputed):')
    for br in BRANCHES:
        vals = sorted(((lab, recomputed[(lab, br)]) for lab in LABELS if (lab, br) in recomputed),
                      key=lambda t: t[1])
        if not vals:
            continue
        print(f'  {br}: lowest {vals[0][0]} {vals[0][1]:.3f} eV | highest {vals[-1][0]} {vals[-1][1]:.3f} eV '
              f'| spread {vals[-1][1] - vals[0][1]:.3f} eV')
        for lab, v in vals:
            print(f'      {lab:8s} {v:9.3f}')
    return 1 if (bad or missing) else 0


if __name__ == '__main__':
    sys.exit(main())
