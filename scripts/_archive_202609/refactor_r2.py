"""R2 拆分脚本：按行区间将 main.py 功能组迁入 server/matcalc/* 并重写 main.py。

用法: .venv/Scripts/python.exe scripts/refactor_r2.py
纪律:
- 迁移前自动备份 main.py -> scripts/main.py.bak_r2
- 仅按行区间搬运 + 剥离 @mcp.tool 装饰器；函数体一个字符不改（行为不变）
- 迁移后必须 pytest 全绿才算完成
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN = ROOT / "server" / "main.py"
PKG = ROOT / "server" / "matcalc"

lines = MAIN.read_text(encoding="utf-8").splitlines(keepends=True)


def seg(a: int, b: int) -> str:
    """取 1-based 闭区间 [a, b] 的源码文本，剥离 @mcp.tool() 装饰器行。"""
    out = []
    for ln in lines[a - 1 : b]:
        if ln.strip() == "@mcp.tool()":
            continue
        out.append(ln)
    return "".join(out).strip("\n") + "\n"


def write_module(name: str, doc: str, imports: str, spans: list[tuple[int, int]]) -> None:
    body = "\n".join(seg(a, b) for a, b in spans)
    text = f'"""{doc}"""\n\nfrom __future__ import annotations\n\n{imports}\n\n{body}'
    (PKG / name).write_text(text, encoding="utf-8")
    print(f"[ok] {name}: {len(text.splitlines())} 行")

# ---------- 六个目标模块 ----------

write_module(
    "structures.py",
    "结构建模：化学式/原型建模、POSCAR 解析与摘要、超胞扩展、表面切面。\n\n"
    "（R2 自 main.py 原样迁移，函数体未改动）",
    "import math\nimport os\nimport time\nfrom typing import Optional\n\n"
    "from pymatgen.core import Composition, Element, Structure\n"
    "from pymatgen.core.lattice import Lattice\nfrom pymatgen.io.vasp import Poscar\n"
    "from pymatgen.symmetry.groups import SpaceGroup\n\nfrom .common import out_dir as _out_dir",
    [(61, 89), (122, 432), (1671, 1721)],
)

write_module(
    "visualize.py",
    "结构可视化：matplotlib 静态球棍图 / plotly 交互式 HTML / CIF 导出三模式。\n\n"
    "（R2 自 main.py 原样迁移，函数体未改动）",
    "import os\nimport time\nfrom typing import Optional\n\n"
    "import matplotlib\nmatplotlib.use(\"Agg\")  # 无 GUI 环境\n"
    "import matplotlib.pyplot as plt  # noqa: E402\n"
    "import numpy as np  # noqa: F401\n"
    "from pymatgen.io.vasp import Poscar\n\nfrom .common import out_dir as _out_dir",
    [(435, 634)],
)

write_module(
    "parsing.py",
    "结果解析与错误诊断：OUTCAR / vasprun.xml / ACF.dat(Bader) 与错误模式库。\n\n"
    "（R2 自 main.py 原样迁移，函数体未改动）",
    "import os\nimport re\nfrom typing import Optional",
    [(789, 944), (1323, 1381), (2100, 2170)],
)

write_module(
    "plotting.py",
    "DOS/PDOS/能带绘图与 Origin 数据导出（numpy 2.x trapezoid 积分）。\n\n"
    "（R2 自 main.py 原样迁移，函数体未改动）",
    "import os\nimport time\nfrom typing import Optional\n\n"
    "import matplotlib\nmatplotlib.use(\"Agg\")\n"
    "import matplotlib.pyplot as plt  # noqa: E402\n"
    "import numpy as np  # noqa: F401",
    [(1384, 1393), (1396, 1502), (1724, 2054)],
)

write_module(
    "analysis.py",
    "性质分析：状态方程拟合等纯计算（后续追加形成能等）。\n\n"
    "（R2 自 main.py 原样迁移，函数体未改动）",
    "from typing import Union, List",
    [(1640, 1668)],
)

write_module(
    "organize.py",
    "数据治理：outputs 归类整理与 Markdown/HTML 报告导出。\n\n"
    "（R2 自 main.py 原样迁移，函数体未改动）",
    "import glob\nimport os\nimport re\nimport shutil\nimport time\nfrom typing import Optional\n\n"
    "from .common import out_dir as _out_dir, OUTPUTS_DIR as _OUTPUTS_DIR",
    [(1504, 1535), (2173, 2249)],
)

# ---------- 重写 main.py ----------

backup = ROOT / "scripts" / "main.py.bak_r2"
backup.write_text("".join(lines), encoding="utf-8")
print(f"[ok] 备份 -> {backup}")

IMPORT_BLOCK = """
# ══════════ M5-R2: 工具实现已迁至 matcalc 包，此处仅组装注册（行为不变） ══════════

try:  # 兼容 python server/main.py（脚本）与 from server import main（包）两种运行方式
    from .matcalc import analysis, organize, parsing, plotting, structures, visualize
except ImportError:  # pragma: no cover
    from matcalc import analysis, organize, parsing, plotting, structures, visualize

for _fn in (
    structures.build_structure, structures.parse_poscar,
    structures.make_supercell, structures.cleave_surface,
    visualize.visualize_structure,
    parsing.parse_vasp_output, parsing.diagnose_vasp_error,
    parsing.analyze_vasprun, parsing.parse_bader_acf,
    plotting.plot_dos, plotting.plot_pdos, plotting.plot_band,
    analysis.fit_eos,
    organize.organize_outputs, organize.export_report,
):
    mcp.tool()(_fn)

"""

RETAIN = [(1, 39), (40, 59), (91, 119), (636, 787), (947, 1321),
          (1537, 1639), (2056, 2097), (2250, len(lines))]

parts = []
for i, (a, b) in enumerate(RETAIN):
    parts.append("".join(lines[a - 1 : b]))
    if i == 0:
        parts.append(IMPORT_BLOCK)

new_main = "".join(parts)
while "\n\n\n\n" in new_main:  # 压掉区间拼接产生的多余空行
    new_main = new_main.replace("\n\n\n\n", "\n\n\n")
MAIN.write_text(new_main, encoding="utf-8")
print(f"[ok] main.py 重写: {len(lines)} -> {len(new_main.splitlines())} 行")
