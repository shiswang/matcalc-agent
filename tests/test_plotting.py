"""绘图与 Origin 导出回归：TDOS/PDOS 文件生成 + np.trapezoid 物理锚点。

锚点依据项目档案：NaCl ISPIN=2 数据中窗口内 Cl-p 积分远大于 Na-s（约 1044 vs 12）。
测试取保守比值阈值（>5×），避免对分辨率/窗口过拟合。
"""
import re
from pathlib import Path

import numpy as np
from pymatgen.io.vasp.outputs import Vasprun

from server.matcalc import plotting as mc
from server.matcalc.common import OUTPUTS_DIR

WINDOW = (-10.0, 10.0)


def _dos_dir(project: str) -> Path:
    return Path(OUTPUTS_DIR) / project / "dos_pdos"


# ---------- plot_dos ----------

def test_tdos_spin_generates_png_and_txt(nacl_vasprun_sp, clean_test_project):
    msg = mc.plot_dos(str(nacl_vasprun_sp), emin=WINDOW[0], emax=WINDOW[1],
                      save=True, project=clean_test_project)
    m_png = re.search(r"DOS 图已生成: (.+)", msg)
    m_txt = re.search(r"数据文件（Origin 可直接导入）: (.+)", msg)
    assert m_png and m_txt, msg
    png, txt = Path(m_png.group(1)), Path(m_txt.group(1))
    assert png.exists() and txt.exists()

    lines_ = txt.read_text(encoding="utf-8").strip().splitlines()
    assert lines_[0] == "# E-EF(eV)\tTDOS_up\tTDOS_down(取负后为-DOS)"
    n_rows = len(lines_) - 1
    assert n_rows > 100

    # 行数 == 窗口内能量点数（与实现同一 mask 口径）
    v = Vasprun(str(nacl_vasprun_sp), parse_projected_eigen=False, exception_on_bad_xml=False)
    ef = v.tdos.efermi
    mask = (v.tdos.energies - ef >= WINDOW[0]) & (v.tdos.energies - ef <= WINDOW[1])
    assert n_rows == int(mask.sum())


def test_tdos_nospin_single_channel(nacl_vasprun_nospin, clean_test_project):
    msg = mc.plot_dos(str(nacl_vasprun_nospin), emin=-10, emax=10,
                      save=True, project=clean_test_project)
    assert "非极化，单自旋通道" in msg
    m_txt = re.search(r"数据文件（Origin 可直接导入）: (.+)", msg)
    assert m_txt and Path(m_txt.group(1)).exists()


def test_tdos_save_false_writes_nothing(nacl_vasprun_sp, clean_test_project):
    msg = mc.plot_dos(str(nacl_vasprun_sp), save=False, project=clean_test_project)
    assert "已生成" not in msg.replace("图已生成: ", "") or "数据文件" not in msg
    assert list(_dos_dir(clean_test_project).glob("*")) == []


# ---------- plot_pdos ----------

def test_pdos_valence_files_and_cl_dominance(nacl_vasprun_sp, clean_test_project):
    msg = mc.plot_pdos(str(nacl_vasprun_sp), split="valence", elements="Na,Cl",
                       emin=WINDOW[0], emax=WINDOW[1], save=True,
                       project=clean_test_project)
    txts = sorted(_dos_dir(clean_test_project).glob("pdos_valence_*.txt"))
    pngs = sorted(_dos_dir(clean_test_project).glob("pdos_valence_*.png"))
    assert txts, msg
    assert pngs, msg

    rows = txts[-1].read_text(encoding="utf-8").strip().splitlines()
    header = rows[0]
    assert header.startswith("# E-EF(eV)")
    cols = header.split("\t")
    cl_idx = [i for i, h in enumerate(cols) if h.startswith("Cl")]
    na_idx = [i for i, h in enumerate(cols) if h.startswith("Na")]
    assert cl_idx and na_idx, f"PDOS 列名不含 Cl/Na: {header}"

    data = np.array([[float(x) for x in ln.split("\t")] for ln in rows[1:]])
    e = data[:, 0]
    int_cl = sum(abs(np.trapezoid(data[:, i], e)) for i in cl_idx)
    int_na = sum(abs(np.trapezoid(data[:, i], e)) for i in na_idx)
    assert int_cl > 5 * int_na, f"Cl 积分 {int_cl} vs Na 积分 {int_na}"


def test_existing_export_cl_dominance(nacl_pdos_export):
    """历史导出文件的物理锚点复核（ISPIN=2，element 模式）。"""
    rows = nacl_pdos_export.read_text(encoding="utf-8").strip().splitlines()
    cols = rows[0].split("\t")
    assert cols[0] == "# E-EF(eV)"

    def elem_sum(prefix):
        idx = [i for i, h in enumerate(cols) if h.startswith(prefix)]
        vals = np.array([[float(x) for x in ln.split("\t")] for ln in rows[1:]])
        return sum(abs(np.trapezoid(vals[:, i], vals[:, 0])) for i in idx)

    cl, na = elem_sum("Cl"), elem_sum("Na")
    assert cl > 5 * na, f"历史导出 Cl={cl} Na={na}，物理锚点失效？"
