"""Assemble the lean VASP data package for the 024_CuFeMn campaigns.

Campaign is selected by VCALC_CAMPAIGN:
  v2  V series recomputed with the agreed +U convention (Ni 6.2 / Mn 3.9 / Fe 4.0)
  cu  Cu series with the same convention and the same protocol, so its formation
      energies are directly comparable with v2
  v1  the superseded first campaign whose per-element U mapping was wrong

Only six file names are kept from every calculation directory:
    INCAR, KPOINTS, POSCAR, CONTCAR, OUTCAR, XDATCAR

Groups by run type:
  relax/parent/                 parent cell relaxation (ISIF=3, 64 atoms)
  relax/defects/<L>/<B>/        24 defect relaxations
  relax/resume_VMnTi_O-van/     continuation relaxation of the unconverged case
  relax/references/             O2_relax, N2_relax
  static/defects/<L>/<B>/       24 unified static single points (bkzhang)
  static/references/            parent_static, O2_static, N2_static
  results/                      formation energies, plots, audit reports

Everything else (OSZICAR, vasp.out, DOSCAR, PROCAR, EIGENVAL, IBZKPT, REPORT,
vasprun.xml, INCAR_static, POTCAR, WAVECAR, CHG) is left out; see README.
"""
from __future__ import annotations
import csv,json,os,re,shutil,zipfile
from pathlib import Path
import run_bk_unified as b
from pymatgen.io.vasp.inputs import Poscar
ROOT=b.ROOT
PKG=Path(os.environ.get('VCALC_PACKAGE_DIR') or ROOT/'package')
BRANCHES=['N-O','O-van']
LABELS_V=['VMnTi','VNiMn','VTiNi','FeTiNi','MnFeNi','MnFeTi','MnMnV','MnMnFe','MnMnMn','MnMnNi','MnTiNi','TiMnMn']
LABELS_CU=['CuMnTi','CuNiMn','CuTiNi','FeTiNi','MnFeNi','MnFeTi','MnMnCu','MnMnFe','MnMnMn','MnMnNi','MnTiNi','TiMnMn']
REFS=[('parent_static',ROOT/'workflows/oxygen_formation_refs_20261015/00_references/collected/parent_static'),
      ('O2_relax',ROOT/'workflows/oxygen_formation_refs_20261015/00_references/collected/O2_relax'),
      ('O2_static',ROOT/'workflows/oxygen_formation_refs_20261015/00_references/collected/O2_static'),
      ('N2_relax',ROOT/'workflows/nitrogen_formation_ref_20261015/00_reference/collected/N2_relax'),
      ('N2_static',ROOT/'workflows/nitrogen_formation_ref_20261015/00_reference/collected/N2_static')]
KEEP={'INCAR','KPOINTS','POSCAR','CONTCAR','OUTCAR','XDATCAR','XDATCAR.reconstructed'}
TOTEN=re.compile(r'free\s+energy\s+TOTEN\s*=\s*(-?\d+\.\d+)\s*eV')
SIGMA0=re.compile(r'energy\(sigma->0\)\s*=\s*([-+\d.Ee]+)')

# --------------------------------------------------------------------------- #
# campaign selection:
#   'cu' = the agreed +U Cu campaign (same protocol as v2, formation energies
#          directly comparable with the V series)
#   'v2' = the agreed +U convention (Ni 6.2 / Mn 3.9 / Fe 4.0, V 3.25)
#   'v1' = the superseded first campaign whose per-element U mapping was wrong
# --------------------------------------------------------------------------- #
CAMPAIGN=os.environ.get('VCALC_CAMPAIGN','v1')
assert CAMPAIGN in ('v1','v2','cu'), f'unknown campaign: {CAMPAIGN}'
V2=ROOT/'workflows'/'v2_u_convention_20261016'/'00_v2'
CU=ROOT/'workflows'/'cu_u_convention_20261017'/'00_cu'
if CAMPAIGN=='v2':
 LABELS=LABELS_V
 PKG_NAME='024_CuFeMn_V_VASP_data'
 RELAX_PARENT_SRC=V2/'parent_relax'/'collected'
 RELAX_DEFECT_SRC=V2/'defect_relax'/'collected'
 RELAX_DEFECT_FLAT=True
 STATIC_PARENT_SRC=V2/'statics'/'collected'/'parent_static'
 STATIC_DEFECT_SRC=V2/'statics'/'collected'
 STATIC_DEFECT_FLAT=True
 STATIC_PARENT_NOTE='v2 parent static (agreed +U convention)'
 RESULTS_SRC=ROOT/'defect_formation_comparison_v2'
elif CAMPAIGN=='cu':
 LABELS=LABELS_CU
 PKG_NAME='024_CuFeMn_Cu_VASP_data'
 RELAX_PARENT_SRC=CU/'parent_relax'/'collected'
 RELAX_DEFECT_SRC=CU/'defect_relax'/'collected'
 RELAX_DEFECT_FLAT=True
 STATIC_PARENT_SRC=CU/'statics'/'collected'/'parent_static'
 STATIC_DEFECT_SRC=CU/'statics'/'collected'
 STATIC_DEFECT_FLAT=True
 STATIC_PARENT_NOTE='Cu parent static (agreed +U convention)'
 RESULTS_SRC=ROOT/'defect_formation_comparison_cu'
else:
 LABELS=LABELS_V
 PKG_NAME='024_CuFeMn_V_VASP_data'
 RELAX_PARENT_SRC=ROOT/'result'/'result'/'00_parent_relax'
 RELAX_DEFECT_SRC=ROOT/'result'/'result'/'stage2_defects'
 RELAX_DEFECT_FLAT=False
 STATIC_PARENT_SRC=ROOT/'workflows'/'oxygen_formation_refs_20261015'/'00_references'/'collected'/'parent_static'
 STATIC_DEFECT_SRC=ROOT/'workflows'/'bk_unified_returned_20261014'/'00_unified_batch'/'collected'
 STATIC_DEFECT_FLAT=False
 STATIC_PARENT_NOTE='first-campaign parent static'
 RESULTS_SRC=ROOT/'defect_formation_comparison'
STAGE=PKG/PKG_NAME
TITLE='024_CuFeMn_Cu' if CAMPAIGN=='cu' else '024_CuFeMn_V'
PARENT_FORMULA='Na10Ti2Mn10Fe1Cu1Ni4O36' if CAMPAIGN=='cu' else 'Na10Ti2Mn10Fe1V1Ni4O36'
POTCAR_LIST='Na_pv Ti_pv Mn_pv Fe_pv Cu_pv Ni_pv [N] O' if CAMPAIGN=='cu' else 'Na_pv Ti_pv Mn_pv Fe_pv V_pv Ni_pv [N] O'
VERIFY_SCRIPT='cu/verify_cu_defect_energies.py' if CAMPAIGN=='cu' else 'verify_defect_energies.py'


def defect_src(base:Path,flat:bool,label:str,branch:str,stage:str='')->Path:
 """v2 stores flat <label>_<branch> dirs; v1 stores <label>/<branch> (static: static/<l>/<b>)."""
 if flat:return base/f'{label}_{branch}'
 return (base/stage/label/branch) if stage else (base/label/branch)

def copy_tree(src:Path,dst:Path,report):
 dst.mkdir(parents=True,exist_ok=True)
 if not src.exists():report.append(('missing',str(src),0));return 0
 n=0
 for p in sorted(src.rglob('*')):
  if not p.is_file() or p.name not in KEEP:continue
  rel=p.relative_to(src)
  out=dst/rel
  if out.exists():continue
  out.parent.mkdir(parents=True,exist_ok=True)
  shutil.copy2(p,out);n+=1
 return n

def tail_energy(outcar:Path,pattern):
 if not outcar.exists():return None
 with outcar.open('rb') as f:
  f.seek(max(0,outcar.stat().st_size-300000));t=f.read().decode(errors='replace')
 m=pattern.findall(t)
 return float(m[-1]) if m else None

def composition(poscar:Path):
 """(species sequence, atom count) of a POSCAR.

 2026-10-20 fix: the old heuristic compared element *names* against a set of
 *characters*, so it never matched and the species/atoms columns of manifest.csv
 were always empty. Use pymatgen instead (VASP4 and VASP5 both fine).
 """
 if not poscar.exists():return '',0
 try:
  p=Poscar.from_file(str(poscar))
  return ''.join(p.site_symbols),sum(int(x) for x in p.natoms)
 except Exception:return '',0

def main():
 if STAGE.exists():shutil.rmtree(STAGE)
 STAGE.mkdir(parents=True)
 rows=[];report=[]
 extra=PKG/'remote_extra'/'extracted'
 merged=0
 for p in (extra.rglob('*') if CAMPAIGN=='v1' and extra.exists() else []):
  if not p.is_file():continue
  parts=p.relative_to(extra).parts
  while parts and parts[0]!='024_CuFeMn_V':parts=parts[1:]
  if not parts:
   print('unmapped remote file:',p);continue
  rest=Path(*parts[1:]);head=rest.parts[0];tail=Path(*rest.parts[2:])
  wf=ROOT/'workflows'
  cand=None
  if head=='stage3_unified_20261014' and rest.parts[1] in ('static','resume','static_guarded'):
   cand=wf/'bk_unified_returned_20261014/00_unified_batch/collected'/rest.parts[1]/tail
  elif head=='formation_refs_20261015':
   cand=wf/'oxygen_formation_refs_20261015/00_references/collected'/Path(*rest.parts[1:])
  elif head=='nitrogen_formation_ref_20261015':
   cand=wf/'nitrogen_formation_ref_20261015/00_reference/collected'/Path(*rest.parts[1:])
  if cand is None:
   print('unmapped remote file:',rest);continue
  cand.parent.mkdir(parents=True,exist_ok=True)
  shutil.copy2(p,cand);merged+=1
 print('merged remote extras:',merged)
 def add(group,label,branch,src,note=''):
  rel=Path(group)/label/branch if branch else Path(group)/label
  n=copy_tree(src,STAGE/rel,report)
  sp,nat=composition(STAGE/rel/'POSCAR')
  rows.append({'group':group,'label':label,'branch':branch,'path':str(rel).replace('\\','/'),
               'files':n,'species':sp,'atoms':nat,
               'toten_eV':tail_energy(STAGE/rel/'OUTCAR',TOTEN),
               'sigma0_eV':tail_energy(STAGE/rel/'OUTCAR',SIGMA0),'note':note})
 add('relax','parent','',RELAX_PARENT_SRC,f'parent relaxation, 64 atoms, ISIF=3 ({CAMPAIGN})')
 for lab in LABELS:
  for br in BRANCHES:
   add('relax/defects',lab,br,defect_src(RELAX_DEFECT_SRC,RELAX_DEFECT_FLAT,lab,br),f'defect relaxation, ISIF=3 ({CAMPAIGN})')
 if CAMPAIGN=='v1':
  add('relax','resume_VMnTi_O-van','',ROOT/'workflows/bk_unified_returned_20261014/00_unified_batch/collected/resume/VMnTi/O-van','continuation relaxation that reached ionic convergence (55 extra steps)')
 for lab in LABELS:
  for br in BRANCHES:
   if CAMPAIGN in ('v2','cu'):
    add('static/defects',lab,br,defect_src(STATIC_DEFECT_SRC,True,lab,br),f'unified static, NSW=0 ISIF=2 ISMEAR=-5 ({CAMPAIGN} +U)')
   elif (lab,br)==('VMnTi','O-van'):
    add('static/defects',lab,br,ROOT/f'workflows/bk_unified_returned_20261014/00_unified_batch/collected/static_guarded/{lab}/{br}','unified static on the resumed geometry (NSW=0 ISIF=2 ISMEAR=-5)')
   else:
    add('static/defects',lab,br,ROOT/f'workflows/bk_unified_returned_20261014/00_unified_batch/collected/static/{lab}/{br}','unified static, NSW=0 ISIF=2 ISMEAR=-5')
 for name,src in REFS:
  if name.endswith('_relax'):
   add('relax/references',name,'',src,'molecular reference relaxation')
  else:
   add('static/references',name,'',src,'reference total energy')
 results=RESULTS_SRC
 fe=STAGE/'results';fe.mkdir(parents=True,exist_ok=True)
 for p in sorted(results.iterdir()):
  if p.is_file():shutil.copy2(p,fe/p.name)
 shutil.copy2(ROOT/'defect_comparison_method.md',fe/'packaging_notes.md')
 shutil.copy2(ROOT/'U_CONVENTION_RECOMPUTE.md',fe/'U_CONVENTION_RECOMPUTE.md')
 if CAMPAIGN=='cu':
  shutil.copy2(ROOT/'cu'/'METHODS.md',STAGE/'METHODS.md')
  for name in ('cu_vs_v.json','cu_vs_v_comparison.csv','cu_vs_v_relative.csv','cu_data_findings.md'):
   src=ROOT/'cu'/name
   if src.exists():shutil.copy2(src,fe/name)
 else:
  shutil.copy2(ROOT/'METHODS.md',STAGE/'METHODS.md')
 provenance=[(ROOT/'workflows/oxygen_formation_refs_20261015/00_references/reference_results.json','O2_reference_results.json'),
             (ROOT/'workflows/nitrogen_formation_ref_20261015/00_reference/reference_results.json','N2_reference_results.json'),
             (RESULTS_SRC/'formation_energies.json','formation_energies.json')]
 if CAMPAIGN in ('v1','v2'):
  provenance += [(ROOT/'xdatcar_validation_summary.json','xdatcar_validation_summary.json'),
                 (ROOT/'xdatcar_fetch_summary.json','xdatcar_fetch_summary.json')]
 if CAMPAIGN=='v2':
  provenance.append((ROOT/'workflows/v2_u_convention_20261016/state.json','v2_workflow_state.json'))
 elif CAMPAIGN=='cu':
  provenance.append((ROOT/'workflows/cu_u_convention_20261017/state.json','cu_workflow_state.json'))
  provenance.append((ROOT/'cu'/'cu_results_audit.json','cu_results_audit.json'))
 else:
  provenance += [(ROOT/'workflows/bk_unified_returned_20261014/00_unified_batch/collection_status.json','defect_static_collection_status.json'),
                 (ROOT/'returned_results_audit.json','relaxation_audit.json'),
                 (ROOT/'returned_input_checks.json','relaxation_input_checks.json')]
 for src,dst in provenance:
  if src.exists():shutil.copy2(src,fe/dst)
 with (fe/'formation_energies.csv').open(encoding='utf-8-sig') as f:data=list(csv.DictReader(f))
 with (STAGE/'manifest.csv').open('w',encoding='utf-8-sig',newline='') as f:
  w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
 total=sum(p.stat().st_size for p in STAGE.rglob('*') if p.is_file())
 files=sum(1 for p in STAGE.rglob('*') if p.is_file())
 (STAGE/'README.md').write_text(readme(rows,data,report,total,files),encoding='utf-8')
 print('staged files:',files,'size MB:',round(total/1e6,1))
 missing=[r for r in report if r[0]=='missing']
 if missing:print('MISSING SOURCES:',missing)
 zip_path=PKG/f'{PKG_NAME}.zip'
 if zip_path.exists():zip_path.unlink()
 with zipfile.ZipFile(zip_path,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
  for p in sorted(STAGE.rglob('*')):
   if p.is_file():z.write(p,p.relative_to(PKG))
 print('zip MB:',round(zip_path.stat().st_size/1e6,1),zip_path)

def readme(rows,data,report,total,files):
 conf=json.loads((RESULTS_SRC/'formation_energies.json').read_text(encoding='utf-8'))
 if CAMPAIGN in ('v2','cu'):
  refs=conf['references']; e_parent=conf['parent_static_eV']
  mu_o,mu_n=refs['mu_O_eV'],refs['mu_N_eV']
  ndirs=sum(1 for r in rows if r['files'])
  parent_note='v2 重算' if CAMPAIGN=='v2' else 'Cu 母体'
  ref_lines=[f"- 母体静态 parent_static：**{e_parent:.8f} eV**（{parent_note}）",
             f"- O2 静态（沿用 v1 分子计算，`LDAU=.FALSE.`）：{refs['O2_static_eV']:.8f} eV",
             f"- N2 静态（同上）：{refs['N2_static_eV']:.8f} eV",
             f"- μO = {mu_o:.8f} eV，μN = {mu_n:.8f} eV"]
  if CAMPAIGN=='cu':
   u_line=('- DFT+U Dudarev（LDAUTYPE=2，UJ=0）：**Ti 5.2、Mn 3.9、Fe 4.0、Ni 6.2、Cu 1.9 eV**；Na/N/O 不加 U'
           '（本组约定；Cu 系列与 V 系列 v2 同协议、同赝势、同 k 网格、同分子参考态，形成能可直接横向比较）')
   xd=['','## XDATCAR','',
       f'- 全部 {ndirs} 个目录都带 **VASP 原生 `XDATCAR`**（结构优化为完整轨迹，静态单点为单帧），包内没有重建文件。',
       '- 母体与 24 个缺陷的轨迹全部来自 Cu 计算本身（bkzhang，VASP 6.6.0），没有从 `OUTCAR` 重建、也没有从别处补取。',
       '- 分子参考（O2/N2）的轨迹沿用第一轮的分子计算：分子计算未启用 +U，不受 U 约定影响。']
   header_extra=['','> 本包是 **Cu 系列**（约定 +U）的结果。与 V 系列 v2 同协议、同赝势、同 k 网格、',
                 '> 同 O2/N2 分子参考态，**形成能可直接与 V 系列横向比较**（见 `results/cu_vs_v_comparison.csv`）。']
  else:
   u_line=('- DFT+U Dudarev（LDAUTYPE=2，UJ=0）：**Ti 5.2、Mn 3.9、Fe 4.0、Ni 6.2、V 3.25 eV**；Na/N/O 不加 U'
           '（本组约定；v1 曾误用 Mn 6.2 / Fe 3.9 / Ni 4.0，故本包为按约定重算的 v2 结果）')
   xd=['','## XDATCAR','',
       f'- 全部 {ndirs} 个目录都带 **VASP 原生 `XDATCAR`**（结构优化为完整轨迹，静态单点为单帧），包内没有重建文件。',
       '- 母体与 24 个缺陷的轨迹全部来自 v2 计算本身（bkzhang，VASP 6.6.0），没有从 `OUTCAR` 重建、也没有从别处补取。',
       '- 分子参考（O2/N2）的轨迹沿用第一轮的分子计算：分子计算未启用 +U，不受本次约定修正影响。']
   header_extra=['','> 本包是 **v2**（按约定 +U 重算）的结果。第一轮（v1）因逐元素 U 映射错误已作废，',
                 '> 事故证据与重算说明见包内 `results/U_CONVENTION_RECOMPUTE.md`。']
  table=[('位点','O 空位','N 取代 O')]
  by=dict(((x['site'],x['branch']),x['formation_eV']) for x in conf['sites'])
  for site in LABELS:
   table.append((site,f"{by[(site,'O-van')]:.3f}",f"{by[(site,'N-O')]:.3f}"))
  schedule_note='- 本批计算全部在 bkzhang（Slurm）：母体 32 核、缺陷弛豫 16 核/作业、静态 16 核/作业。'
 else:
  r=conf['references']
  mu_o,mu_n=conf['mu_O_eV'],conf['mu_N_eV']
  ref_lines=[f"- 母体静态 parent_static：{r['parent_static']['energy_eV']:.8f}（作业 {r['parent_static']['job_id']}）",
             f"- O2 优化：{r['O2_relax']['energy_eV']:.8f}，静态：{r['O2_static']['energy_eV']:.8f}，键长 {r['O2_static']['bond_A']:.6f} Å",
             f"- N2 优化：{r['N2_relax']['energy_eV']:.8f}，静态：{r['N2_static']['energy_eV']:.8f}，键长 {r['N2_static']['bond_A']:.6f} Å",
             f"- μO = {mu_o:.8f}，μN = {mu_n:.8f}"]
  u_line=('- DFT+U Dudarev（LDAUTYPE=2，UJ=0）：Ti 5.2、Mn 6.2、Fe 3.9、V 3.25、Ni 4.0 eV；Na/N/O 不加 U'
          '（⚠️ 该组取值偏离本组约定，见 `results/U_CONVENTION_RECOMPUTE.md`）')
  xd=['','## XDATCAR','',
      '- 全部 55 个目录都带 VASP 原生 `XDATCAR`（结构优化为完整轨迹，静态单点为单帧），包内没有重建文件。',
      '- 其中 22 个原件（`relax/parent/` 加 21 个缺陷优化）是从 bkzhang 的 `00_parent_relax/` 与 `stage2_defects/` 取回的：那批返回数据当初只带了 INCAR/KPOINTS/POSCAR/CONTCAR/OUTCAR。',
      '- 取回后逐个与同目录 `OUTCAR` 的逐步记录核对：25 个优化目录帧数完全一致，晶格偏差 ≤5.0e-7 Å、分数坐标偏差 ≤8.9e-7。明细见 `results/xdatcar_validation_summary.json`。']
  table=[('位点','O 空位','N 取代 O')]
  for x in conf['sites']:
   table.append((x['site'],f"{x['O_vacancy_formation_eV']:.3f}",f"{x['N_substitution_formation_eV']:.3f}"))
  header_extra=[]
  schedule_note='- 母体与 21 个缺陷弛豫在 bkzhang；另 3 个弛豫在另一台集群（见 `results/relaxation_audit.json`）。'
 lines=[f'# {TITLE} VASP 数据包（精简版）','',
  f'共 {files} 个文件，解压前约 {total/1e6:.0f} MB。**每个计算目录只保留 6 个文件**：',
  '`INCAR`、`KPOINTS`、`POSCAR`、`CONTCAR`、`OUTCAR`、`XDATCAR`。']
 lines+=header_extra
 lines+=['','按计算类型分成两组：','',
  '| 目录 | 内容 |','|---|---|',
  f'| `relax/parent/` | 母体 {PARENT_FORMULA} 结构优化（64 原子，ISIF=3） |',
  '| `relax/defects/<位点>/<分支>/` | 24 个缺陷结构优化（ISIF=3） |',
  '| `relax/references/O2_relax`、`N2_relax/` | O2、N2 分子结构优化 |',
  '| `static/defects/<位点>/<分支>/` | 24 个缺陷静态单点（NSW=0, IBRION=-1, ISIF=2, ISMEAR=-5） |',
  '| `static/references/` | parent_static、O2_static、N2_static |',
  '| `results/` | 形成能 CSV/JSON、对比图 PNG/SVG、方法说明、重算说明与溯源（非 VASP 输出） |','',
  '根目录 `METHODS.md` 是完整的计算方法。`<分支>` 为 `N-O`（N 取代 O）或 `O-van`（单纯 O 空位）；位点是 12 个局部环境标签，',
  '缺陷目录共 24 个 = 12 位点 × 2 分支，`relax/` 与 `static/` 下同名对应。','',
  '## 计算参数（全部目录一致）','',
  f'- VASP 6.6.0，PAW_PBE（`{POTCAR_LIST}`），ENCUT 520 eV，EDIFF 1E-5，ISPIN 2，IVDW=11（DFT-D3）',
  u_line,
  '- KPOINTS：Γ 中心 5×5×1（13 个不可约 k 点），ISMEAR=-5；LREAL=.FALSE.，LASPH=.FALSE.，ISYM=2，NCORE=4',
  '- 静态单点：NSW=0，IBRION=-1，ISIF=2，LWAVE=LCHARG=.FALSE.；分子参考 O2/N2 为 15 Å 盒、Γ 单点、ISMEAR=0 SIGMA=0.01',
  schedule_note,'',
  '## 参考能量（eV）','']
 lines+=ref_lines
 lines+=['','## 形成能公式','',
  '```',
  'Ef(O 空位)     = E(O35)   - E(parent O36) + 0.5 E(O2)',
  'Ef(N 取代 O)   = E(N1O35) - E(parent O36) + 0.5 E(O2) - 0.5 E(N2)',
  '```','',
  '中性缺陷；采用元素分子参考的原始 PBE-D3 能量，未加经验氧分子修正、零点能或有限温度修正。','',
  '## 形成能（eV）','',
  '| 位点 | O 空位 | N 取代 O |','|---|---:|---:|']
 for site,ov,nn in table[1:]:
  lines.append(f'| {site} | {ov} | {nn} |')
 lines+=xd
 lines+=['','## 未包含的文件','',
  '- 按精简要求每个目录只保留上述 6 类文件，因此**不含** `OSZICAR`、`vasp.out`、`DOSCAR`、`EIGENVAL`、`IBZKPT`、`REPORT`、`vasprun.xml`、`INCAR_static`、调度日志等。',
  f'- `POTCAR`：赝势版权库，按项目规矩不随包分发；可用 `potcars/potpaw_PBE` 按 `{POTCAR_LIST}` 顺序重建。',
  '- `PROCAR`、`WAVECAR`、`CHG/CHGCAR`：体积过大未包含。',
  '- 未入包的文件在本地 `server/outputs/024_CuFeMn_V/` 下按工作流目录保留，需要时可直接取用。','',
  '## 其他说明','',
  '- 各目录 `toten_eV`/`sigma0_eV` 见 `manifest.csv`；形成能用的是 `energy(sigma->0)`。',
  f'- 交付前用 `{VERIFY_SCRIPT}` 独立复核过：逐 OUTCAR 校验 +U 元素对应，并从静态 `OUTCAR` 重算全部形成能。',
  '- 固体静态电子收敛不保证磁性全局基态，位点间接近的能量差需谨慎解释。','']
 return '\n'.join(lines)

if __name__=='__main__':main()
