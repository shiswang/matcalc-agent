"""离线验收：不连集群、不依赖 DSH。由 scripts/smoke_local.ps1 调用。"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> int:
    print("== [1/3] MCP tool count (expect 62) ==")
    import server.main as mc

    tools = asyncio.run(mc.mcp.list_tools())
    n = len(tools)
    print(f"tool_count={n}")
    if n != 62:
        print(f"FAIL expected 62 tools, got {n}", file=sys.stderr)
        return 1
    print("OK tools=62")

    print("== [2/3] Offline NaCl structure + VASP inputs ==")
    from pymatgen.core import Lattice, Structure

    from server.matcalc import structures as st
    from server.matcalc import vasp_inputs as vi
    from server.matcalc.structures import _to_vasp5_poscar

    out = st.build_structure("NaCl", prototype="rocksalt", save=False)
    if out.startswith("错误") or out.startswith("错误"):
        print(f"FAIL build_structure: {out[:200]}", file=sys.stderr)
        return 1
    if "NaCl" not in out and "POSCAR" not in out:
        print(f"FAIL unexpected build_structure output: {out[:200]}", file=sys.stderr)
        return 1
    print("build_structure OK")

    cell = Structure.from_spacegroup(
        "Fm-3m", Lattice.cubic(5.64), ["Na", "Cl"], [[0, 0, 0], [0.5, 0.5, 0.5]]
    )
    poscar = _to_vasp5_poscar(cell)
    msg = vi.generate_vasp_inputs(poscar, calc_type="relax")
    if isinstance(msg, str) and msg.startswith("错误"):
        print(f"FAIL generate_vasp_inputs: {msg[:300]}", file=sys.stderr)
        return 1
    text = str(msg)
    if not any(k in text for k in ("INCAR", "KPOINTS", "relax", "POSCAR", "已保存")):
        print(f"FAIL unexpected generate_vasp_inputs output: {text[:240]}", file=sys.stderr)
        return 1
    print("generate_vasp_inputs OK")
    print(text[:240].replace("\n", " | "))

    print("== [3/3] DONE ==")
    print("SMOKE PASS - wire any MCP client (see MCP.md)")
    print("Next: copy clusters.example.json clusters.json and fill your cluster")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
