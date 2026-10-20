"""R3 拆分脚本：将输入生成组迁入 server/matcalc/vasp_inputs.py 并二次瘦身 main.py。

前置: 已执行 refactor_r2.py。用法同 R2。
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN = ROOT / "server" / "main.py"
PKG = ROOT / "server" / "matcalc"

lines = MAIN.read_text(encoding="utf-8").splitlines(keepends=True)


def seg(a: int, b: int) -> str:
    out = []
    for ln in lines[a - 1 : b]:
        if ln.strip() == "@mcp.tool()":
            continue
        out.append(ln)
    return "".join(out).strip("\n") + "\n"


# ---------- vasp_inputs.py ----------
body = "\n".join([
    seg(81, 107),     # _INCAR_TEMPLATES / _METALS（含注释行）
    seg(466, 507),    # _save_input_set / _primitive_and_kpath / _line_mode_kpoints_text
    seg(109, 260),    # generate_vasp_inputs
    seg(261, 354),    # generate_sbatch
    seg(509, 806),    # band / dos / optical / elastic / eos / bader 输入生成器
])
text = (
    '"""VASP 输入生成：INCAR/KPOINTS/POTCAR 脚本、两段式能带与 DOS、\n'
    '光学/弹性/EOS/Bader 输入集、作业脚本生成。\n\n'
    '（R3 自 main.py 原样迁移，函数体未改动）"""\n\n'
    "from __future__ import annotations\n\n"
    "import math\nimport os\nimport time\nfrom typing import Optional\n\n"
    "from pymatgen.core import Structure\n"
    "from pymatgen.io.vasp import Poscar\n\n"
    "from .common import out_dir as _out_dir\n\n\n"
    + body
)
(PKG / "vasp_inputs.py").write_text(text, encoding="utf-8")
print(f"[ok] vasp_inputs.py: {len(text.splitlines())} 行")

# ---------- 重写 main.py ----------
backup = ROOT / "scripts" / "main.py.bak_r3"
backup.write_text("".join(lines), encoding="utf-8")
print(f"[ok] 备份 -> {backup}")

BLOCK = """
# ══════════ M5-R2/R3: 工具实现已迁至 matcalc 包，此处仅组装注册（行为不变） ══════════

try:  # 兼容 python server/main.py（脚本）与 from server import main（包）两种运行方式
    from .matcalc import analysis, organize, parsing, plotting, structures, vasp_inputs
except ImportError:  # pragma: no cover
    from matcalc import analysis, organize, parsing, plotting, structures, vasp_inputs

for _fn in (
    structures.build_structure, structures.parse_poscar,
    structures.make_supercell, structures.cleave_surface,
    parsing.parse_vasp_output, parsing.diagnose_vasp_error,
    parsing.analyze_vasprun, parsing.parse_bader_acf,
    plotting.plot_dos, plotting.plot_pdos, plotting.plot_band,
    analysis.fit_eos,
    organize.organize_outputs, organize.export_report,
    vasp_inputs.generate_vasp_inputs, vasp_inputs.generate_sbatch,
    vasp_inputs.generate_band_inputs, vasp_inputs.generate_dos_inputs,
    vasp_inputs.generate_optical_inputs, vasp_inputs.generate_elastic_inputs,
    vasp_inputs.generate_eos_inputs, vasp_inputs.generate_bader_inputs,
):
    mcp.tool()(_fn)

"""

# (1,40)=头部与 FastMCP 实例；(355,464)=五个远程包装工具；(808,末尾)=M4 作业守护
RETAIN = [(1, 40), (355, 464), (808, len(lines))]

parts = []
for i, (a, b) in enumerate(RETAIN):
    parts.append("".join(lines[a - 1 : b]))
    if i == 0:
        parts.append(BLOCK)

new_main = "".join(parts)
while "\n\n\n\n" in new_main:
    new_main = new_main.replace("\n\n\n\n", "\n\n\n")
MAIN.write_text(new_main, encoding="utf-8")
print(f"[ok] main.py 二次瘦身: {len(lines)} -> {len(new_main.splitlines())} 行")
