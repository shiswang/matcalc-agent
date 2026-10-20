"""Audit the original Cu-project OUTCARs (from 模拟计算.zip).

Checks, per OUTCAR: species order, applied DFT+U per element, pseudopotential set,
functional/cutoff/D3/smearing/k-point settings, code version, convergence, energies.
Intended U values for this project (as used by the 024_CuFeMn_V recompute):
    Ti 5.2, Mn 6.2, Fe 3.9, Ni 4.0, Cu 1.9 eV
"""
from __future__ import annotations
import csv, json, re, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from campaign_paths import CU_DATA as ROOT
SRC = ROOT / 'cu_original'
TOTEN = re.compile(r'free\s+energy\s+TOTEN\s*=\s*(-?\d+\.\d+)\s*eV')
SIGMA0 = re.compile(r'energy\(sigma->0\)\s*=\s*([-+\d.Ee]+)')
INTENDED_U = {'Ti': 5.2, 'Mn': 6.2, 'Fe': 3.9, 'Ni': 4.0, 'Cu': 1.9}


def _line(text, key):
    """Value text of `key = ...`; VASP prints LDAU* as '... for each species LDAUU = ...'."""
    m = re.findall(key + r'\s*=\s*(.*)$', text, re.M)
    return m[-1].strip() if m else None


def _val(text, key):
    v = _line(text, key)
    if v is None:
        return None
    return v.split()[0]


def audit(path: Path):
    t = path.read_text(errors='replace')
    titels = [x.strip() for x in re.findall(r'TITEL\s*=\s*(.+)', t)]
    species = [x.split()[1].split('_')[0] for x in titels if len(x.split()) > 1]
    variants = [x.split()[1] for x in titels if len(x.split()) > 1]
    ions = re.findall(r'ions per type =\s*([\d ]+)', t)
    counts = [int(x) for x in ions[-1].split()] if ions else []
    u_line = _line(t, 'LDAUU')
    u_vals = [float(x) for x in u_line.split()] if u_line else []
    applied = dict(zip(species, u_vals)) if len(u_vals) == len(species) else {}
    mismatch = {e: (applied.get(e), INTENDED_U[e]) for e in INTENDED_U
                if applied.get(e) is not None and abs(applied[e] - INTENDED_U[e]) > 1e-9}
    tl = TOTEN.findall(t)
    s0 = SIGMA0.findall(t)
    rec = {
        'outcar': str(path.relative_to(SRC)).replace('\\', '/'),
        'atoms': sum(counts), 'counts': counts,
        'species_order': species, 'potcar_variants': variants,
        'LDAUL': _line(t, 'LDAUL'), 'LDAUU': u_line, 'LDAUJ': _line(t, 'LDAUJ'),
        'u_applied_per_element': applied,
        'u_mismatch_vs_intended': {k: f'applied {v[0]} != intended {v[1]}' for k, v in mismatch.items()},
        'toten_eV': float(tl[-1]) if tl else (float(s0[-1]) if s0 else None),
        'sigma0_eV': float(s0[-1]) if s0 else None,
        'ionic_steps': len(re.findall(r'TOTAL-FORCE \(eV/Angst\)', t)),
        'converged_ionic': 'reached required accuracy' in t,
        'scf_ediif_reached': 'aborting loop because EDIFF is reached' in t,
        'normal_end': 'General timing and accounting informations' in t,
        'ENCUT': _val(t, 'ENCUT'), 'ISPIN': _val(t, 'ISPIN'), 'ISMEAR': _val(t, 'ISMEAR'),
        'SIGMA': _val(t, 'SIGMA'), 'IVDW': _val(t, 'IVDW'), 'NKPTS': _val(t, 'NKPTS'),
        'NSW': _val(t, 'NSW'), 'ISIF': _val(t, 'ISIF'), 'IBRION': _val(t, 'IBRION'),
        'EDIFF': _val(t, 'EDIFF'), 'LREAL': _val(t, 'LREAL'), 'LMAXMIX': _val(t, 'LMAXMIX'),
        'LASPH': _val(t, 'LASPH'), 'NCORE': _val(t, 'NCORE'), 'ISYM': _val(t, 'ISYM'),
        'electrons': (re.findall(r'number of electron\s+([\d.]+)', t) or [None])[-1],
        'vasp_version': (re.findall(r'vasp\.(\d+\.\d+\.\d+)', t) or ['?'])[0],
    }
    return rec


def main():
    rows = [audit(p) for p in sorted(SRC.rglob('OUTCAR'))]
    (ROOT / 'cu_results_audit.json').write_text(
        json.dumps({'source_zip': r'E:\Project\024_CuFeMn\模拟计算.zip',
                    'intended_U_eV': INTENDED_U, 'outcars': rows}, indent=2, ensure_ascii=False), encoding='utf-8')
    keys = ['outcar', 'atoms', 'species_order', 'LDAUU', 'u_mismatch_vs_intended', 'toten_eV', 'ionic_steps',
            'converged_ionic', 'normal_end', 'ISMEAR', 'ISPIN', 'ENCUT', 'IVDW', 'NKPTS', 'NSW', 'ISIF',
            'IBRION', 'LREAL', 'NCORE', 'ISYM', 'vasp_version', 'potcar_variants']
    with (ROOT / 'cu_results_audit.csv').open('w', encoding='utf-8-sig', newline='') as f:
        w = csv.DictWriter(f, fieldnames=keys, extrasaction='ignore')
        w.writeheader()
        for r in rows:
            w.writerow({**r, 'species_order': ' '.join(r['species_order']),
                        'u_mismatch_vs_intended': '; '.join(f'{k}:{v}' for k, v in r['u_mismatch_vs_intended'].items()) or '-',
                        'potcar_variants': ' '.join(r['potcar_variants'])})
    print(f"{'outcar':40s} {'atoms':>5s} {'steps':>5s} {'TOTEN':>15s} {'code':>7s}  U applied (Ti/Mn/Fe/Ni/Cu)")
    for r in rows:
        u = r['u_applied_per_element']
        us = ' '.join(f'{e}={u.get(e, "-")}' for e in ['Ti', 'Mn', 'Fe', 'Ni', 'Cu'])
        print(f"{r['outcar']:40s} {r['atoms']:5d} {r['ionic_steps']:5d} {r['toten_eV']:15.8f} {r['vasp_version']:>7s}  {us}")
    bad = [r for r in rows if r['u_mismatch_vs_intended']]
    print(f"\nU 与目标值不一致的 OUTCAR：{len(bad)}/{len(rows)}")
    groups = {}
    for r in bad:
        key = tuple(sorted(r['u_mismatch_vs_intended']))
        groups.setdefault(key, []).append(r['outcar'])
    for k, v in groups.items():
        print(f"  不一致元素 {k}: {len(v)} 个目录，例：{v[0]}")
    print('\nwrote cu_results_audit.json / cu_results_audit.csv')


if __name__ == '__main__':
    main()
