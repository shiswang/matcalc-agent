"""Project-scoped batch handler; all state advancement uses advance_workflow."""
from pathlib import Path
import sys,json,re,tarfile,subprocess,hashlib,time
sys.path.insert(0,str(Path(__file__).resolve().parent))
from campaign_paths import DATA_ROOT as ROOT, REPO
sys.path.insert(0,str(REPO/'server'))
from matcalc import workflows as wf
from pymatgen.io.vasp.inputs import Incar,Poscar
class _NodeCfg:
    """clusters.json 里某个节点的配置，按需读取。

    导入模块时**不**读 clusters.json：CI / 离线环境只有占位配置（节点名不是 bkzhang），
    那里 import 驱动不应该失败——真正提交作业时才会用到配置，那时才报"缺少该节点"。
    """

    def __init__(self, key: str):
        self._key = key
        self._data: dict = {}
        self._loaded = False

    def _load(self) -> dict:
        if not self._loaded:
            nodes = json.loads((REPO / 'clusters.json').read_text(encoding='utf-8'))['nodes']
            if self._key not in nodes:
                raise KeyError(
                    f"clusters.json 里没有 {self._key!r} 节点（现有: {sorted(nodes)}）；"
                    f"提交作业前请补上该节点配置"
                )
            self._data = nodes[self._key]
            self._loaded = True
        return self._data

    def __getitem__(self, k):
        return self._load()[k]

    def get(self, k, default=None):
        return self._load().get(k, default)

    def __contains__(self, k):
        return k in self._load()

    def keys(self):
        return self._load().keys()

    def items(self):
        return self._load().items()

    def values(self):
        return self._load().values()

    def __repr__(self):
        return repr(self._load())

CFG=_NodeCfg('bkzhang')
PROJECT='024_CuFeMn_V'
WFID='bk_unified_returned_20261014'
NAME='unified_batch'
REMOTE='matcalc/024_CuFeMn_V/stage3_unified_20261014'
SSH=r'C:\Windows\System32\OpenSSH\ssh.exe'
SCP=r'C:\Windows\System32\OpenSSH\scp.exe'
BASE=ROOT/'result'/'result'/'stage2_defects'
EXPECTED={'Na':0,'Ti':5.2,'Mn':6.2,'Fe':3.9,'V':3.25,'Ni':4,'N':0,'O':0}
def remote(script,log):
 p=Path(log);p.parent.mkdir(parents=True,exist_ok=True)
 with p.open('wb') as out:
  r=subprocess.run([SSH,'-T','-o','BatchMode=yes','-o','ConnectTimeout=20','-i',CFG['ssh_key'],CFG['host'],r"tr -d '\r' | bash -s"],input=script.encode(),stdout=out,stderr=subprocess.STDOUT)
 if r.returncode:raise RuntimeError(f'SSH failed {r.returncode}; see {p}')
 return p.read_text(encoding='utf-8',errors='replace')
def moments(out,n):
 with out.open('rb') as f:
  f.seek(max(0,out.stat().st_size-100000));t=f.read().decode(errors='replace')
 b=t.rsplit('magnetization (x)',1)[-1]
 vals=[]
 for l in b.splitlines():
  a=l.split()
  if len(a)==5 and a[0].isdigit():vals.append(float(a[-1]))
  if len(vals)==n:break
 if len(vals)!=n:raise ValueError(f'Missing moments {out}')
 return vals

def prepare(state,step):
 d=Path(wf._step_dir(WFID,PROJECT,0,NAME));d.mkdir(parents=True,exist_ok=True)
 audit=json.loads((ROOT/'returned_results_audit.json').read_text())
 manifest=[]
 for row in audit['defects']:
  label,branch=row['label'],row['branch'];src=BASE/label/branch
  stage='resume' if not row['ionic_converged'] else 'static'
  stages=[stage,'static_guarded'] if stage=='resume' else [stage]
  for st in stages:
   dst=d/st/label/branch;dst.mkdir(parents=True,exist_ok=True)
   pos=(src/'CONTCAR').read_text();p=Poscar.from_str(pos)
   inc=Incar.from_file(src/('INCAR' if st=='resume' else 'INCAR_static'))
   inc['MAGMOM']=moments(src/'OUTCAR',len(p.structure))
   inc['ISMEAR']=1 if st=='resume' else -5
   inc['LWAVE']=False;inc['LCHARG']=False
   inc['NSW']=200 if st=='resume' else 0
   inc['IBRION']=2 if st=='resume' else -1
   inc['ISIF']=3 if st=='resume' else 2
   assert dict(zip(p.site_symbols,inc['LDAUU']))=={s:EXPECTED[s] for s in p.site_symbols}
   assert len(inc['MAGMOM'])==len(p.structure)
   assert all(len(inc[k])==len(p.site_symbols) for k in ['LDAUL','LDAUU','LDAUJ'])
   (dst/'POSCAR').write_text(pos,encoding='utf-8',newline='\n')
   (dst/'INCAR').write_text(str(inc),encoding='utf-8',newline='\n')
   (dst/'KPOINTS').write_text((src/'KPOINTS').read_text(),encoding='utf-8',newline='\n')
   guard=''
   if st=='static_guarded':
    guard='''RESUME="$SLURM_SUBMIT_DIR/../../../resume/VMnTi/O-van"
grep -q 'reached required accuracy' "$RESUME/OUTCAR" || { echo 'RESUME_NOT_CONVERGED'; exit 42; }
grep -q 'General timing and accounting informations' "$RESUME/OUTCAR" || exit 43
cp "$RESUME/CONTCAR" POSCAR
MOM=$(awk '/magnetization \\(x\\)/ {v=""; active=1; next} active && $1 ~ /^[0-9]+$/ && NF==5 {v=v " " $5} active && $1=="tot" {last=v;active=0} END {print last}' "$RESUME/OUTCAR")
[ "$(echo "$MOM" | wc -w)" -eq 63 ] || exit 44
sed -i "s/^MAGMOM.*/MAGMOM = $MOM/" INCAR
'''
   job=f'''#!/bin/bash
#SBATCH -J V24_{st[:2]}_{label}_{branch.replace('-','')}
#SBATCH -p {CFG['queue']}
#SBATCH -A {CFG['account']}
#SBATCH -N 1
#SBATCH -n 16
#SBATCH --mem=24G
#SBATCH --time=48:00:00
#SBATCH -o scheduler-%j.out
#SBATCH -e scheduler-%j.err
set -euo pipefail
cd "$SLURM_SUBMIT_DIR"
{guard}
{CFG['vasp_setup']}
export OMP_NUM_THREADS=1
export MKL_NUM_THREADS=1
mpirun -np "$SLURM_NTASKS" {CFG['vasp_exe']} > vasp.out 2>&1
'''
   (dst/'job.pbs').write_text(job,encoding='utf-8',newline='\n')
   manifest.append({'stage':st,'label':label,'branch':branch,'directory':str(dst.relative_to(d)).replace('\\','/'),'species':p.site_symbols,'atoms':len(p.structure),'ISMEAR':inc['ISMEAR'],'source_converged':row['ionic_converged']})
 (d/'manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
 step['status']='waiting_submit';step['note']='25 input sets verified: 23 static, one resume, one guarded static; 16 ranks / 24G'
 return step['note']

def submit(state,step):
 d=Path(wf._step_dir(WFID,PROJECT,0,NAME))
 if step.get('submitted_job'):
  check=(ROOT/'_upload'/'bk_unified_check.sh').read_text(encoding='utf-8')
  output=remote(check,d/'latest_status.log')
  return collect(state,step,d)
 manifest=json.loads((d/'manifest.json').read_text())
 tar=d/'inputs.tar.gz'
 with tarfile.open(tar,'w:gz') as tf:
  for r in manifest:
   for fn in ['POSCAR','INCAR','KPOINTS','job.pbs']:
    f=d/r['directory']/fn;tf.add(f,arcname=f'{r["directory"]}/{fn}')
 script=f'''set -euo pipefail
P="$HOME/{REMOTE}"
mkdir -p "$P"
cd "$P"
[ ! -e submitted.tsv ] || {{ echo 'BATCH_ALREADY_SUBMITTED'; cat submitted.tsv; exit 0; }}
tar -xzmf inputs.tar.gz
LIB={CFG['local_potcar_lib']}
'''
 for r in manifest:
  potentials=[s+'_pv' if s in ['Na','Ti','Mn','Fe','V','Ni'] else s for s in r['species']]
  script+=f'cd "$P/{r["directory"]}"\ncat '+' '.join(f'"$LIB/{s}/POTCAR"' for s in potentials)+' > POTCAR\n'
  script+=f'[ "$(grep -c TITEL POTCAR)" -eq {len(potentials)} ]\n'
 expected_md5={'Na_pv':'5c9856f448bf380d5b3733e9f598a718','Ti_pv':'4b3e0513e5c0b0c044fb47ed7c80d8f9','Mn_pv':'94a1a1c4f5ec3f936c4cb7d46c6464bb','Fe_pv':'924ac02be178cfc7807e8b6c3d514753','V_pv':'08dacebd9b4e1eb69bcbf91bfc24b904','Ni_pv':'ed85c7b882fbcc8747fc2966a66e8584','N':'9d4908b6809ffb7a0762dee7fc571857','O':'9d87f5aff44d5d488070cd054a6acf7c'}
 for sp,md5 in expected_md5.items():
  script+=f'[ "$(md5sum "$LIB/{sp}/POTCAR" | cut -d " " -f1)" = "{md5}" ] || {{ echo "POTCAR_HASH_MISMATCH {sp}"; exit 46; }}\n'
 # Build/validate all potentials before any submission. Persistent mapping per successful sbatch.
 script+='cd "$P"\ntouch submitted.tsv\n'
 ordered=sorted(manifest,key=lambda r: {'resume':0,'static':1,'static_guarded':2}[r['stage']])
 for r in ordered:
  dep='--dependency=afterok:$RESUME_JOB' if r['stage']=='static_guarded' else ''
  script+=f'cd "$P/{r["directory"]}"\nJ=$(sbatch --parsable {dep} job.pbs)\nJ=${{J%%;*}}\n[[ "$J" =~ ^[0-9]+$ ]] || exit 45\nprintf "%s\\t%s\\n" "{r["directory"]}" "$J" >> "$P/submitted.tsv"\n'
  if r['stage']=='resume':script+='RESUME_JOB=$J\n'
 script+='cd "$P"\ncat submitted.tsv\nsqueue -u "$USER" -o "%.12i %.32j %.8T %.5C %.6M %R"\n'
 remote(f'set -eu\nmkdir -p "$HOME/{REMOTE}"\n',d/'mkdir.log')
 with (d/'upload.log').open('wb') as out:
  r=subprocess.run([SCP,'-o','BatchMode=yes','-i',CFG['ssh_key'],str(tar),CFG['host']+':'+REMOTE+'/inputs.tar.gz'],stdout=out,stderr=subprocess.STDOUT)
 if r.returncode:raise RuntimeError('Upload failed')
 result=remote(script,d/'submit.log')
 jobs=[]
 for l in result.splitlines():
  if '\t' in l:
   dr,j=l.split('\t',1)
   if j.isdigit():jobs.append({'directory':dr,'job_id':j})
 if len(jobs)!=25:raise RuntimeError('Incomplete batch mapping; inspect submit.log and remote submitted.tsv before retry')
 step['submitted_job']='batch:25';step['key_results']={'jobs':jobs,'remote_path':REMOTE,'ppn':16,'memory':'24G'};step['note']='Submitted 23 static + resume + guarded static to bkzhang'
 return step['note']
def collect(state,step,d):
 # Return only scheduler-completed outputs; running files are never treated as final.
 jobs=step['key_results']['jobs']
 ids=','.join(j['job_id'] for j in jobs)
 text=remote(f'set -eu\nsacct -X -n -P -j {ids} --format=JobIDRaw,State,ExitCode\n',d/'accounting.log')
 status={}
 for line in text.splitlines():
  a=line.strip().split('|')
  if len(a)>=3 and a[0].isdigit():status[a[0]]={'state':a[1],'exit':a[2]}
 completed=[j for j in jobs if status.get(j['job_id'],{}).get('state')=='COMPLETED' and status[j['job_id']]['exit']=='0:0']
 accepted=[];issues=[]
 for j in jobs:
  s=status.get(j['job_id'],{})
  if s.get('state') in ['FAILED','OUT_OF_MEMORY','TIMEOUT','CANCELLED','NODE_FAIL','BOOT_FAIL','DEADLINE']:
   issues.append({'directory':j['directory'],'job_id':j['job_id'],'scheduler_failure':s})
 for j in completed:
  local=d/'collected'/j['directory'];local.mkdir(parents=True,exist_ok=True)
  if not (local/'download_complete.json').exists():
   for name in ['OUTCAR','OSZICAR','CONTCAR','INCAR','POSCAR','KPOINTS','vasp.out']:
    with (d/'download.log').open('ab') as log:
     r=subprocess.run([SCP,'-o','BatchMode=yes','-i',CFG['ssh_key'],CFG['host']+':'+REMOTE+'/'+j['directory']+'/'+name,str(local/name)],stdout=log,stderr=subprocess.STDOUT)
    if r.returncode:raise RuntimeError(f'Output download failed: {j["directory"]}/{name}')
   (local/'download_complete.json').write_text(json.dumps({'job_id':j['job_id'],'files':['OUTCAR','OSZICAR','CONTCAR','INCAR','POSCAR','KPOINTS','vasp.out']}),encoding='utf-8')
  t=(local/'OUTCAR').read_text(errors='replace')
  normal='General timing and accounting informations' in t
  iterations=list(re.finditer(r'Iteration\s+\d+\(\s*\d+\)',t))
  final=t[iterations[-1].start():] if iterations else ''
  scf='aborting loop because EDIFF is reached' in final
  is_resume=j['directory'].startswith('resume/')
  ionic=(not is_resume) or 'reached required accuracy' in t
  if not (normal and scf and ionic):
   issues.append({'directory':j['directory'],'normal_end':normal,'electronic_converged':scf,'ionic_converged':ionic});continue
  if is_resume:continue
  def value(k):
   m=re.search(r'\b'+k+r'\s*=\s*([^\s;]+)',t);return m.group(1) if m else None
  mismatches={}
  for key,want in {'NSW':0,'IBRION':-1,'ISIF':2,'ISMEAR':-5,'NKPTS':13,'ENCUT':520,'EDIFF':1e-5,'ISYM':2,'IVDW':11,'ISPIN':2}.items():
   try:actual=float(value(key))
   except (TypeError,ValueError):actual=None
   if actual is None or abs(actual-want)>max(abs(want)*1e-7,1e-12):mismatches[key]={'expected':want,'actual':actual}
  for key in ['LREAL','LASPH','LWAVE','LCHARG']:
   if str(value(key)).lower() not in ['f','.false.','false']:mismatches[key]=value(key)
  pos=Poscar.from_file(local/'POSCAR',check_for_potcar=False)
  us=re.search(r'^\s*LDAUU\s*=\s*([^\n]+)',t,re.M)
  actual_u=[float(v) for v in us.group(1).split()] if us else []
  if actual_u!=[EXPECTED[s] for s in pos.site_symbols]:mismatches['LDAUU']=actual_u
  expected_titles=[s+'_pv' if s in ['Na','Ti','Mn','Fe','V','Ni'] else s for s in pos.site_symbols]
  actual_titles=list(dict.fromkeys(re.findall(r'^\s*TITEL\s*=\s*PAW_PBE\s+(\S+)',t,re.M)))
  if actual_titles!=expected_titles:mismatches['POTCAR_order']=actual_titles
  if (local/'KPOINTS').read_bytes()!=(d/j['directory']/'KPOINTS').read_bytes():mismatches['KPOINTS']='changed'
  if mismatches:
   issues.append({'directory':j['directory'],'parameter_mismatch':mismatches});continue
  energy=re.findall(r'energy\(sigma->0\)\s*=\s*([-+\d.Ee]+)',t)
  if not energy:issues.append({'directory':j['directory'],'missing_energy':True});continue
  parts=j['directory'].split('/')
  accepted.append({'label':parts[1],'branch':parts[2],'job_id':j['job_id'],'energy_eV':float(energy[-1]),'directory':str(local.relative_to(ROOT))})
 for branch in ['N-O','O-van']:
  rows=[x for x in accepted if x['branch']==branch]
  if rows:
   low=min(x['energy_eV'] for x in rows)
   for x in rows:x['relative_eV']=x['energy_eV']-low
 result={'checked_at':time.strftime('%Y-%m-%d %H:%M:%S'),'scheduler':status,'accepted_static_count':len(accepted),'results':accepted,'issues':issues,'relative_energy_is_partial':len(accepted)!=24}
 (d/'collection_status.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
 step['key_results']['accepted_static_count']=len(accepted)
 step['key_results']['collection_status']=str((d/'collection_status.json').relative_to(ROOT))
 if len(accepted)==24 and not issues:
  step['status']='done';step['note']='24 static results collected with normal termination and electronic convergence'
 else:step['note']=f'Collected and verified {len(accepted)}/24 static results; {len(issues)} convergence/parameter issues; jobs remain in progress'
 return step['note']

def handler(state,step):
 if step['status']=='pending':return prepare(state,step)
 return submit(state,step)
wf.WF_TEMPLATES['v24_unified_batch']=[{'name':NAME,'type':'v24_batch'}]
wf._STEP_HANDLERS['v24_batch']=handler
if __name__=='__main__':
 state=wf._load_state(WFID,PROJECT)
 if state is None:
  state={'schema_version':1,'wf_id':WFID,'template':'v24_unified_batch','project':PROJECT,'status':'running','revision':0,'created':time.strftime('%Y-%m-%d %H:%M:%S'),'params':{'node':'bkzhang','ppn':16},'current':0,'steps':[{'name':NAME,'type':'v24_batch','status':'pending','key_results':{},'note':''}]}
  wf._save_state(state)
 print(wf.advance_workflow(WFID,PROJECT,expected_revision=state['revision']))
