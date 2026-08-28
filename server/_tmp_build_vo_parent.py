# -*- coding: utf-8 -*-
"""母体 V_O 模型构建: 删 O 位点 52 (对标掺杂A) 与 82 (纯Mn环境), 输出 113 原子 POSCAR。"""
import warnings

warnings.filterwarnings("ignore")
from pymatgen.core import Structure
from pymatgen.io.vasp import Poscar

SRC = r"D:\personal_files\pycharm\Ai_model\matcalc-agent\server\outputs\NMO_parent\structures\CONTCAR_relaxed"
OUT = r"D:\personal_files\pycharm\Ai_model\matcalc-agent\server\outputs\NMO_parent\structures"

s = Structure.from_file(SRC)
for idx, tag in ((52, "Vo_P_A"), (82, "Vo_P_B")):
    # 校验是 O
    assert s[idx].specie.symbol == "O", f"{tag}: 索引 {idx} 不是 O ({s[idx].specie})"
    sd = s.copy()
    sd.remove_sites([idx])
    p = Poscar(sd)
    p.comment = f"{tag}: parent minus O#{idx} (113 atoms)"
    path = f"{OUT}\\{tag}.vasp"
    p.write_file(path)
    p2 = Poscar.from_file(path)
    print(f"{tag}: 挖除 O#{idx} -> {sum(p2.natoms)} 原子, 元素 {p2.site_symbols} {p2.natoms}")
    # 配位核对
    nn = s.get_neighbors(s[idx], 2.6)
    from collections import Counter
    print(f"   {tag} 原配位: {dict(Counter(n.specie.symbol for n in nn if n.specie.symbol != 'O'))}")
