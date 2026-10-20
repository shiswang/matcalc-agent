"""回归检查：把 v1 / v2 / cu 通道的打包结果导到临时目录，不覆盖已交付的 zip。

用法: python check_packaging_channels.py [v1|v2|cu]
"""
import os
import sys
import tempfile
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
os.environ['VCALC_CAMPAIGN'] = sys.argv[1] if len(sys.argv) > 1 else 'v2'

# 输出目录走环境变量重定向（不修改被检模块的常量）
tmp = Path(tempfile.mkdtemp(prefix='pkgcheck_'))
os.environ['VCALC_PACKAGE_DIR'] = str(tmp)

import package_vasp_data as P  # noqa: E402  (import 时读取上面两个环境变量)

P.main()

zip_path = tmp / f'{P.PKG_NAME}.zip'
with zipfile.ZipFile(zip_path) as z:
    bad = z.testzip()
    names = z.namelist()
    manifest = z.read([n for n in names if n.endswith('manifest.csv')][0]).decode('utf-8-sig')
    readme = z.read([n for n in names if n.endswith('README.md')][0]).decode('utf-8')
print('---- CHECK ----')
print('campaign      :', P.CAMPAIGN)
print('zip           :', zip_path.name, round(zip_path.stat().st_size / 1e6, 1), 'MB')
print('entries       :', len(names), '| testzip:', bad or 'OK')
rows = manifest.strip().splitlines()
print('manifest rows :', len(rows) - 1)
print('header        :', rows[0])
print('row[1]        :', rows[1])
print('readme title  :', readme.splitlines()[0])
print('readme XDATCAR:', [l for l in readme.splitlines() if '个目录都带' in l][:1])
print('readme U line :', [l for l in readme.splitlines() if 'DFT+U' in l][:1])
print('tmp dir       :', tmp)
