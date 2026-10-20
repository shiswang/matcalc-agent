"""Cu campaign (agreed +U): mirror of run_v2_campaign, parameterised for Cu.

Agreed convention: Ti 5.2 / Mn 3.9 / Fe 4.0 / Ni 6.2 / Cu 1.9 (Na, N, O: no U).
The old Cu defects were never relaxed (v1 was static-only), so the 24 relaxations start
from the old Cu defect structures and run from scratch.

Steps: parent_relax -> defect_inputs -> defect_relax -> statics -> energies
"""
from __future__ import annotations
import csv, json, os, re, subprocess, sys, tarfile, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # scripts/campaigns/024_CuFeMn_V/
import run_v2_campaign as v2
from pymatgen.core import Structure
from pymatgen.io.vasp.inputs import Poscar

ROOT = v2.ROOT
PROJECT = '024_CuFeMn_V'
WFID = 'cu_u_convention_20261017'
REMOTE = 'matcalc/024_CuFeMn_V/' + WFID
D = ROOT / 'workflows' / WFID / '00_cu'
OLD = Path(os.environ.get('MATCALC_OLD_CU_PROJECT') or r'E:\Project\024_CuFeMn\模拟计算')

CONVENTION = {'Na': 0.0, 'Ti': 5.2, 'Mn': 3.9, 'Fe': 4.0, 'Cu': 1.9, 'Ni': 6.2, 'N': 0.0, 'O': 0.0}
POTCAR_DIR = {'Na': 'Na_pv', 'Ti': 'Ti_pv', 'Mn': 'Mn_pv', 'Fe': 'Fe_pv',
              'Cu': 'Cu_pv', 'Ni': 'Ni_pv', 'N': 'N', 'O': 'O'}
EXPECTED_MD5 = {**v2.EXPECTED_MD5, 'Cu_pv': '32975c9961e0e1e5df658b892e8d6582'}
LABEL_SITES = {
    'CuMnTi': (49, ['Cu', 'Mn', 'Ti']), 'CuNiMn': (51, ['Cu', 'Mn', 'Ni']),
    'CuTiNi': (58, ['Cu', 'Ni', 'Ti']), 'FeTiNi': (40, ['Fe', 'Ni', 'Ti']),
    'MnFeNi': (30, ['Fe', 'Mn', 'Ni']), 'MnFeTi': (31, ['Fe', 'Mn', 'Ti']),
    'MnMnCu': (55, ['Cu', 'Mn', 'Mn']), 'MnMnFe': (42, ['Fe', 'Mn', 'Mn']),
    'MnMnMn': (50, ['Mn', 'Mn', 'Mn']), 'MnMnNi': (41, ['Mn', 'Mn', 'Ni']),
    'MnTiNi': (32, ['Mn', 'Ni', 'Ti']), 'TiMnMn': (59, ['Mn', 'Mn', 'Ti']),
}
LABELS = list(LABEL_SITES)
BRANCHES = ['N-O', 'O-van']
KPOINTS_TEXT = v2.KPOINTS_TEXT
DEFECT_PPN, DEFECT_MEM = 16, '20G'
ALLOW_SUBMIT = os.environ.get('V2_ALLOW_SUBMIT') == '1'
write = v2.write
job_pbs = v2.job_pbs
_poscar_text = v2.poscar_text
_species_of = v2._species_of
_remote = v2.b.remote
_scp = v2.b.SCP
CFG = v2.CFG
TOL_U = v2.TOL_U
SIGMA0 = v2.SIGMA0
TOTEN = v2.TOTEN

# 不要改 v2 的模块级常量来"复用"：两个驱动在同一进程里是共享模块，
# 改 v2.CONVENTION 会把 V 的 3.25 覆盖成 Cu 的 1.9，v2 再生成 V 体系直接 KeyError。
# Cu 需要的常量都在本模块各自定义；从 v2 复用的只限无状态函数（write/job_pbs/...）。
assert v2.CONVENTION['V'] == 3.25 and 'Cu' not in v2.CONVENTION, \
    'v2 的 U 约定已被污染：检查是否有代码在 import 后改 v2.CONVENTION'


def u_from_outcar(text):
    titels = [x.strip() for x in re.findall(r'TITEL\s*=\s*(.+)', text)]
    species = [x.split()[1].split('_')[0] for x in titels if len(x.split()) > 1]
    m = re.findall(r'LDAUU\s*=\s*(.*)$', text, re.M)
    u = [float(x) for x in m[-1].split()]
    assert len(u) == len(species), (len(u), len(species))
    return dict(zip(species, u))


def assert_convention(text, where):
    got = u_from_outcar(text)
    bad = {e: (got.get(e), CONVENTION[e]) for e in CONVENTION
           if e in got and abs(got[e] - CONVENTION[e]) > TOL_U}
    if bad:
        raise AssertionError(f'{where}: per-element U deviates from the agreed convention: {bad}')
    return got


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


def defect_incar(magmom, stage, species_order, system=None, comment=None, nelm=100):
    ldaul = ' '.join('%d' % (2 if s in ('Ti', 'Mn', 'Fe', 'Cu', 'Ni') else -1) for s in species_order)
    ldauu = ' '.join('%g' % CONVENTION[s] for s in species_order)
    ldauj = ' '.join('0.0' for _ in species_order)
    if system is None:
        if 'N' in species_order:
            system = 'Na10 Ti2 Mn10 Fe1 Cu1 Ni4 N1 O35'
        elif len(magmom) == 64:
            system = 'Na10 Ti2 Mn10 Fe1 Cu1 Ni4 O36 (parent)'
        else:
            system = 'Na10 Ti2 Mn10 Fe1 Cu1 Ni4 O35 (O vacancy)'
    head = 'relax (ionic + cell, ISIF=3)' if stage == 'relax' else 'static single point (NSW=0, ISIF=2)'
    ionic = ('NSW = 200\nIBRION = 2\nISIF = 3\nEDIFFG = -0.02\nPOTIM = 0.5\nISYM = 2'
             if stage == 'relax' else 'NSW = 0\nIBRION = -1\nISIF = 2\nEDIFFG = -0.02\nPOTIM = 0.5\nISYM = 2')
    return _assert_incar_stage(f"""SYSTEM = {system} -- {head}
# Project 024_CuFeMn_Cu, agreed +U convention (Ti 5.2 / Mn 3.9 / Fe 4.0 / Ni 6.2 / Cu 1.9)
{comment or '# STAGE: ' + head}

PREC    = Accurate
ISTART  = 0
ICHARG  = 2
ISPIN   = 2
MAGMOM  = {' '.join('%g' % v for v in magmom)}
NCORE   = 4

ENCUT   = 520
NELM    = {nelm}
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


def _collect_one(dest, stage_remote, name, jobid, log):
    dest.mkdir(parents=True, exist_ok=True)
    for fn in ['OUTCAR', 'CONTCAR', 'OSZICAR', 'XDATCAR', 'vasp.out', 'INCAR', 'POSCAR', 'KPOINTS']:
        with log.open('ab') as f:
            r = subprocess.run([v2.b.SCP, '-o', 'BatchMode=yes', '-i', CFG['ssh_key'],
                                CFG['host'] + f':{stage_remote}/{name}/{fn}', str(dest / fn)],
                               stdout=f, stderr=subprocess.STDOUT)
        if r.returncode:
            raise RuntimeError(f'download failed for {name}/{fn}')
    t = (dest / 'OUTCAR').read_text(errors='replace')
    order = Poscar.from_file(str(dest / 'POSCAR'), check_for_potcar=False).site_symbols
    u = u_from_outcar(t)
    rec = {'name': name, 'job_id': jobid, 'species': order,
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
           'sigma0_eV': float(SIGMA0.findall(t)[-1]) if SIGMA0.findall(t) else None,
           'E0_eV': float(TOTEN.findall(t)[-1]) if TOTEN.findall(t) else None,
           'max_force_eV_A': None}
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
    rec['issues'] = [k for k in ['u_ok', 'electronic_converged', 'normal_end', 'NKPTS_13',
                                 'ISMEAR_minus5', 'ENCUT_520', 'IVDW_11'] if not rec[k]]
    return rec


def _read_submission(stage_remote, log):
    """{name: job_id} recorded on the cluster for this stage (empty when nothing submitted)."""
    out = _remote(f'cat "$HOME/{stage_remote}/submitted.tsv" 2>/dev/null || true', log)
    latest = {}
    for n, j in re.findall(r'^([A-Za-z0-9_\-]+)\t(\d+)$', out, re.M):
        latest[n] = j          # later lines win: a resubmission supersedes the old id
    return latest


def _remote_submission(stage_remote, items, log):
    """Return [(name, job_id)] only when the remote record covers exactly this item set.

    Used by the defect_relax stage, which must reuse a previous round's submission
    verbatim (all 24 or nothing) instead of restarting the batch.
    """
    pairs = sorted(_read_submission(stage_remote, log).items())
    want = {n for n, _ in items}
    return pairs if {n for n, _ in pairs} == want else []


def _submit_remote(stage_remote, items, log):
    md5 = '\n'.join(f'[ "$(md5sum "$LIB/{k}/POTCAR" | cut -d " " -f1)" = {v} ]' for k, v in EXPECTED_MD5.items())
    body = ''
    for name, dd in items:
        order, _ = _species_of(dd / 'POSCAR')
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
    out = _remote(script, log)
    return {n: j for n, j in re.findall(r'^([A-Za-z0-9_\-]+)\t(\d+)$', out, re.M)}


def _tar_dirs(items, tar):
    with tarfile.open(tar, 'w:gz') as tf:
        for name, dd in items:
            for n in ['POSCAR', 'INCAR', 'KPOINTS', 'job.pbs']:
                p = dd / n
                if p.exists():
                    tf.add(p, arcname=f'{name}/{n}')


# --------------------------------------------------------------------------- step 0
def parent_relax(state, step):
    d = D / 'parent_relax'
    if step['status'] == 'pending':
        contcar = OLD / 'initial_relax' / 'CONTCAR'
        struct = Poscar.from_file(str(contcar), check_for_potcar=False).structure
        order = Poscar.from_file(str(contcar), check_for_potcar=False).site_symbols
        assert order == ['Na', 'Ti', 'Ni', 'Mn', 'Fe', 'Cu', 'O'], order
        assert len(struct) == 64, len(struct)
        moments = v2.b.moments(OLD / 'initial_relax' / 'OUTCAR', len(struct))
        write(d / 'POSCAR', _poscar_text(struct, 'Na10 Ti2 Mn10 Fe1 Cu1 Ni4 O36 parent -- start from old Cu CONTCAR', order))
        write(d / 'INCAR', defect_incar(moments, 'relax', order,
                                       system='Na10 Ti2 Mn10 Fe1 Cu1 Ni4 O36 (parent, start from old Cu CONTCAR)'))
        write(d / 'KPOINTS', KPOINTS_TEXT)
        write(d / 'job.pbs', job_pbs('Cu_parent_relax', 32, '32G'))
        write(d / 'manifest.json', json.dumps(
            {'stage': 'parent_relax', 'start_structure': str(contcar), 'species': order, 'atoms': 64,
             'u_applied': {s: CONVENTION[s] for s in order},
             'protocol': 'ISIF=3, NSW=200, EDIFFG=-0.02, ISMEAR=-5, 13 k-points'}, indent=2))
        step['status'] = 'waiting_submit'
        step['note'] = f'parent relax prepared from old Cu CONTCAR; U per element = {dict((s, CONVENTION[s]) for s in order)}'
        return step['note']
    if not step.get('submitted_job'):
        tar = d / 'inputs.tar.gz'
        with tarfile.open(tar, 'w:gz') as tf:
            for n in ['POSCAR', 'INCAR', 'KPOINTS', 'job.pbs']:
                tf.add(d / n, arcname=f'parent_relax/{n}')
        _remote(f'mkdir -p "$HOME/{REMOTE}"\n', d / 'mkdir.log')
        with (d / 'upload.log').open('wb') as f:
            r = subprocess.run([_scp, '-o', 'BatchMode=yes', '-i', CFG['ssh_key'], str(tar),
                                CFG['host'] + ':' + REMOTE + '/inputs.tar.gz'], stdout=f, stderr=subprocess.STDOUT)
        if r.returncode:
            raise RuntimeError('upload failed')
        order = Poscar.from_file(str(d / 'POSCAR'), check_for_potcar=False).site_symbols
        pots = ' '.join(f'"$LIB/{POTCAR_DIR[s]}/POTCAR"' for s in order)
        md5 = '\n'.join(f'[ "$(md5sum "$LIB/{k}/POTCAR" | cut -d " " -f1)" = {v} ]' for k, v in EXPECTED_MD5.items())
        script = f'''set -euo pipefail
cd "$HOME/{REMOTE}"
if [ -f submitted.tsv ]; then cat submitted.tsv; exit 0; fi
tar -xzmf inputs.tar.gz
LIB={CFG['local_potcar_lib']}
{md5}
cd parent_relax
cat {pots} > POTCAR
[ "$(grep -c TITEL POTCAR)" -eq {len(order)} ]
J=$(sbatch --parsable job.pbs); J=${{J%%;*}}
[[ "$J" =~ ^[0-9]+$ ]]
printf 'parent_relax\\t%s\\n' "$J" > ../submitted.tsv
cat ../submitted.tsv
'''
        out = _remote(script, d / 'submit.log')
        ids = re.findall(r'parent_relax\t(\d+)', out)
        assert ids, f'no job id parsed; see submit.log\n{out}'
        step['submitted_job'] = ids[-1]
        step['key_results'] = {'job_id': ids[-1], 'remote_path': REMOTE}
        step['status'] = 'waiting_run'
        step['note'] = f'Cu parent relaxation submitted as job {ids[-1]} (32 ranks, --mem=32G)'
        return step['note']
    job = step['submitted_job']
    out = _remote(f'sacct -X -n -P -j {job} --format=JobIDRaw,State,ExitCode\n', d / 'accounting.log')
    status = out.strip().split('|')
    if len(status) < 3 or status[1] != 'COMPLETED':
        step['note'] = f'Cu parent relaxation {job}: {out.strip() or "no record yet"}'
        return step['note']
    if status[2] != '0:0':
        raise RuntimeError(f'Cu parent relaxation {job} exited with {status[2]}')
    dest = d / 'collected'
    dest.mkdir(parents=True, exist_ok=True)
    for fn in ['OUTCAR', 'CONTCAR', 'OSZICAR', 'XDATCAR', 'vasp.out', 'INCAR', 'POSCAR', 'KPOINTS']:
        with (d / 'download.log').open('ab') as f:
            r = subprocess.run([_scp, '-o', 'BatchMode=yes', '-i', CFG['ssh_key'],
                                CFG['host'] + f':{REMOTE}/parent_relax/{fn}', str(dest / fn)],
                               stdout=f, stderr=subprocess.STDOUT)
        if r.returncode:
            raise RuntimeError('download failed for ' + fn)
    t = (dest / 'OUTCAR').read_text(errors='replace')
    checks = {'ionic_converged': 'reached required accuracy' in t,
              'electronic_converged': 'aborting loop because EDIFF is reached' in t,
              'normal_end': 'General timing and accounting informations' in t,
              'NKPTS_13': bool(re.search(r'NKPTS\s*=\s*13\b', t)),
              'ENCUT_520': bool(re.search(r'ENCUT\s*=\s*520', t)),
              'ISPIN_2': bool(re.search(r'ISPIN\s*=\s*2', t)),
              'IVDW_11': bool(re.search(r'IVDW\s*=\s*11', t))}
    u = assert_convention(t, 'Cu parent OUTCAR')
    toten = TOTEN.findall(t)
    write(d / 'parent_moments_cu.txt', ' '.join('%g' % m for m in v2.b.moments(dest / 'OUTCAR', 64)))
    write(d / 'relaxed_parent_CONTCAR_cu', (dest / 'CONTCAR').read_text())
    step['key_results'].update({'job_id': job, 'checks': checks, 'u_applied': u,
                                'E0_eV': float(toten[-1]) if toten else None,
                                'ionic_steps': len(re.findall(r'TOTAL-FORCE \(eV/Angst\)', t))})
    if not all(checks.values()):
        step['note'] = f'Cu parent finished but checks failed: {checks}'
        return step['note']
    step['status'] = 'done'
    step['note'] = f'Cu parent relaxation converged: E0={float(toten[-1]):.8f} eV, U convention verified'
    return step['note']


# --------------------------------------------------------------------------- step 1
def defect_inputs(state, step):
    d = D / 'defect_inputs'
    if step['status'] != 'pending':
        return step['note']
    parent = Poscar.from_file(str(OLD / 'initial_relax' / 'CONTCAR'), check_for_potcar=False).structure
    entries = []
    for lab, (site, want_tm) in LABEL_SITES.items():
        for br in BRANCHES:
            src = (OLD / 'N-O-calc' / lab / 'CONTCAR') if br == 'N-O' else (OLD / 'O-van-calc' / 'sturcture' / lab / 'CONTCAR')
            out = src.with_name('OUTCAR')
            assert src.exists(), src
            st = Poscar.from_file(str(src), check_for_potcar=False).structure
            order = Poscar.from_file(str(src), check_for_potcar=False).site_symbols
            expect = ['Na', 'Ti', 'Mn', 'Fe', 'Cu', 'Ni'] + (['N'] if br == 'N-O' else []) + ['O']
            assert order == expect, (lab, br, order, expect)
            assert len(st) == (64 if br == 'N-O' else 63), (lab, br, len(st))
            if br == 'N-O':
                n_idx = [i for i, s in enumerate(st) if s.species_string == 'N'][0]
                shell = sorted(x.species_string for x in st.get_neighbors(st[n_idx], 3.0)
                               if x.species_string in ('Cu', 'Mn', 'Fe', 'Ni', 'Ti'))
                assert shell == sorted(want_tm), (lab, br, shell, want_tm)
                gap = None
            else:
                gap = float(min(st.lattice.get_all_distances([parent[site].frac_coords],
                                                             [s.frac_coords for s in st])[0]))
                assert gap > 1.0, (lab, br, gap)
            moments = v2.b.moments(out, len(st)) if out.exists() else None
            target = d / f'{lab}_{br}'
            title = (f'Na10 Ti2 Mn10 Fe1 Cu1 Ni4 N1 O35 ({lab}, N substituted O) -- old Cu defect start'
                     if br == 'N-O' else f'Na10 Ti2 Mn10 Fe1 Cu1 Ni4 O35 ({lab}, O vacancy) -- old Cu defect start')
            write(target / 'POSCAR', _poscar_text(st, title, order))
            comment = ('# STAGE: relax (ionic + cell, ISIF=3); start geometry from the old Cu project\n'
                       '# MAGMOM = final projected moments of the old static run (same defect)')
            if moments is None:
                comment = '# STAGE: relax (ionic + cell, ISIF=3); no old moments found, MAGMOM below is from the parent transplant'
            write(target / 'INCAR', defect_incar(moments, 'relax', order, comment=comment))
            write(target / 'KPOINTS', KPOINTS_TEXT)
            write(target / 'job.pbs', job_pbs(f'CuR_{lab}_{br}', DEFECT_PPN, DEFECT_MEM))
            entries.append({'name': f'{lab}_{br}', 'label': lab, 'branch': br, 'parent_site': site,
                            'n_sites': len(st), 'species': order, 'start': str(src),
                            'u_applied': {s: CONVENTION[s] for s in order}, 'vacancy_gap_A': gap,
                            'magmom_from': str(out) if out.exists() else None})
    write(d / 'manifest.json', json.dumps(
        {'start_policy': 'old Cu defect structures (v1 was static-only, so these are unrelaxed starts)',
         'kpoints': 'Gamma 5x5x1', 'ismear': -5, 'u_convention': CONVENTION, 'entries': entries}, indent=2, ensure_ascii=False))
    step['status'] = 'done'
    step['key_results'] = {'entries': len(entries), 'dir': str(d.relative_to(ROOT))}
    step['note'] = f'prepared {len(entries)} defect relaxations from old Cu defect structures (24 = 12 sites x 2 branches)'
    return step['note']


# --------------------------------------------------------------------------- step 2
def defect_relax(state, step):
    stage = D / 'defect_relax'
    kr = step.setdefault('key_results', {})
    jobs = kr.get('jobs')
    stage_remote = REMOTE + '/defect_relax'
    src = D / 'defect_inputs'
    if jobs is None:
        items = [(n, src / n) for n in [f'{l}_{b}' for l in LABELS for b in BRANCHES]]
        assert all((dd / 'POSCAR').exists() for _, dd in items)
        stage.mkdir(parents=True, exist_ok=True)
        pairs = _remote_submission(stage_remote, items, stage / 'existing.log')
        if pairs:
            print(f'[cu defect_relax] reusing existing submission record ({len(pairs)} jobs)')
        else:
            tar = stage / 'inputs.tar.gz'
            _tar_dirs(items, tar)
            _remote(f'mkdir -p "$HOME/{stage_remote}"\nrm -rf "$HOME/{stage_remote}"/*\n', stage / 'mkdir.log')
            with (stage / 'upload.log').open('wb') as f:
                r = subprocess.run([_scp, '-o', 'BatchMode=yes', '-i', CFG['ssh_key'], str(tar),
                                    CFG['host'] + ':' + stage_remote + '/inputs.tar.gz'], stdout=f, stderr=subprocess.STDOUT)
            if r.returncode:
                raise RuntimeError('upload failed')
            _remote(f'cd "$HOME/{stage_remote}"\ntar -xzmf inputs.tar.gz\n', stage / 'untar.log')
            pairs = sorted(_submit_remote(stage_remote, items, stage / 'submit.log').items())
        assert len(pairs) == 24, f'expected 24 submissions, got {len(pairs)}'
        jobs = [{'name': n, 'job_id': j} for n, j in pairs]
        kr['jobs'] = jobs
        kr['rounds'] = [{'round': 1, 'jobs': jobs}]
        step['status'] = 'waiting_run'
        step['note'] = f'round 1: submitted {len(jobs)} Cu defect relaxations ({DEFECT_PPN} ranks each)'
        return step['note']
    stage_remote = kr.get('stage_remote', stage_remote)
    names = ','.join(j['job_id'] for j in jobs)
    out = _remote(f'sacct -X -n -P -j {names} --format=JobIDRaw,State,ExitCode\n', stage / 'accounting.log')
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
        records[j['name']] = _collect_one(stage / 'collected' / j['name'], stage_remote, j['name'], j['job_id'], stage / 'download.log')
    if not terminal:
        step['note'] = f'round {len(kr.get("rounds", []))}: {len(records)}/24 collected, waiting for the rest'
        return step['note']
    unconverged = [n for n, r in records.items() if not r['ionic_converged']]
    bad = {n: r['issues'] for n, r in records.items() if r['issues']}
    if bad:
        raise RuntimeError(f'protocol checks failed: {bad}')
    if unconverged and len(kr.get('rounds', [])) < 3:
        rtag = f'resume{len(kr.get("rounds", []))}'
        ritems = []
        for name in unconverged:
            sdir = stage / 'collected' / name
            dst = stage / rtag / name
            dst.mkdir(parents=True, exist_ok=True)
            order, natoms = _species_of(sdir / 'POSCAR')
            moments = v2.b.moments(sdir / 'OUTCAR', natoms)
            write(dst / 'POSCAR', (sdir / 'CONTCAR').read_text())
            write(dst / 'INCAR', defect_incar(moments, 'relax', order,
                                             comment='# STAGE: continuation relax (ISIF=3) after NSW was exhausted'))
            write(dst / 'KPOINTS', (sdir / 'KPOINTS').read_text())
            write(dst / 'job.pbs', job_pbs(f'CuRr_{name}', DEFECT_PPN, DEFECT_MEM))
            ritems.append((name, dst))
        rtar = stage / f'{rtag}.tar.gz'
        _tar_dirs(ritems, rtar)
        rremote = REMOTE + f'/{rtag}'
        _remote(f'mkdir -p "$HOME/{rremote}"\nrm -rf "$HOME/{rremote}"/*\n', stage / f'{rtag}_mkdir.log')
        with (stage / f'{rtag}_upload.log').open('wb') as f:
            r = subprocess.run([_scp, '-o', 'BatchMode=yes', '-i', CFG['ssh_key'], str(rtar),
                                CFG['host'] + ':' + rremote + '/inputs.tar.gz'], stdout=f, stderr=subprocess.STDOUT)
        if r.returncode:
            raise RuntimeError(f'{rtag} upload failed')
        _remote(f'cd "$HOME/{rremote}"\ntar -xzmf inputs.tar.gz\n', stage / f'{rtag}_untar.log')
        got = _submit_remote(rremote, ritems, stage / f'{rtag}_submit.log')
        jobs = [{'name': n, 'job_id': j} for n, j in sorted(got.items())]
        kr['jobs'] = jobs
        kr['stage_remote'] = rremote
        kr['records'] = {k: v for k, v in records.items() if k not in unconverged}
        kr.setdefault('rounds', []).append({'round': len(kr['rounds']) + 1, 'resumed': unconverged, 'jobs': jobs})
        step['status'] = 'waiting_run'
        step['note'] = f'round {len(kr["rounds"])}: resubmitted {len(jobs)} unconverged relaxations {unconverged}'
        return step['note']
    if unconverged:
        raise RuntimeError(f'still unconverged after {len(kr.get("rounds", []))} rounds: {unconverged}')
    step['status'] = 'done'
    kr['job_ids'] = {n: r['job_id'] for n, r in records.items()}
    step['note'] = 'all 24 Cu defect relaxations converged and verified (U convention + NKPTS + ISMEAR per OUTCAR)'
    return step['note']


# --------------------------------------------------------------------------- step 3
def statics(state, step):
    stage = D / 'statics'
    kr = step.setdefault('key_results', {})
    stage_remote = REMOTE + '/statics'
    rel = D / 'defect_relax' / 'collected'
    all_names = ['parent_static'] + [f'{l}_{b}' for l in LABELS for b in BRANCHES]
    pd = stage / 'parent_static'
    if not (pd / 'POSCAR').exists():
        pcont = D / 'parent_relax' / 'collected' / 'CONTCAR'
        if pcont.exists():
            order, natoms = _species_of(pcont)
            write(pd / 'POSCAR', pcont.read_text())
            write(pd / 'INCAR', defect_incar(v2.b.moments(D / 'parent_relax' / 'collected' / 'OUTCAR', natoms), 'static', order))
            write(pd / 'KPOINTS', KPOINTS_TEXT)
            write(pd / 'job.pbs', job_pbs('Cu_parent_static', DEFECT_PPN, '24G'))
    for lab in LABELS:
        for br in BRANCHES:
            name = f'{lab}_{br}'
            dst, src_dir = stage / name, rel / name
            if (dst / 'POSCAR').exists() or not (src_dir / 'CONTCAR').exists():
                continue
            order, natoms = _species_of(src_dir / 'POSCAR')
            write(dst / 'POSCAR', (src_dir / 'CONTCAR').read_text())
            write(dst / 'INCAR', defect_incar(v2.b.moments(src_dir / 'OUTCAR', natoms), 'static', order))
            write(dst / 'KPOINTS', (src_dir / 'KPOINTS').read_text())
            write(dst / 'job.pbs', job_pbs(f'Cus_{name}', DEFECT_PPN, '24G'))
    items = [(n, stage / n) for n in all_names if (stage / n / 'POSCAR').exists()]
    submitted = _read_submission(stage_remote, stage / 'existing.log') if items else {}
    todo = [(n, dd) for n, dd in items if n not in submitted]
    if todo:
        if not ALLOW_SUBMIT:
            step['note'] = '[statics] inputs ready, submission held: set V2_ALLOW_SUBMIT=1 to release'
            return step['note']
        stage.mkdir(parents=True, exist_ok=True)
        tar = stage / 'inputs.tar.gz'
        _tar_dirs(todo, tar)
        _remote(f'mkdir -p "$HOME/{stage_remote}"\n', stage / 'mkdir.log')
        with (stage / 'upload.log').open('wb') as f:
            r = subprocess.run([_scp, '-o', 'BatchMode=yes', '-i', CFG['ssh_key'], str(tar),
                                CFG['host'] + ':' + stage_remote + '/inputs.tar.gz'], stdout=f, stderr=subprocess.STDOUT)
        if r.returncode:
            raise RuntimeError('statics upload failed')
        _remote(f'cd "$HOME/{stage_remote}"\ntar -xzmf inputs.tar.gz\n', stage / 'untar.log')
        submitted = _submit_remote(stage_remote, todo, stage / 'submit.log') or submitted
    jobs = [{'name': n, 'job_id': j} for n, j in sorted(submitted.items())]
    kr['jobs'] = jobs
    kr['prepared'] = sorted(n for n, _ in items)
    records = kr.setdefault('records', {})
    failed = {}
    if jobs:
        names = ','.join(j['job_id'] for j in jobs)
        out = _remote(f'sacct -X -n -P -j {names} --format=JobIDRaw,State,ExitCode\n', stage / 'accounting.log')
        status = {}
        for line in out.splitlines():
            a = line.split('|')
            if len(a) >= 3 and a[0].isdigit():
                status[a[0]] = (a[1], a[2])
        for j in jobs:
            st = status.get(j['job_id'])
            if st is None or st[0] in ('PENDING', 'RUNNING', 'COMPLETING', 'CONFIGURING'):
                continue
            if st[0] != 'COMPLETED' or st[1] != '0:0':
                failed[j['name']] = st     # collected below as a resubmission candidate
                continue
            if j['name'] in records:
                continue
            records[j['name']] = _collect_one(stage / 'collected' / j['name'], stage_remote, j['name'], j['job_id'], stage / 'download.log')
    bad = {n: r['issues'] for n, r in records.items() if r['issues']}
    retries = kr.setdefault('retries', {})
    # Neither a scheduler failure nor an exhausted SCF loop is a protocol violation, so
    # offenders are rerun instead of stopping collection.  Ladder (max two extra tries):
    #   attempt 2: NELM 100 -> 240
    #   attempt 3: NELM 240 + conservative charge/spin mixing (the O-vacancy cells with an
    #              odd electron count slosh badly; one of them also crashed Slurm twice)
    def rung(name):
        r = retries.get(name, 0)
        return {'nelm': 240, 'mix': r >= 1, 'attempt': r + 2}

    retry = {n: {'why': 'scf', 'issues': iss, **rung(n)} for n, iss in bad.items()
             if set(iss) <= {'electronic_converged'} and retries.get(n, 0) < 2}
    retry.update({n: {'why': 'scheduler', 'state': s, **rung(n)} for n, s in failed.items()
                  if retries.get(n, 0) < 2})
    if retry:
        for name in sorted(retry):
            dst, src_dir = stage / name, rel / name
            order, natoms = _species_of(src_dir / 'POSCAR')
            why = retry[name]['why']
            comment = ('# STAGE: static retry, NELM 240 (EDIFF 1E-5 not reached in 100 steps)' if why == 'scf'
                       else f"# STAGE: static retry after scheduler state {retry[name]['state']}")
            if retry[name]['mix']:
                comment += ', conservative charge/spin mixing'
            text = defect_incar(v2.b.moments(src_dir / 'OUTCAR', natoms), 'static', order,
                                nelm=retry[name]['nelm'], comment=comment)
            if retry[name]['mix']:
                text = text.replace('NELM    = 240', 'NELM    = 240\nALGO    = Normal\n'
                                                    'AMIX    = 0.2\nBMIX    = 0.0001\n'
                                                    'AMIX_MAG = 0.8\nBMIX_MAG = 0.0001')
            write(dst / 'INCAR', text)
            # Keep the failed run's logs (vasp.out / scheduler-*.err / OSZICAR) so a repeated
            # failure can be diagnosed; VASP overwrites its own files on the restart.
            _remote(f'''cd "$HOME/{stage_remote}/{name}"
mkdir -p prev
for f in *; do
  case " POSCAR INCAR KPOINTS job.pbs POTCAR prev " in *" $f "*) continue;; esac
  mv -f "$f" prev/ 2>/dev/null || rm -rf "$f"
done
''', stage / 'retry_archive.log')
            with (stage / 'retry_upload.log').open('ab') as f:
                r = subprocess.run([_scp, '-o', 'BatchMode=yes', '-i', CFG['ssh_key'],
                                    str(dst / 'INCAR'), CFG['host'] + f':{stage_remote}/{name}/INCAR'],
                                   stdout=f, stderr=subprocess.STDOUT)
            if r.returncode:
                raise RuntimeError(f'{name}: retry INCAR upload failed')
            got = _submit_remote(stage_remote, [(name, dst)], stage / 'retry_submit.log')
            if name not in got:
                raise RuntimeError(f'{name}: retry sbatch did not report a job id ({got})')
            for j in kr['jobs']:
                if j['name'] == name:
                    j['job_id'] = got[name]
            records.pop(name, None)
            retries[name] = retries.get(name, 0) + 1
            print(f'[statics] {name}: {why} retry attempt {retry[name]["attempt"]} -> job {got[name]} '
                  f'(NELM={retry[name]["nelm"]}{" + mixing" if retry[name]["mix"] else ""})', flush=True)
        jobs = kr['jobs']
        step['status'] = 'waiting_run'
        step['note'] = f'{len(records)}/25 collected; retried {sorted(retry)} {[(n, retry[n]["why"]) for n in sorted(retry)]}'
        return step['note']
    if bad or failed:
        raise RuntimeError(f'static protocol checks failed: models={bad} scheduler={failed}')
    if len(records) == len(all_names) == 25:
        step['status'] = 'done'
        step['note'] = '25/25 Cu statics completed and verified (U convention, ISMEAR=-5, NKPTS=13)'
        return step['note']
    step['status'] = 'waiting_run'
    step['note'] = (f'{len(records)}/25 collected; {len(items)}/25 prepared; {len(jobs)} submitted'
                    + (f'; still missing relaxations for '
                       f'{[n for n in all_names if n not in [x for x, _ in items]]}' if len(items) < 25 else ''))
    return step['note']


# --------------------------------------------------------------------------- step 4
def _plot_cu(rows, mu_o, mu_n, e_parent, out_dir):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib import font_manager
    available = {f.name for f in font_manager.fontManager.ttflist}
    font = next((f for f in ['Microsoft YaHei', 'SimHei', 'Noto Sans CJK SC'] if f in available), 'DejaVu Sans')
    plt.rcParams.update({'font.family': font, 'axes.unicode_minus': False, 'font.size': 11})
    order = LABELS
    data = {br: [next(r for r in rows if r['site'] == lab and r['branch'] == br) for lab in order] for br in BRANCHES}
    fig, ax = plt.subplots(figsize=(12, 6))
    for br, label, color, marker, off in [('O-van', 'O 空位', '#315d88', 'o', -18), ('N-O', 'N 取代 O', '#d47934', 's', 12)]:
        y = [r['formation_eV'] for r in data[br]]
        ax.plot(range(12), y, color=color, marker=marker, lw=1.6, ms=6, label=label)
        for i, v in enumerate(y):
            ax.annotate(f'{v:.3f}', (i, v), xytext=(0, off), textcoords='offset points', ha='center', fontsize=8.5,
                        color=color, zorder=5,
                        bbox=dict(boxstyle='round,pad=0.12', fc='white', ec='none', alpha=0.82))
    ax.set_xticks(range(12), order, rotation=40, ha='right')
    ax.set_xlabel('位点'); ax.set_ylabel('缺陷形成能（eV）')
    ax.set_title('Cu 替代体系（约定 +U 重算）：O 空位与 N 取代 O 的形成能', pad=16)
    ax.grid(axis='y', alpha=.2); ax.spines[['top', 'right']].set_visible(False)
    ax.margins(y=.22); ax.legend(frameon=False)
    fig.text(.5, .018, r'元素参考：$\mu_\mathrm{O}=\frac{1}{2}E(\mathrm{O_2})$，$\mu_\mathrm{N}=\frac{1}{2}E(\mathrm{N_2})$；'
                      r'DFT+U：Ti 5.2 / Mn 3.9 / Fe 4.0 / Ni 6.2 / Cu 1.9 eV；未加经验修正、零点能及温度修正',
             ha='center', fontsize=9, color='#555555')
    fig.tight_layout(rect=[0, .05, 1, 1])
    fig.savefig(out_dir / 'defect_formation_comparison.png', dpi=300)
    fig.savefig(out_dir / 'defect_formation_comparison.svg')
    plt.close(fig)


def energies(state, step):
    kr = step.setdefault('key_results', {})
    if step['status'] != 'pending':
        return step['note']
    srec = next(s for s in state['steps'] if s['name'] == 'statics')['key_results']['records']
    o2 = json.loads((ROOT / 'workflows' / 'oxygen_formation_refs_20261015' / '00_references' / 'reference_results.json').read_text())['references']['O2_static']['energy_eV']
    n2 = json.loads((ROOT / 'workflows' / 'nitrogen_formation_ref_20261015' / '00_reference' / 'reference_results.json').read_text())['references']['N2_static']['energy_eV']
    mu_o, mu_n = o2 / 2.0, n2 / 2.0
    e_parent = srec['parent_static']['sigma0_eV']
    rows = []
    for lab in LABELS:
        for br in BRANCHES:
            r = srec[f'{lab}_{br}']
            ef = r['sigma0_eV'] - e_parent + mu_o - (mu_n if br == 'N-O' else 0.0)
            rmag = v2._total_magnetization(D / 'defect_relax' / 'collected' / f'{lab}_{br}' / 'OUTCAR')
            smag = v2._total_magnetization(D / 'statics' / 'collected' / f'{lab}_{br}' / 'OUTCAR')
            rows.append({'site': lab, 'branch': br, 'defect_energy_eV': r['sigma0_eV'], 'formation_eV': ef,
                         'job_id': r['job_id'], 'relax_total_moment_uB': rmag, 'static_total_moment_uB': smag,
                         'moment_shift_uB': (None if (rmag is None or smag is None) else round(smag - rmag, 4)),
                         'u_applied': r['u_applied']})
    out_dir = ROOT / 'defect_formation_comparison_cu'
    out_dir.mkdir(exist_ok=True)
    payload = {'u_convention': CONVENTION, 'parent_static_eV': e_parent,
               'references': {'O2_static_eV': o2, 'N2_static_eV': n2, 'mu_O_eV': mu_o, 'mu_N_eV': mu_n,
                              'source': 'shared molecular references (LDAU=.FALSE., unaffected by the U correction)'},
               'formulas': {'O-vacancy': 'E(O35) - E(parent) + 0.5 E(O2)',
                            'N-substitution': 'E(N1O35) - E(parent) + 0.5 E(O2) - 0.5 E(N2)'},
               'sites': rows}
    (out_dir / 'formation_energies.json').write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding='utf-8')
    with (out_dir / 'formation_energies.csv').open('w', encoding='utf-8-sig', newline='') as f:
        w = csv.DictWriter(f, fieldnames=['site', 'branch', 'defect_energy_eV', 'formation_eV', 'job_id',
                                          'relax_total_moment_uB', 'static_total_moment_uB', 'moment_shift_uB'])
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k) for k in w.fieldnames})
    _plot_cu(rows, mu_o, mu_n, e_parent, out_dir)
    from PIL import Image
    with Image.open(out_dir / 'defect_formation_comparison.png') as im:
        im.verify()
    kr['formation'] = rows
    kr['mu_O_eV'], kr['mu_N_eV'] = mu_o, mu_n
    kr['parent_static_eV'] = e_parent
    best = {br: min((r for r in rows if r['branch'] == br), key=lambda r: r['formation_eV']) for br in BRANCHES}
    step['status'] = 'done'
    step['note'] = ('Cu formation energies + figure written; ' +
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


v2.wf._STEP_HANDLERS['cu'] = handle
v2.wf.WF_TEMPLATES['cu_campaign'] = [
    {'name': 'parent_relax', 'type': 'cu'},
    {'name': 'defect_inputs', 'type': 'cu'},
    {'name': 'defect_relax', 'type': 'cu'},
    {'name': 'statics', 'type': 'cu'},
    {'name': 'energies', 'type': 'cu'},
]

if __name__ == '__main__':
    state = v2.wf._load_state(WFID, PROJECT)
    if state is None:
        state = {'schema_version': 1, 'wf_id': WFID, 'template': 'cu_campaign', 'project': PROJECT,
                 'status': 'running', 'revision': 0, 'created': time.strftime('%Y-%m-%d %H:%M:%S'),
                 'params': {'node': 'bkzhang', 'u_convention': CONVENTION,
                            'reason': 'mirror of the v2 V campaign so Cu and V are comparable'},
                 'current': 0,
                 'steps': [{'name': n, 'type': 'cu', 'status': 'pending', 'key_results': {}, 'note': ''}
                           for n in ['parent_relax', 'defect_inputs', 'defect_relax', 'statics', 'energies']]}
        v2.wf._save_state(state)
    print(v2.wf.advance_workflow(WFID, PROJECT, expected_revision=state['revision']))
