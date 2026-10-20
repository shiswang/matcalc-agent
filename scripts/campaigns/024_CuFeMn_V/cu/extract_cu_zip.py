"""Extract the original Cu-project archive into the campaign data tree.

Source (original project data, read-only):
    E:\\Project\\024_CuFeMn\\模拟计算.zip      (override: MATCALC_OLD_CU_ZIP)
Destination:
    <campaign data>/cu/cu_original           (see campaign_paths.CU_DATA)
"""
import os
import pathlib
import sys
import zipfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from campaign_paths import CU_DATA  # noqa: E402

SRC = pathlib.Path(os.environ.get('MATCALC_OLD_CU_ZIP') or r'E:\Project\024_CuFeMn\模拟计算.zip')
DST = CU_DATA / 'cu_original'
DST.mkdir(parents=True, exist_ok=True)
with zipfile.ZipFile(SRC) as z:
    names = z.namelist()
    z.extractall(DST)
files = sorted(p for p in DST.rglob('*') if p.is_file())
print('extracted files:', len(files))
byname = {}
for p in files:
    byname.setdefault(p.name, []).append(str(p.relative_to(DST)))
for k in sorted(byname):
    print(f'  {k:16s} x{len(byname[k])}')
print()
print('top level:', sorted(p.name for p in DST.iterdir()))
