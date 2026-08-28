# -*- coding: utf-8 -*-
"""母体 O 位点配位分析 + 选取与掺杂体系可比的 V_O 代表位点。"""
import warnings
from collections import Counter, defaultdict

import numpy as np

warnings.filterwarnings("ignore")
from pymatgen.core import Structure

s = Structure.from_file(
    r"D:\personal_files\pycharm\Ai_model\matcalc-agent\server\outputs\NMO_parent\structures\CONTCAR_relaxed"
)
print(f"母体: {len(s)} 原子, {s.composition.formula}")

# O 位点配位环境（r=2.6 Å 金属壳）
groups = defaultdict(list)
for i, site in enumerate(s):
    if site.specie.symbol != "O":
        continue
    nn = Counter(
        n.specie.symbol for n in s.get_neighbors(site, 2.6) if n.specie.symbol != "O"
    )
    key = tuple(sorted(nn.items()))
    groups[key].append((i, nn))

print("\nO 位点配位环境分组 (共", sum(len(v) for v in groups.values()), "个 O):")
for k, v in sorted(groups.items(), key=lambda x: -len(x[1])):
    print(f"  {dict(k)}  ×{len(v)}  (示例索引 {v[0][0]})")

# 掺杂体系 A 位点: Mn×2,Na×2,Ni×1 —— 在母体里找同类
print("\n=== 位点选取 ===")
candidates = {}
for k, v in groups.items():
    d = dict(k)
    tag = "|".join(f"{el}{d.get(el,0)}" for el in ("Mn", "Ni", "Na", "Mg", "Y", "Ti"))
    candidates[tag] = [idx for idx, _ in v]

# 与掺杂 A (Mn2Na2Ni1) 同类位点优先
prefer = ["Mn2|Ni1|Na2", "Mn2|Na2", "Mn2|Ni1|Na1", "Mn2|Ni1"]
for p in prefer:
    if p in candidates:
        print(f"选择 {p}: {len(candidates[p])} 个, 取索引 {candidates[p][0]}")
        break
else:
    top = max(candidates.items(), key=lambda x: len(x[1]))
    print(f"无完全同类, 取最大组 {top[0]}: 索引 {top[1][0]}")

# 第二代表: Mn3 纯锰位点(若有)
if "Mn3" in candidates:
    print(f"第二代表 Mn3: {len(candidates['Mn3'])} 个, 取索引 {candidates['Mn3'][0]}")

# 输出全部位点索引便于决策
print("\n全部候选索引:", {t: v[:3] for t, v in candidates.items()})
