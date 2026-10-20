"""R3 修补：① M4 头(NODES/LOCAL_POTCAR_LIB)归还 main.py；② vasp_inputs.py 截断误入的 M4 段；
③ vasp_inputs.py 补 remote 模块导入（generate_sbatch 缺省分区依赖它）。"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN = ROOT / "server" / "main.py"
VI = ROOT / "server" / "matcalc" / "vasp_inputs.py"
BAK = ROOT / "scripts" / "main.py.bak_r3"

# ---- ① 从备份取回 M4 头（781 注释起，到 LOCAL_POTCAR_LIB 段落止） ----
bak_lines = BAK.read_text(encoding="utf-8").splitlines(keepends=True)
m4_head = "".join(bak_lines[780:806]).rstrip("\n") + "\n"  # 1-based [781, 806]
assert "NODES" in m4_head and "LOCAL_POTCAR_LIB" in m4_head, "备份区间校验失败"

main_text = MAIN.read_text(encoding="utf-8")
anchor = "def _ssh_base(node: str) -> list:"
assert anchor in main_text and "\nNODES" not in main_text, "main.py 状态与预期不符"
main_text = main_text.replace(anchor, m4_head + "\n" + anchor, 1)
MAIN.write_text(main_text, encoding="utf-8")
print("[ok] M4 头已归还 main.py")

# ---- ②③ vasp_inputs.py：截断 M4 段 + 加 remote 导入 ----
vi_text = VI.read_text(encoding="utf-8")
cut_marker = "# ==================== M4:"
assert cut_marker in vi_text, "未找到误入的 M4 标记"
vi_text = vi_text.split(cut_marker)[0].rstrip("\n") + "\n"

import_block = (
    "\ntry:  # generate_sbatch 的缺省 partition/模块取自 remote 配置\n"
    "    from .. import remote\n"
    "except ImportError:  # pragma: no cover —— 直接以脚本方式运行时\n"
    "    import remote\n"
)
anchor2 = "from .common import out_dir as _out_dir\n"
assert anchor2 in vi_text, "vasp_inputs.py 导入锚点缺失"
vi_text = vi_text.replace(anchor2, anchor2 + import_block, 1)
VI.write_text(vi_text, encoding="utf-8")
print(f"[ok] vasp_inputs.py 修补完成: {len(vi_text.splitlines())} 行")
