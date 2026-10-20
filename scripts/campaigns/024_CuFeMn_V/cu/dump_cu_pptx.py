"""Dump the text of the original Cu-project slide decks (parameters / conclusions).

Source (original project data, read-only):
    <MATCALC_OLD_CU_PROJECT>/模拟计算.pptx
    <MATCALC_OLD_CU_PROJECT>/dos/result/CuFeNi_FeTiNi_pdos_result.pptx
Default MATCALC_OLD_CU_PROJECT = E:\\Project\\024_CuFeMn\\模拟计算
"""
from __future__ import annotations
import os
import re
import zipfile
from pathlib import Path
import xml.etree.ElementTree as ET

BASE = Path(os.environ.get('MATCALC_OLD_CU_PROJECT') or r'E:\Project\024_CuFeMn\模拟计算')
SRC = [BASE / '模拟计算.pptx',
       BASE / 'dos' / 'result' / 'CuFeNi_FeTiNi_pdos_result.pptx']
NS = {'a': 'http://schemas.openxmlformats.org/drawingml/2006/main'}

for p in SRC:
    if not p.exists():
        print('missing:', p); continue
    print('=' * 78)
    print(p.name)
    print('=' * 78)
    with zipfile.ZipFile(p) as z:
        slides = sorted((n for n in z.namelist() if re.fullmatch(r'ppt/slides/slide\d+\.xml', n)),
                        key=lambda n: int(re.findall(r'\d+', n)[0]))
        for n in slides:
            root = ET.fromstring(z.read(n))
            texts = [t.text for t in root.iter('{%s}t' % NS['a']) if t.text and t.text.strip()]
            print(f'--- {n}')
            for t in texts:
                print('   ', t.strip())
