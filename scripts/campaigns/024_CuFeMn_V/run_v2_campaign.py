"""v2 campaign: recompute the 024_CuFeMn_V (Cu -> V) series with the AGREED +U convention.

Agreed convention (user-confirmed 2026-10-15):
    Ti 5.2 / Mn 3.9 / Fe 4.0 / Ni 6.2 / V 3.25 eV ; Na, N, O: no U
The first campaign used Mn 6.2 / Fe 3.9 / Ni 4.0 and is therefore superseded.  Every
stage of this campaign re-checks the per-element U mapping parsed from its own OUTCAR
(species order included), so a mismatched list can never slip through again.

Steps
  0 parent_relax     ISIF=3 relaxation of the 64-atom parent (bkzhang, 32 ranks)
  1 defect_inputs    build the 24 defect cells on the new relaxed parent   [pending]
  2 defect_relax     submit/collect the 24 defect relaxations              [pending]
  3 statics          parent static + 24 unified statics                    [pending]
  4 energies         formation energies, plots, package, docs              [pending]
"""
from __future__ import annotations
import csv, json, os, re, subprocess, tarfile, time
from pathlib import Path
import run_bk_unified as b
from pymatgen.io.vasp.inputs import Incar, Poscar
from pymatgen.core import Structure
from matcalc import workflows as wf

ROOT = b.ROOT
CFG = b.CFG
PROJECT = '024_CuFeMn_V'
WFID = 'v2_u_convention_20261016'
NAME = 'v2'
REMOTE = 'matcalc/024_CuFeMn_V/' + WFID
D = ROOT / 'workflows' / WFID / '00_v2'
SRC = ROOT / 'calc_u_fix'

CONVENTION = {'Na': 0.0, 'Ti': 5.2, 'Mn': 3.9, 'Fe': 4.0, 'V': 3.25, 'Ni': 6.2, 'N': 0.0, 'O': 0.0}
# VASP prints the applied LDAUU with one decimal in OUTCAR (3.25 -> "3.2"), so the
# OUTCAR-based convention check must tolerate that print rounding.
TOL_U = 0.06
POTCAR_DIR = {'Na': 'Na_pv', 'Ti': 'Ti_pv', 'Mn': 'Mn_pv', 'Fe': 'Fe_pv',
              'V': 'V_pv', 'Ni': 'Ni_pv', 'N': 'N', 'O': 'O'}
EXPECTED_MD5 = {'Na_pv': '5c9856f448bf380d5b3733e9f598a718', 'Ti_pv': '4b3e0513e5c0b0c044fb47ed7c80d8f9',
                'Mn_pv': '94a1a1c4f5ec3f936c4cb7d46c6464bb', 'Fe_pv': '924ac02be178cfc7807e8b6c3d514753',
                'V_pv': '08dacebd9b4e1eb69bcbf91bfc24b904', 'Ni_pv': 'ed85c7b882fbcc8747fc2966a66e8584',
                'N': '9d4908b6809ffb7a0762dee7fc571857', 'O': '9d87f5aff44d5d488070cd054a6acf7c'}
PENDING = set()
TOTEN = re.compile(r'free\s+energy\s+TOTEN\s*=\s*(-?\d+\.\d+)\s*eV')
SIGMA0 = re.compile(r'energy\(sigma->0\)\s*=\s*([-+\d.Ee]+)')

SPECIES_ORDER = ['Na', 'Ti', 'Mn', 'Fe', 'V', 'Ni', 'N', 'O']
LABEL_SITES = {
    "VMnTi": (49, ["V", "Mn", "Ti"]), "VNiMn": (51, ["V", "Mn", "Ni"]),
    "VTiNi": (58, ["V", "Ni", "Ti"]), "FeTiNi": (40, ["Fe", "Ni", "Ti"]),
    "MnFeNi": (30, ["Fe", "Mn", "Ni"]), "MnFeTi": (31, ["Fe", "Mn", "Ti"]),
    "MnMnV": (55, ["V", "Mn", "Mn"]), "MnMnFe": (42, ["Fe", "Mn", "Mn"]),
    "MnMnMn": (50, ["Mn", "Mn", "Mn"]), "MnMnNi": (41, ["Mn", "Mn", "Ni"]),
    "MnTiNi": (32, ["Mn", "Ni", "Ti"]), "TiMnMn": (59, ["Mn", "Mn", "Ti"]),
}
BRANCHES = ["N-O", "O-van"]
MAGMOM_N = 0.001
KPOINTS_TEXT = """Gamma-centred 5x5x1 mesh - same k-sampling as the first campaign
0
Gamma
5 5 1
0 0 0
"""
DEFECT_PPN, DEFECT_MEM = 16, '20G'


def poscar_text(structure, title, species_order):
    species, coords = [], []
    for site in structure:
        if site.species_string not in species:
            species.append(site.species_string)
        coords.append(site.frac_coords)
    counts = [sum(1 for s in structure if s.species_string == sym) for sym in species]
    assert species == [s for s in species_order if s in species], (species, species_order)
    lines = [title, "1.0"]
    for vec in structure.lattice.matrix:
        lines.append("  %18.12f %18.12f %18.12f" % tuple(vec))
    lines.append("".join("%6s" % s for s in species))
    lines.append("".join("%6d" % c for c in counts))
    lines.append("Direct")
    for xyz in coords:
        lines.append("  %18.12f %18.12f %18.12f" % tuple(xyz))
    return "\n".join(lines) + "\n"


def _assert_incar_stage(text, stage, where=''):
    """阶段自检：静态必须是真静态，弛豫必须是真弛豫。

    2026-10-20 加：`stage` 参数传错时，静态会带着 NSW=200 跑成第二次弛豫，
    而 U / ENCUT / k 点全部合规，协议检查根本发现不了。
    """
    import re as _re
    want = {'static': {'NSW': '0', 'IBRION': '-1', 'ISIF': '2'},
            'relax': {'NSW': '200', 'IBRION': '2', 'ISIF': '3'}}[stage]
    got = {}
    for k in want:
        m = _re.search(rf'^{k}\s*=\s*(\S+)', text, _re.M)
        if m:
            got[k] = m.group(1)
    bad = {k: got.get(k) for k, v in want.items() if got.get(k) != v}
    if bad:
        raise RuntimeError(f'{where}生成的 {stage} INCAR 阶段不对：期望 {want}，实际 {bad}')
    return text


def defect_incar(magmom, stage, species_order, system=None, comment=None):
    ldaul = " ".join("%d" % (2 if s in ('Ti', 'Mn', 'Fe', 'V', 'Ni') else -1) for s in species_order)
    ldauu = " ".join("%g" % CONVENTION[s] for s in species_order)
    ldauj = " ".join("0.0" for _ in species_order)
    if system is None:
        if "N" in species_order:
            system = "Na10 Ti2 Mn10 Fe1 V1 Ni4 N1 O35"
        elif len(magmom) == 64:
            system = "Na10 Ti2 Mn10 Fe1 V1 Ni4 O36 (parent, Cu -> V)"
        else:
            system = "Na10 Ti2 Mn10 Fe1 V1 Ni4 O35 (O vacancy)"
    if stage == 'relax':
        head, ionic = "relax (ionic + cell, ISIF=3)", "NSW = 200\nIBRION = 2\nISIF = 3\nEDIFFG = -0.02\nPOTIM = 0.5\nISYM = 2"
    else:
        head, ionic = "static single point (NSW=0, ISIF=2)", "NSW = 0\nIBRION = -1\nISIF = 2\nEDIFFG = -0.02\nPOTIM = 0.5\nISYM = 2"
    return _assert_incar_stage(f"""SYSTEM = {system} -- {head}
# Project 024_CuFeMn_V, campaign v2 (agreed +U convention: Ti 5.2 / Mn 3.9 / Fe 4.0 / Ni 6.2 / V 3.25)
{comment or '# STAGE: ' + head}

PREC    = Accurate
ISTART  = 0
ICHARG  = 2
ISPIN   = 2
MAGMOM  = {' '.join('%g' % v for v in magmom)}
NCORE   = 4

ENCUT   = 520
NELM    = 100
NELMIN  = 5
NELMDL  = -8
EDIFF   = 1E-5
LREAL   = .FALSE.
LMAXMIX = 4
LASPH   = .FALSE.

{ionic}

ISMEAR  = -5
SIGMA   = 0.05
LORBIT  = 11

LWAVE   = .FALSE.
LCHARG  = .FALSE.

IVDW    = 11

LDAU     = .TRUE.
LDAUTYPE = 2
LDAUL    = {ldaul}
LDAUU    = {ldauu}
LDAUJ    = {ldauj}
""", stage, f'{system}: ')


def build_defect(parent, moments, site, branch):
    if branch == "N-O":
        kept = list(range(len(parent)))
        new_species = {site: "N"}
    else:
        kept = [i for i in range(len(parent)) if i != site]
        new_species = {}
    recs = []
    for pos, i in enumerate(kept):
        sp = new_species.get(i, parent[i].species_string)
        mom = MAGMOM_N if i in new_species else moments[i]
        recs.append((pos, sp, parent[i].frac_coords, mom))
    rank = {s: k for k, s in enumerate(SPECIES_ORDER)}
    recs.sort(key=lambda r: (rank[r[1]], r[0]))
    species = [r[1] for r in recs]
    order = [s for s in SPECIES_ORDER if s in species]
    st = Structure(parent.lattice, species, [r[2] for r in recs])
    return st, order, [r[3] for r in recs]


def write(p: Path, s: str):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(s, encoding='utf-8', newline='\n')


def u_from_outcar(text: str):
    """{element: applied U} parsed from the OUTCAR's own species order."""
    titels = [x.strip() for x in re.findall(r'TITEL\s*=\s*(.+)', text)]
    species = [x.split()[1].split('_')[0] for x in titels if len(x.split()) > 1]
    m = re.findall(r'LDAUU\s*=\s*(.*)$', text, re.M)
    if not m:
        raise ValueError('no LDAUU line in OUTCAR')
    u = [float(x) for x in m[-1].split()]
    if len(u) != len(species):
        raise ValueError(f'LDAUU length {len(u)} != species {len(species)}')
    return dict(zip(species, u))


def assert_convention(text: str, where: str):
    got = u_from_outcar(text)
    bad = {e: (got.get(e), CONVENTION[e]) for e in CONVENTION
           if e in got and abs(got[e] - CONVENTION[e]) > TOL_U}
    if bad:
        raise AssertionError(f'{where}: per-element U deviates from the agreed convention: {bad}')
    return got


def job_pbs(jobname: str, ppn: int, mem: str, wall: str = '48:00:00') -> str:
    return f'''#!/bin/bash
#SBATCH -J {jobname}
#SBATCH -p {CFG['queue']}
#SBATCH -A {CFG['account']}
#SBATCH -N 1
#SBATCH -n {ppn}
#SBATCH --mem={mem}
#SBATCH --time={wall}
#SBATCH -o scheduler-%j.out
#SBATCH -e scheduler-%j.err
set -eo pipefail
cd "$SLURM_SUBMIT_DIR"
{CFG['vasp_setup']}
export OMP_NUM_THREADS=1
export MKL_NUM_THREADS=1
mpirun -np "$SLURM_NTASKS" {CFG['vasp_exe']} > vasp.out 2>&1
'''


def parent_incar(magmom, order):
    ldaul = " ".join("%d" % (2 if s in ('Ti', 'Mn', 'Fe', 'V', 'Ni') else -1) for s in order)
    ldauu = " ".join("%g" % CONVENTION[s] for s in order)
    ldauj = " ".join("0.0" for _ in order)
    return _assert_incar_stage(f"""SYSTEM = Na10 Ti2 Mn10 Fe1 V1 Ni4 O36 (parent, Cu -> V) -- relax (ionic + cell, ISIF=3)
# Project 024_CuFeMn_V, campaign v2 (agreed +U convention: Ti 5.2 / Mn 3.9 / Fe 4.0 / Ni 6.2 / V 3.25)
# Start structure: CONTCAR of the first campaign's parent relaxation.
# MAGMOM: final projected moments of that relaxation (same site order as the CONTCAR).

PREC    = Accurate
ISTART  = 0
ICHARG  = 2
ISPIN   = 2
MAGMOM  = {' '.join('%g' % v for v in magmom)}
NCORE   = 4

ENCUT   = 520
NELM    = 100
NELMIN  = 5
NELMDL  = -8
EDIFF   = 1E-5
LREAL   = .FALSE.
LMAXMIX = 4
LASPH   = .FALSE.

NSW     = 200
IBRION  = 2
ISIF    = 3
EDIFFG  = -0.02
POTIM   = 0.5
ISYM    = 2

ISMEAR  = -5
SIGMA   = 0.05
LORBIT  = 11

LWAVE   = .FALSE.
LCHARG  = .FALSE.

IVDW    = 11

LDAU     = .TRUE.
LDAUTYPE = 2
LDAUL    = {ldaul}
LDAUU    = {ldauu}
LDAUJ    = {ldauj}
""", 'relax', 'parent: ')


# --------------------------------------------------------------------------- step 0
def parent_relax(state, step):
    d = D / 'parent_relax'
    src = SRC / '00_parent_relax'
    prev = ROOT / 'result' / 'result' / '00_parent_relax'
    if step['status'] == 'pending':
        # start from the already relaxed parent geometry (CONTCAR), not the raw POSCAR
        contcar = prev / 'CONTCAR'
        assert contcar.exists(), contcar
        struct = Poscar.from_file(str(contcar), check_for_potcar=False).structure
        order = Poscar.from_file(str(contcar), check_for_potcar=False).site_symbols
        assert order == ['Na', 'Ti', 'Ni', 'Mn', 'Fe', 'V', 'O'], order
        assert len(struct) == 64
        moments = b.moments(prev / 'OUTCAR', len(struct))       # same site order as the CONTCAR
        title = ' '.join(contcar.read_text(errors='replace').splitlines()[0].split()[:8]) or 'parent'
        write(d / 'POSCAR', poscar_text(struct, 'Na10 Ti2 Mn10 Fe1 V1 Ni4 O36 parent (Cu->V) -- v2 start from CONTCAR', order))
        write(d / 'INCAR', parent_incar(moments, order))
        write(d / 'KPOINTS', (src / 'KPOINTS').read_text())
        write(d / 'job.pbs', job_pbs('V2_parent_relax', 32, '32G'))
        write(d / 'manifest.json', json.dumps(
            {'stage': 'parent_relax',
             'start_structure': 'result/result/00_parent_relax/CONTCAR (first campaign parent relaxation)',
             'start_toten_eV': float(TOTEN.findall((prev / 'OUTCAR').read_text(errors='replace'))[-1]),
             'species': order, 'atoms': len(struct),
             'u_applied': {s: CONVENTION[s] for s in order},
             'magmom_source': 'final projected moments of the first campaign parent relaxation',
             'protocol': 'ISIF=3, NSW=200, IBRION=2, EDIFFG=-0.02, ISMEAR=-5, NKPTS=13, LWAVE=LCHARG=.FALSE.'}, indent=2))
        step['status'] = 'waiting_submit'
        step['note'] = f'parent relax prepared from CONTCAR; U per element = {dict((s, CONVENTION[s]) for s in order)}'
        return step['note']

    if not step.get('submitted_job'):
        with tarfile.open(d / 'inputs.tar.gz', 'w:gz') as tf:
            for n in ['POSCAR', 'INCAR', 'KPOINTS', 'job.pbs']:
                tf.add(d / n, arcname=f'parent_relax/{n}')
        b.remote(f'mkdir -p "$HOME/{REMOTE}"\nrm -f "$HOME/_xdatcar_pack.tar.gz" "$HOME/xdatcar_wanted.txt"\n', d / 'mkdir.log')
        with (d / 'upload.log').open('wb') as f:
            r = subprocess.run([b.SCP, '-o', 'BatchMode=yes', '-i', CFG['ssh_key'], str(d / 'inputs.tar.gz'),
                                CFG['host'] + ':' + REMOTE + '/inputs.tar.gz'], stdout=f, stderr=subprocess.STDOUT)
        if r.returncode:
            raise RuntimeError('upload failed; see upload.log')
        pots = ' '.join(f'"$LIB/{POTCAR_DIR[s]}/POTCAR"' for s in ['Na', 'Ti', 'Ni', 'Mn', 'Fe', 'V', 'O'])
        md5 = '\n'.join(f'[ "$(md5sum "$LIB/{k}/POTCAR" | cut -d " " -f1)" = {v} ]' for k, v in EXPECTED_MD5.items())
        script = f'''set -euo pipefail
cd "$HOME/{REMOTE}"
if [ -f submitted.tsv ]; then cat submitted.tsv; exit 0; fi
tar -xzmf inputs.tar.gz
LIB={CFG['local_potcar_lib']}
{md5}
cd parent_relax
cat {pots} > POTCAR
[ "$(grep -c TITEL POTCAR)" -eq 7 ]
J=$(sbatch --parsable job.pbs); J=${{J%%;*}}
[[ "$J" =~ ^[0-9]+$ ]]
printf 'parent_relax\\t%s\\n' "$J" > ../submitted.tsv
cat ../submitted.tsv
'''
        out = b.remote(script, d / 'submit.log')
        ids = re.findall(r'parent_relax\t(\d+)', out)
        assert ids, f'no job id parsed; see submit.log\n{out}'
        step['submitted_job'] = ids[-1]
        step['key_results'] = {'job_id': ids[-1], 'remote_path': REMOTE}
        step['status'] = 'waiting_run'
        step['note'] = f'parent relaxation submitted as job {ids[-1]} (32 ranks, --mem=32G)'
        return step['note']

    job = step['submitted_job']
    out = b.remote(f'sacct -X -n -P -j {job} --format=JobIDRaw,State,ExitCode\n', d / 'accounting.log')
    status = out.strip().split('|')
    if len(status) < 3 or status[1] not in ('COMPLETED',):
        step['note'] = f'parent relaxation {job}: {out.strip() or "no record yet"}'
        return step['note']
    if status[2] != '0:0':
        raise RuntimeError(f'parent relaxation {job} exited with {status[2]}')

    dest = d / 'collected'
    dest.mkdir(parents=True, exist_ok=True)
    for fn in ['OUTCAR', 'CONTCAR', 'OSZICAR', 'XDATCAR', 'vasp.out', 'INCAR', 'POSCAR', 'KPOINTS']:
        with (d / 'download.log').open('ab') as f:
            r = subprocess.run([b.SCP, '-o', 'BatchMode=yes', '-i', CFG['ssh_key'],
                                CFG['host'] + f':{REMOTE}/parent_relax/{fn}', str(dest / fn)],
                               stdout=f, stderr=subprocess.STDOUT)
        if r.returncode:
            raise RuntimeError('download failed for ' + fn)
    t = (dest / 'OUTCAR').read_text(errors='replace')
    checks = {
        'ionic_converged': 'reached required accuracy' in t,
        'electronic_converged': 'aborting loop because EDIFF is reached' in t,
        'normal_end': 'General timing and accounting informations' in t,
        'NKPTS_13': bool(re.search(r'NKPTS\s*=\s*13\b', t)),
        'ENCUT_520': bool(re.search(r'ENCUT\s*=\s*520', t)),
        'ISPIN_2': bool(re.search(r'ISPIN\s*=\s*2', t)),
        'IVDW_11': bool(re.search(r'IVDW\s*=\s*11', t)),
    }
    u = assert_convention(t, 'parent OUTCAR')
    toten = TOTEN.findall(t)
    e0 = float(toten[-1]) if toten else None
    moments = b.moments(dest / 'OUTCAR', 64)
    write(d / 'parent_moments_v2.txt', ' '.join('%g' % m for m in moments))
    write(d / 'relaxed_parent_CONTCAR_v2', (dest / 'CONTCAR').read_text())
    step['key_results'].update({'job_id': job, 'checks': checks, 'u_applied': u,
                                'E0_eV': e0, 'ionic_steps': len(re.findall(r'TOTAL-FORCE \(eV/Angst\)', t)),
                                'moments_file': str((d / 'parent_moments_v2.txt').relative_to(ROOT)),
                                'contcar_file': str((d / 'relaxed_parent_CONTCAR_v2').relative_to(ROOT))})
    if not all(checks.values()):
        step['note'] = f'parent relaxation finished but checks failed: {checks}'
        return step['note']
    step['status'] = 'done'
    step['note'] = f'parent relaxation converged: E0={e0:.8f} eV, U convention verified'
    return step['note']


def pending(state, step):
    step['note'] = f'[{step["name"]}] handler not implemented yet; campaign is still on the parent relaxation'
    return step['note']


def defect_inputs(state, step):
    """Prepare the 24 defect relaxations.

    Start geometry: the FIRST campaign's relaxed defect CONTCAR (a plain restart with the
    corrected U - the converged result is still the v2 minimum of the same basin).  This
    is ~10x cheaper than rebuilding the cells on the new parent: the v1 relaxations took
    570-704 s per ionic step and 24-200 steps each.  If a v1 CONTCAR is missing, the cell
    is rebuilt on the v2 parent CONTCAR instead (fallback, recorded in the manifest).
    """
    d = D / 'defect_inputs'
    if step['status'] != 'pending':
        return step['note']
    parent_path = D / 'parent_relax' / 'relaxed_parent_CONTCAR_v2'
    moments_path = D / 'parent_relax' / 'parent_moments_v2.txt'
    assert parent_path.exists() and moments_path.exists(), 'parent relaxation outputs missing'
    v1_root = ROOT / 'result' / 'result' / 'stage2_defects'
    resume_root = ROOT / 'workflows' / 'bk_unified_returned_20261014' / '00_unified_batch' / 'collected' / 'resume'
    parent = Structure.from_file(str(parent_path))
    parent_order = Poscar.from_file(str(parent_path), check_for_potcar=False).site_symbols
    parent_moments = [float(x) for x in moments_path.read_text().split()]
    entries = []
    for lab, (site, want_tm) in LABEL_SITES.items():
        for br in BRANCHES:
            name = f'{lab}_{br}'
            target = d / name
            # prefer the most-relaxed v1 geometry available for this defect:
            #   resume/<l>/<b>  (v1 continuation that reached EDIFFG, if any)
            #   stage2_defects/<l>/<b>  (v1 relaxation)
            #   else rebuild on the v2 parent CONTCAR
            cands = [(resume_root / lab / br, 'v1-resume-contcar-restart'),
                     (v1_root / lab / br, 'v1-contcar-restart')]
            start_dir = start_mode = None
            for cand, mode in cands:
                if (cand / 'CONTCAR').exists() and (cand / 'OUTCAR').exists():
                    start_dir, start_mode = cand, mode
                    break
            if start_dir is not None:
                start_txt = (start_dir / 'CONTCAR').read_text()
                st = Poscar.from_str(start_txt).structure
                order = Poscar.from_str(start_txt).site_symbols
                moments = b.moments(start_dir / 'OUTCAR', len(st))
                start_src = start_dir.relative_to(ROOT).as_posix() + '/CONTCAR'
                start_converged = 'reached required accuracy' in (start_dir / 'OUTCAR').read_text(errors='replace')
            else:
                start_mode = 'rebuilt-on-v2-parent'
                assert parent[site].species_string == 'O', (lab, parent[site].species_string)
                st, order, moments = build_defect(parent, parent_moments, site, br)
                start_src = f'workflows/{WFID}/00_v2/parent_relax/relaxed_parent_CONTCAR_v2'
                start_converged = None
            # ---- guards
            expect = ['Na', 'Ti', 'Mn', 'Fe', 'V', 'Ni'] + (['N'] if br == 'N-O' else []) + ['O']
            assert order == expect, (name, order, expect)
            assert len(st) == (64 if br == 'N-O' else 63), (name, len(st))
            if br == 'O-van':
                gap = float(min(st.lattice.get_all_distances([parent[site].frac_coords],
                                                             [s.frac_coords for s in st])[0]))
                assert gap > 1.0, (name, gap)
            else:
                n_idx = [i for i, s in enumerate(st) if s.species_string == 'N'][0]
                shell = sorted(x.species_string for x in st.get_neighbors(st[n_idx], 3.0)
                               if x.species_string in ('Mn', 'Fe', 'V', 'Ni', 'Ti'))
                assert shell == sorted(want_tm), (name, shell, want_tm)
                gap = None
            assert len(moments) == len(st), (name, len(moments), len(st))
            comment = (f'# STAGE: relax (ionic + cell, ISIF=3); restart of {start_src}\n'
                       f'# MAGMOM = final projected moments of that relaxation ({start_mode},'
                       f' start_converged={start_converged})')
            title = (f"Na10 Ti2 Mn10 Fe1 V1 Ni4 N1 O35 ({lab}, N substituted O) -- v2 restart"
                     if br == 'N-O' else
                     f"Na10 Ti2 Mn10 Fe1 V1 Ni4 O35 ({lab}, O vacancy) -- v2 restart")
            write(target / 'POSCAR', poscar_text(st, title, order))
            write(target / 'INCAR', defect_incar(moments, 'relax', order, comment=comment))
            write(target / 'INCAR_static', defect_incar(moments, 'static', order,
                                                       comment='# STAGE: static single point; prepared from the same relaxation'))
            write(target / 'KPOINTS', KPOINTS_TEXT)
            write(target / 'job.pbs', job_pbs(f"V2_{name}", DEFECT_PPN, DEFECT_MEM))
            entries.append({'name': name, 'label': lab, 'branch': br, 'parent_site': site,
                            'n_sites': len(st), 'species': order, 'mode': start_mode,
                            'start': start_src, 'start_converged': start_converged,
                            'u_applied': {s: CONVENTION[s] for s in order},
                            'vacancy_gap_A': gap})
    write(d / 'manifest.json', json.dumps(
        {'start_policy': 'most-relaxed v1 geometry (resume CONTCAR if present, else stage2 CONTCAR), '
                         'restarted with the corrected U; fallback = rebuild on v2 parent CONTCAR',
         'v2_parent': f'workflows/{WFID}/00_v2/parent_relax/relaxed_parent_CONTCAR_v2',
         'v2_parent_species': parent_order, 'kpoints': 'Gamma 5x5x1', 'ismear': -5,
         'u_convention': CONVENTION, 'entries': entries}, indent=2, ensure_ascii=False))
    step['status'] = 'done'
    step['key_results'] = {'entries': len(entries), 'dir': str(d.relative_to(ROOT)),
                           'modes': {m: sum(1 for e in entries if e['mode'] == m)
                                     for m in {e['mode'] for e in entries}}}
    step['note'] = (f'prepared {len(entries)} defect relaxations; '
                    + ', '.join(f"{m}={sum(1 for e in entries if e['mode'] == m)}"
                                for m in {e['mode'] for e in entries}))
    return step['note']


def _species_of(poscar: Path):
    p = Poscar.from_file(str(poscar), check_for_potcar=False)
    return p.site_symbols, len(p.structure)


def _prepare_resume_inputs(stage: Path, rtag: str, names):
    """Build continuation inputs for relaxations that hit NSW without reaching EDIFFG.

    Each resume directory takes the previous CONTCAR as POSCAR, the same relax protocol,
    and MAGMOM taken from that run's final projected moments.
    """
    ritems = []
    for name in names:
        src_dir = stage / 'collected' / name
        dst = stage / rtag / name
        dst.mkdir(parents=True, exist_ok=True)
        order, natoms = _species_of(src_dir / 'POSCAR')
        moments = b.moments(src_dir / 'OUTCAR', natoms)
        comment = f'# STAGE: continuation relax (ISIF=3) after NSW was exhausted; restart of collected/{name}/CONTCAR'
        write(dst / 'POSCAR', (src_dir / 'CONTCAR').read_text())
        write(dst / 'INCAR', defect_incar(moments, 'relax', order, comment=comment))
        write(dst / 'KPOINTS', (src_dir / 'KPOINTS').read_text())
        write(dst / 'job.pbs', job_pbs(f'V2r_{name}', DEFECT_PPN, DEFECT_MEM))
        ritems.append((name, dst))
    return ritems


def _read_submission(stage_remote: str, log: Path):
    """{name: job id} recorded on the cluster for this stage (empty when nothing submitted)."""
    out = b.remote(f'cat "$HOME/{stage_remote}/submitted.tsv" 2>/dev/null || true', log)
    return {n: j for n, j in re.findall(r'^([A-Za-z0-9_\-]+)\t(\d+)$', out, re.M)}


def _remote_submission(stage_remote: str, items, log: Path):
    """Return the existing remote submission record if it covers all items, else [].

    Protects against duplicate submissions: the submission record (submitted.tsv) is
    written next to the job inputs, so if a previous round uploaded and submitted and
    then died before the workflow state was saved, we must reuse it instead of wiping
    the stage directory and starting those jobs a second time.
    """
    pairs = sorted(_read_submission(stage_remote, log).items())
    names = {n for n, _ in pairs}
    want = {n for n, _ in items}
    return pairs if names == want else []


def _tar_dirs(items, tar: Path):
    """items = [(unique_name, directory), ...]; tar layout is <unique_name>/<file>."""
    with tarfile.open(tar, 'w:gz') as tf:
        for name, d in items:
            for n in ['POSCAR', 'INCAR', 'INCAR_static', 'KPOINTS', 'job.pbs']:
                p = d / n
                if p.exists():
                    tf.add(p, arcname=f'{name}/{n}')


# Submissions require an explicit human go-ahead.  Without V2_ALLOW_SUBMIT=1 the
# submitting steps prepare everything and then hold, so a long-running monitor can
# never slip past a review gate (it did once: advance_workflow chains steps inside a
# single call, so an outside-the-call gate check is not enough).
ALLOW_SUBMIT = os.environ.get('V2_ALLOW_SUBMIT') == '1'


def _submit_allowed(step):
    if ALLOW_SUBMIT:
        return True
    step['note'] = (f'[{step["name"]}] inputs ready, submission held: '
                    f'set V2_ALLOW_SUBMIT=1 to release')
    return False


def _submit_remote(stage_remote: str, items, log: Path):
    """Submit exactly `items` (their inputs must already be uploaded); append to submitted.tsv.

    Only the given directories are touched, so already-submitted (possibly still running)
    jobs are never overwritten - this is what makes incremental submission safe.
    """
    md5 = '\n'.join(f'[ "$(md5sum "$LIB/{k}/POTCAR" | cut -d " " -f1)" = {v} ]' for k, v in EXPECTED_MD5.items())
    body = ''
    for name, d in items:
        order, _ = _species_of(d / 'POSCAR')
        pots = ' '.join(f'"$LIB/{POTCAR_DIR[s]}/POTCAR"' for s in order)
        body += f'''cd {name}
cat {pots} > POTCAR
[ "$(grep -c TITEL POTCAR)" -eq {len(order)} ]
J=$(sbatch --parsable job.pbs); J=${{J%%;*}}
[[ "$J" =~ ^[0-9]+$ ]]
printf '%s\\t%s\\n' {name} "$J" >> ../submitted.tsv
cd ..
'''
    script = f'''set -euo pipefail
cd "$HOME/{stage_remote}"
LIB={CFG['local_potcar_lib']}
{md5}
touch submitted.tsv
{body}
cat submitted.tsv
'''
    out = b.remote(script, log)
    return {n: j for n, j in re.findall(r'^([A-Za-z0-9_\-]+)\t(\d+)$', out, re.M)}


def _collect_one(dest: Path, stage_remote: str, name: str, jobid: str, log: Path):
    """Download and verify one finished calculation; returns a record dict."""
    dest.mkdir(parents=True, exist_ok=True)
    for fn in ['OUTCAR', 'CONTCAR', 'OSZICAR', 'XDATCAR', 'vasp.out', 'INCAR', 'POSCAR', 'KPOINTS']:
        with log.open('ab') as f:
            r = subprocess.run([b.SCP, '-o', 'BatchMode=yes', '-i', CFG['ssh_key'],
                                CFG['host'] + f':{stage_remote}/{name}/{fn}', str(dest / fn)],
                               stdout=f, stderr=subprocess.STDOUT)
        if r.returncode:
            raise RuntimeError(f'download failed for {name}/{fn}')
    t = (dest / 'OUTCAR').read_text(errors='replace')
    order = Poscar.from_file(str(dest / 'POSCAR'), check_for_potcar=False).site_symbols
    u = u_from_outcar(t)
    rec = {
        'name': name, 'job_id': jobid, 'species': order,
        'u_applied': {s: u.get(s) for s in order},
        'u_ok': all(s not in CONVENTION or abs(u.get(s, CONVENTION[s]) - CONVENTION[s]) <= TOL_U for s in order),
        'ionic_converged': 'reached required accuracy' in t,
        'electronic_converged': 'aborting loop because EDIFF is reached' in t,
        'normal_end': 'General timing and accounting informations' in t,
        'NKPTS_13': bool(re.search(r'NKPTS\s*=\s*13\b', t)),
        'ISMEAR_minus5': bool(re.search(r'ISMEAR\s*=\s*-5', t)),
        'ENCUT_520': bool(re.search(r'ENCUT\s*=\s*520', t)),
        'IVDW_11': bool(re.search(r'IVDW\s*=\s*11', t)),
        'ionic_steps': len(re.findall(r'TOTAL-FORCE \(eV/Angst\)', t)),
        'E0_eV': float(TOTEN.findall(t)[-1]) if TOTEN.findall(t) else None,
        'sigma0_eV': float(SIGMA0.findall(t)[-1]) if SIGMA0.findall(t) else None,
        'max_force_eV_A': None,
    }
    forces = list(re.finditer(r'TOTAL-FORCE \(eV/Angst\)', t))
    if forces:
        natoms = len(order)
        rows = []
        for line in t[forces[-1].end():].splitlines():
            f = line.split()
            if len(f) != 6:
                if rows:
                    break
                continue
            try:
                rows.append([float(x) for x in f[3:]])
            except ValueError:
                continue
            if len(rows) == natoms:
                break
        if len(rows) == natoms:
            rec['max_force_eV_A'] = max(sum(x * x for x in vec) ** 0.5 for vec in rows)
    rec['issues'] = [k for k in ['u_ok', 'electronic_converged', 'normal_end', 'NKPTS_13', 'ISMEAR_minus5', 'ENCUT_520', 'IVDW_11'] if not rec[k]]
    return rec


def defect_relax(state, step):
    """Submit, monitor and collect the 24 defect relaxations (with resume rounds)."""
    stage = D / 'defect_relax'
    src = D / 'defect_inputs'
    kr = step.setdefault('key_results', {})
    jobs = kr.get('jobs')
    rounds = kr.setdefault('rounds', [])
    stage_remote = REMOTE + '/defect_relax'

    # ---- phase A: first submission of the 24 relaxations
    if jobs is None:
        # step 1 writes flat <label>_<branch> directories (unique per defect)
        items = [(f'{lab}_{br}', src / f'{lab}_{br}') for lab in LABEL_SITES for br in BRANCHES]
        assert all((d / 'POSCAR').exists() for _, d in items), \
            'defect_inputs step not finished (missing ' + \
            ', '.join(n for n, d in items if not (d / 'POSCAR').exists()) + ')'
        if not _submit_allowed(step):
            return step['note']
        stage.mkdir(parents=True, exist_ok=True)
        pairs = _remote_submission(stage_remote, items, stage / 'existing.log')
        if pairs:
            print(f'[defect_relax] reusing existing remote submission record ({len(pairs)} jobs)')
        else:
            tar = stage / 'inputs.tar.gz'
            _tar_dirs(items, tar)
            b.remote(f'mkdir -p "$HOME/{stage_remote}"\nrm -rf "$HOME/{stage_remote}"/*\n', stage / 'mkdir.log')
            with (stage / 'upload.log').open('wb') as f:
                r = subprocess.run([b.SCP, '-o', 'BatchMode=yes', '-i', CFG['ssh_key'], str(tar),
                                    CFG['host'] + ':' + stage_remote + '/inputs.tar.gz'], stdout=f, stderr=subprocess.STDOUT)
            if r.returncode:
                raise RuntimeError('upload failed; see upload.log')
            b.remote(f'cd "$HOME/{stage_remote}"\ntar -xzmf inputs.tar.gz\n', stage / 'untar.log')
            pairs = sorted(_submit_remote(stage_remote, items, stage / 'submit.log').items())
        assert len(pairs) == 24, f'expected 24 submissions, got {len(pairs)}: {pairs}'
        jobs = [{'name': n, 'job_id': j} for n, j in pairs]
        kr['jobs'] = jobs
        rounds.append({'round': 1, 'jobs': jobs})
        step['status'] = 'waiting_run'
        step['note'] = f'round 1: submitted {len(jobs)} defect relaxations ({DEFECT_PPN} ranks each)'
        return step['note']

    # ---- phase B: poll and collect
    stage_remote = kr.get('stage_remote', REMOTE + '/defect_relax')
    names = ','.join(j['job_id'] for j in jobs)
    out = b.remote(f'sacct -X -n -P -j {names} --format=JobIDRaw,State,ExitCode\n', stage / 'accounting.log')
    status = {}
    for line in out.splitlines():
        a = line.split('|')
        if len(a) >= 3 and a[0].isdigit():
            status[a[0]] = (a[1], a[2])
    records = kr.setdefault('records', {})
    terminal = True
    for j in jobs:
        st = status.get(j['job_id'])
        if st is None or st[0] in ('PENDING', 'RUNNING', 'COMPLETING', 'CONFIGURING'):
            terminal = False
            continue
        if st[0] != 'COMPLETED' or st[1] != '0:0':
            raise RuntimeError(f"{j['name']}: scheduler state {st}")
        if j['name'] in records:
            continue
        rec = _collect_one(stage / 'collected' / j['name'], stage_remote, j['name'], j['job_id'], stage / 'download.log')
        records[j['name']] = rec
    if not terminal:
        done = len(records)
        step['note'] = f'round {len(rounds)}: {done}/24 collected, waiting for the rest'
        return step['note']

    unconverged = [n for n, r in records.items() if not r['ionic_converged']]
    bad = {n: r['issues'] for n, r in records.items() if r['issues']}
    if bad:
        raise RuntimeError(f'protocol checks failed: {bad}')
    if unconverged and len(rounds) < 3:
        # ---- phase C: resume the unconverged relaxations from their CONTCARs
        rtag = f'resume{len(rounds)}'
        ritems = _prepare_resume_inputs(stage, rtag, unconverged)
        rtar = stage / f'{rtag}.tar.gz'
        _tar_dirs(ritems, rtar)
        rremote = REMOTE + f'/{rtag}'
        b.remote(f'mkdir -p "$HOME/{rremote}"\nrm -rf "$HOME/{rremote}"/*\n', stage / f'{rtag}_mkdir.log')
        with (stage / f'{rtag}_upload.log').open('wb') as f:
            r = subprocess.run([b.SCP, '-o', 'BatchMode=yes', '-i', CFG['ssh_key'], str(rtar),
                                CFG['host'] + ':' + rremote + '/inputs.tar.gz'], stdout=f, stderr=subprocess.STDOUT)
        if r.returncode:
            raise RuntimeError(f'{rtag} upload failed')
        b.remote(f'cd "$HOME/{rremote}"\ntar -xzmf inputs.tar.gz\n', stage / f'{rtag}_untar.log')
        got = _submit_remote(rremote, ritems, stage / f'{rtag}_submit.log')
        pairs = sorted(got.items())
        assert len(pairs) == len(ritems), (pairs, len(ritems))
        jobs = [{'name': n, 'job_id': j} for n, j in pairs]
        kr['jobs'] = jobs
        kr['stage_remote'] = rremote
        kr['records'] = {k: v for k, v in records.items() if k not in unconverged}
        rounds.append({'round': len(rounds) + 1, 'resumed': unconverged, 'jobs': jobs})
        step['status'] = 'waiting_run'
        step['note'] = f'round {len(rounds)}: resubmitted {len(jobs)} unconverged relaxations {unconverged}'
        return step['note']

    if unconverged:
        raise RuntimeError(f'still unconverged after {len(rounds)} rounds: {unconverged}')
    step['status'] = 'done'
    kr['job_ids'] = {n: r['job_id'] for n, r in records.items()}
    step['note'] = (f'all 24 defect relaxations converged and verified '
                    f'(U convention + NKPTS + ISMEAR checked per OUTCAR); rounds={len(rounds)}')
    return step['note']


def statics(state, step):
    """Parent static + 24 unified defect statics, prepared and submitted INCREMENTALLY.

    Every advance prepares whatever is available (the parent as soon as its relaxation is
    collected, each defect as soon as its own relaxation is), uploads/submits only the
    directories that have not been submitted yet, and then polls.  This lets the statics
    overlap the tail of the relaxation stage instead of waiting for all 24.
    """
    stage = D / 'statics'
    kr = step.setdefault('key_results', {})
    stage_remote = REMOTE + '/statics'
    rel = D / 'defect_relax' / 'collected'
    all_names = ['parent_static'] + [f'{lab}_{br}' for lab in LABEL_SITES for br in BRANCHES]

    # ---------- prepare whatever is ready (idempotent: only missing dirs are written)
    pd = stage / 'parent_static'
    if not (pd / 'POSCAR').exists():
        pcont = D / 'parent_relax' / 'collected' / 'CONTCAR'
        if pcont.exists():
            order, natoms = _species_of(pcont)
            write(pd / 'POSCAR', pcont.read_text())
            write(pd / 'INCAR', defect_incar(b.moments(D / 'parent_relax' / 'collected' / 'OUTCAR', natoms), 'static', order))
            write(pd / 'KPOINTS', KPOINTS_TEXT)
            write(pd / 'job.pbs', job_pbs('V2_parent_static', DEFECT_PPN, '24G'))
    for lab in LABEL_SITES:
        for br in BRANCHES:
            name = f'{lab}_{br}'
            dst, src_dir = stage / name, rel / name
            if (dst / 'POSCAR').exists() or not (src_dir / 'CONTCAR').exists():
                continue
            order, natoms = _species_of(src_dir / 'POSCAR')
            write(dst / 'POSCAR', (src_dir / 'CONTCAR').read_text())
            write(dst / 'INCAR', defect_incar(b.moments(src_dir / 'OUTCAR', natoms), 'static', order))
            write(dst / 'KPOINTS', (src_dir / 'KPOINTS').read_text())
            write(dst / 'job.pbs', job_pbs(f'V2s_{name}', DEFECT_PPN, '24G'))
    items = [(n, stage / n) for n in all_names if (stage / n / 'POSCAR').exists()]

    # ---------- submit only what is still missing on the cluster
    submitted = _read_submission(stage_remote, stage / 'existing.log') if items else {}
    todo = [(n, d) for n, d in items if n not in submitted]
    if todo:
        if not _submit_allowed(step):
            return step['note']
        tar = stage / 'inputs.tar.gz'
        _tar_dirs(todo, tar)
        b.remote(f'mkdir -p "$HOME/{stage_remote}"\n', stage / 'mkdir.log')
        with (stage / 'upload.log').open('wb') as f:
            r = subprocess.run([b.SCP, '-o', 'BatchMode=yes', '-i', CFG['ssh_key'], str(tar),
                                CFG['host'] + ':' + stage_remote + '/inputs.tar.gz'], stdout=f, stderr=subprocess.STDOUT)
        if r.returncode:
            raise RuntimeError('statics upload failed')
        b.remote(f'cd "$HOME/{stage_remote}"\ntar -xzmf inputs.tar.gz\n', stage / 'untar.log')
        submitted = _submit_remote(stage_remote, todo, stage / 'submit.log') or submitted
    jobs = [{'name': n, 'job_id': j} for n, j in sorted(submitted.items())]
    kr['jobs'] = jobs
    kr['prepared'] = sorted(n for n, _ in items)

    # ---------- poll and collect what was submitted
    records = kr.setdefault('records', {})
    if jobs:
        names = ','.join(j['job_id'] for j in jobs)
        out = b.remote(f'sacct -X -n -P -j {names} --format=JobIDRaw,State,ExitCode\n', stage / 'accounting.log')
        status = {}
        for line in out.splitlines():
            a = line.split('|')
            if len(a) >= 3 and a[0].isdigit():
                status[a[0]] = (a[1], a[2])
        for j in jobs:
            st = status.get(j['job_id'])
            if st is None or st[0] in ('PENDING', 'RUNNING', 'COMPLETING', 'CONFIGURING', 'FAILED'):
                if st and st[0] not in ('PENDING', 'RUNNING', 'COMPLETING', 'CONFIGURING'):
                    raise RuntimeError(f"{j['name']}: scheduler state {st}")
                continue
            if st[0] != 'COMPLETED' or st[1] != '0:0':
                raise RuntimeError(f"{j['name']}: scheduler state {st}")
            if j['name'] in records:
                continue
            records[j['name']] = _collect_one(stage / 'collected' / j['name'], stage_remote, j['name'], j['job_id'], stage / 'download.log')

    bad = {n: r['issues'] for n, r in records.items() if r['issues']}
    if bad:
        raise RuntimeError(f'static protocol checks failed: {bad}')
    no_energy = [n for n, r in records.items() if r['sigma0_eV'] is None]
    if no_energy:
        raise RuntimeError(f'no energy(sigma->0) recorded for {no_energy}')
    if len(records) == len(all_names) == 25:
        step['status'] = 'done'
        step['note'] = '25/25 statics completed and verified (U convention, ISMEAR=-5, NKPTS=13)'
        return step['note']
    step['status'] = 'waiting_run'
    step['note'] = (f'{len(records)}/25 collected; {len(items)}/25 prepared; {len(jobs)} submitted'
                    + (f'; still missing relaxations for '
                       f'{[n for n in all_names if n not in [x for x, _ in items]]}' if len(items) < 25 else ''))
    return step['note']


def _plot_v2(rows, mu_o, mu_n, e_parent, out_dir: Path):
    """Two-curve figure (O vacancy / N substitution) for the v2 campaign."""
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib import font_manager
    available = {f.name for f in font_manager.fontManager.ttflist}
    font = next((f for f in ['Microsoft YaHei', 'SimHei', 'Noto Sans CJK SC'] if f in available), 'DejaVu Sans')
    plt.rcParams.update({'font.family': font, 'axes.unicode_minus': False, 'font.size': 11})
    order = list(LABEL_SITES)
    data = {br: [next(r for r in rows if r['site'] == lab and r['branch'] == br) for lab in order] for br in BRANCHES}
    fig, ax = plt.subplots(figsize=(12, 6))
    for br, label, color, marker, off in [('O-van', 'O 空位', '#315d88', 'o', 10),
                                          ('N-O', 'N 取代 O', '#d47934', 's', -17)]:
        y = [r['formation_eV'] for r in data[br]]
        ax.plot(range(12), y, color=color, marker=marker, lw=1.6, ms=6, label=label)
        for i, v in enumerate(y):
            ax.annotate(f'{v:.3f}', (i, v), xytext=(0, off), textcoords='offset points',
                        ha='center', fontsize=8.5, color=color)
    ax.set_xticks(range(12), order, rotation=40, ha='right')
    ax.set_xlabel('位点'); ax.set_ylabel('缺陷形成能（eV）')
    ax.set_title('V 替代体系（约定 +U 重算）：O 空位与 N 取代 O 的形成能', pad=16)
    ax.grid(axis='y', alpha=.2); ax.spines[['top', 'right']].set_visible(False)
    ax.margins(y=.22); ax.legend(frameon=False)
    fig.text(.5, .018,
             r'元素参考：$\mu_\mathrm{O}=\frac{1}{2}E(\mathrm{O_2})$，$\mu_\mathrm{N}=\frac{1}{2}E(\mathrm{N_2})$；'
             r'DFT+U：Ti 5.2 / Mn 3.9 / Fe 4.0 / Ni 6.2 / V 3.25 eV；未加经验修正、零点能及温度修正',
             ha='center', fontsize=9, color='#555555')
    fig.tight_layout(rect=[0, .05, 1, 1])
    fig.savefig(out_dir / 'defect_formation_comparison.png', dpi=300)
    fig.savefig(out_dir / 'defect_formation_comparison.svg')
    plt.close(fig)


def _total_magnetization(outcar: Path):
    """Last 'number of electron X magnetization Y' value from an OUTCAR (or None)."""
    if not outcar.exists():
        return None
    t = outcar.read_text(errors='replace')
    m = re.findall(r'number of electron\s+[\d.]+\s+magnetization\s+(-?[\d.]+)', t)
    return float(m[-1]) if m else None


def energies(state, step):
    """Formation energies from the v2 statics + the existing O2/N2 references."""
    kr = step.setdefault('key_results', {})
    if step['status'] != 'pending':
        return step['note']
    srec = next(s for s in state['steps'] if s['name'] == 'statics')['key_results']['records']
    ref_dir = ROOT / 'workflows' / 'oxygen_formation_refs_20261015' / '00_references'
    nref_dir = ROOT / 'workflows' / 'nitrogen_formation_ref_20261015' / '00_reference'
    o2 = json.loads((ref_dir / 'reference_results.json').read_text())['references']['O2_static']['energy_eV']
    n2 = json.loads((nref_dir / 'reference_results.json').read_text())['references']['N2_static']['energy_eV']
    mu_o, mu_n = o2 / 2.0, n2 / 2.0
    e_parent = srec['parent_static']['sigma0_eV']
    order = [l for l in LABEL_SITES]
    rows = []
    for lab in order:
        for br in BRANCHES:
            name = f'{lab}_{br}'
            r = srec[name]
            ef = r['sigma0_eV'] - e_parent + mu_o - (mu_n if br == 'N-O' else 0.0)
            relax_mag = _total_magnetization(D / 'defect_relax' / 'collected' / name / 'OUTCAR')
            static_mag = _total_magnetization(D / 'statics' / 'collected' / name / 'OUTCAR')
            rows.append({'site': lab, 'branch': br, 'defect_energy_eV': r['sigma0_eV'],
                         'formation_eV': ef, 'job_id': r['job_id'],
                         'relax_total_moment_uB': relax_mag, 'static_total_moment_uB': static_mag,
                         'moment_shift_uB': (None if (relax_mag is None or static_mag is None)
                                             else round(static_mag - relax_mag, 4)),
                         'u_applied': r['u_applied']})
    out_dir = ROOT / 'defect_formation_comparison_v2'
    out_dir.mkdir(exist_ok=True)
    payload = {'u_convention': CONVENTION, 'parent_static_eV': e_parent,
               'references': {'O2_static_eV': o2, 'N2_static_eV': n2, 'mu_O_eV': mu_o, 'mu_N_eV': mu_n,
                              'source': 'first campaign molecular references (LDAU=.FALSE., unaffected by the U fix)'},
               'formulas': {'O-vacancy': 'E(O35) - E(parent) + 0.5 E(O2)',
                            'N-substitution': 'E(N1O35) - E(parent) + 0.5 E(O2) - 0.5 E(N2)'},
               'sites': rows}
    (out_dir / 'formation_energies.json').write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding='utf-8')
    with (out_dir / 'formation_energies.csv').open('w', encoding='utf-8-sig', newline='') as f:
        w = csv.DictWriter(f, fieldnames=['site', 'branch', 'defect_energy_eV', 'formation_eV', 'job_id',
                                          'relax_total_moment_uB', 'static_total_moment_uB', 'moment_shift_uB'])
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k) for k in ['site', 'branch', 'defect_energy_eV', 'formation_eV', 'job_id',
                                              'relax_total_moment_uB', 'static_total_moment_uB', 'moment_shift_uB']})
    kr['formation'] = rows
    kr['mu_O_eV'], kr['mu_N_eV'] = mu_o, mu_n
    kr['parent_static_eV'] = e_parent
    _plot_v2(rows, mu_o, mu_n, e_parent, out_dir)
    from PIL import Image
    with Image.open(out_dir / 'defect_formation_comparison.png') as im:
        im.verify()
    best = {br: min((r for r in rows if r['branch'] == br), key=lambda r: r['formation_eV']) for br in BRANCHES}
    step['status'] = 'done'
    step['note'] = ('v2 formation energies + figure written; ' +
                    '; '.join(f"{br}: {v['site']} {v['formation_eV']:.3f} eV" for br, v in best.items()))
    return step['note']


def handle(state, step):
    if step['name'] == 'parent_relax':
        return parent_relax(state, step)
    if step['name'] == 'defect_inputs':
        return defect_inputs(state, step)
    if step['name'] == 'defect_relax':
        return defect_relax(state, step)
    if step['name'] == 'statics':
        return statics(state, step)
    if step['name'] == 'energies':
        return energies(state, step)
    raise RuntimeError(f'unknown step {step["name"]}')


wf._STEP_HANDLERS['v2'] = handle
wf.WF_TEMPLATES['v2_campaign'] = [
    {'name': 'parent_relax', 'type': 'v2'},
    {'name': 'defect_inputs', 'type': 'v2'},
    {'name': 'defect_relax', 'type': 'v2'},
    {'name': 'statics', 'type': 'v2'},
    {'name': 'energies', 'type': 'v2'},
]

if __name__ == '__main__':
    state = wf._load_state(WFID, PROJECT)
    if state is None:
        state = {'schema_version': 1, 'wf_id': WFID, 'template': 'v2_campaign', 'project': PROJECT,
                 'status': 'running', 'revision': 0, 'created': time.strftime('%Y-%m-%d %H:%M:%S'),
                 'params': {'node': 'bkzhang', 'u_convention': CONVENTION, 'reason': 'first campaign used a wrong per-element U mapping'},
                 'current': 0,
                 'steps': [{'name': n, 'type': 'v2', 'status': 'pending', 'key_results': {}, 'note': ''}
                           for n in ['parent_relax', 'defect_inputs', 'defect_relax', 'statics', 'energies']]}
        wf._save_state(state)
    print(wf.advance_workflow(WFID, PROJECT, expected_revision=state['revision']))
