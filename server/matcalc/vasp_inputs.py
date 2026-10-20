"""VASP 输入生成：INCAR/KPOINTS/POTCAR 脚本、两段式能带与 DOS、
光学/弹性/EOS/Bader 输入集、作业脚本生成。

（R3 自 main.py 原样迁移，函数体未改动）"""

from __future__ import annotations

import math
import os
import re
import time
from typing import Optional

from pymatgen.core import Element, Structure
from pymatgen.io.vasp import Poscar

try:  # 兼容包导入与脚本直跑（_to_vasp5_poscar 为全项目统一 POSCAR 写出器，见 structures.py）
    from .structures import _to_vasp5_poscar
    from .common import out_dir as _out_dir, OUTPUTS_DIR as _OUTPUTS_DIR
except ImportError:  # pragma: no cover
    from matcalc.structures import _to_vasp5_poscar
    from matcalc.common import out_dir as _out_dir, OUTPUTS_DIR as _OUTPUTS_DIR

try:  # generate_sbatch 的缺省 partition/模块取自 remote 配置
    from .. import remote
except ImportError:  # pragma: no cover —— 直接以脚本方式运行时
    import remote


_INCAR_TEMPLATES: dict[str, dict] = {
    "relax": {
        "IBRION": 2, "ISIF": 3, "NSW": 100, "EDIFFG": -0.02,
        "ISMEAR": None, "SIGMA": 0.1,
    },
    "static": {
        "IBRION": -1, "ISIF": 2, "NSW": 0, "EDIFFG": None,
        "ISMEAR": None, "SIGMA": 0.05,
    },
    "bands": {
        "IBRION": -1, "ISIF": 2, "NSW": 0, "EDIFFG": None,
        "ISMEAR": None, "SIGMA": 0.05, "LORBIT": 11,
    },
    "dos": {
        "IBRION": -1, "ISIF": 2, "NSW": 0, "EDIFFG": None,
        "ISMEAR": None, "SIGMA": 0.05, "LORBIT": 11, "NEDOS": 2000,
    },
    "elastic": {
        "IBRION": 6, "ISIF": 3, "NSW": 1, "EDIFFG": None,
        "ISMEAR": None, "SIGMA": 0.1, "NFREE": 4,
    },
}

# calc_type → 期望的离子步设置（NSW, IBRION）。防止模板被改错后静默产出"假静态"。
_STAGE_EXPECT: dict[str, tuple[object, tuple[int, ...]]] = {
    "relax": (">0", (1, 2, 3)),
    "static": (0, (-1,)),
    "bands": (0, (-1,)),
    "dos": (0, (-1,)),
    "elastic": (None, (6,)),
}


def _check_stage_consistency(incar_text: str, calc_type: str) -> None:
    """校验 calc_type 与 INCAR 里的离子步参数自洽。

    静态（static / bands / dos）必须是 NSW=0 + IBRION=-1；relax 必须 NSW>0 且 IBRION∈{1,2,3}；
    elastic 必须 IBRION=6。这道检查防的是"模板被改错"：那种错误下 U / ENCUT / k 点全部合规，
    只有离子步参数不对，下游的协议核对发现不了，只会把静态跑成第二次弛豫。
    """
    kv: dict[str, str] = {}
    for line in incar_text.splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        m = re.match(r"^([A-Z][A-Z0-9_]*)\s*=\s*([^\s#]+)", s)
        if m and m.group(1) not in kv:
            kv[m.group(1)] = m.group(2)
    if "NSW" not in kv or "IBRION" not in kv:
        raise RuntimeError(f"INCAR 缺少 NSW/IBRION，无法校验 calc_type={calc_type!r}")
    try:
        nsw, ibrion = int(float(kv["NSW"])), int(float(kv["IBRION"]))
    except ValueError:
        raise RuntimeError(f"INCAR 的 NSW/IBRION 非数值：{kv['NSW']!r} / {kv['IBRION']!r}")

    want_nsw, want_ibrion = _STAGE_EXPECT[calc_type]
    if ibrion not in want_ibrion:
        raise RuntimeError(
            f"calc_type={calc_type!r} 生成了 IBRION={ibrion}，应为 {want_ibrion}（模板被改错？）"
        )
    if want_nsw == ">0" and nsw <= 0:
        raise RuntimeError(f"calc_type={calc_type!r} 生成了 NSW={nsw}，应为正整数")
    if want_nsw == 0 and nsw != 0:
        raise RuntimeError(
            f"calc_type={calc_type!r} 生成了 NSW={nsw}，应为 0（静态会被跑成弛豫）"
        )


# 常见金属元素（用于 ISMEAR 建议）
_METALS = {
    "Li", "Na", "K", "Mg", "Ca", "Sr", "Ba", "Ti", "Zr", "V", "Cr", "Mn",
    "Fe", "Co", "Ni", "Cu", "Zn", "Al", "Ag", "Au", "Pt", "Pd", "Nb", "Mo", "W",
}


def _save_input_set(tag: str, files: dict, project: Optional[str] = None) -> str:
    """把一组输入文件保存到 outputs/[<project>/inputs/]<tag>_<时间戳>/ 目录。"""
    d = os.path.join(_out_dir(project, "input"), f"{tag}_{int(time.time())}")
    os.makedirs(d, exist_ok=True)
    rows = [f"输入文件已保存到目录: {d}"]
    for name, text in files.items():
        p = os.path.join(d, name)
        with open(p, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        rows.append(f"- {name} ({len(text.splitlines())} 行)")
    return "\n".join(rows)


def _primitive_and_kpath(structure: Structure):
    """取标准原胞与其高对称路径（能带/DOA 计算必须用原胞保证 k 坐标一致）。"""
    from pymatgen.symmetry.analyzer import SpacegroupAnalyzer
    from pymatgen.symmetry.bandstructure import HighSymmKpath

    sga = SpacegroupAnalyzer(structure, symprec=0.01)
    prim = sga.get_primitive_standard_structure()
    hskp = HighSymmKpath(prim)
    kp = hskp.kpath
    return prim, kp["path"], kp["kpoints"]


def _line_mode_kpoints_text(path_segments, kpoint_dict, npts: int) -> str:
    """由路径段生成 VASP line-mode KPOINTS 文本。"""
    lines = [
        "Line-mode K-Path (MatCalcAgent auto-generated)",
        str(npts),
        "Line-mode",
        "rec",
    ]
    for seg in path_segments:
        for a, b in zip(seg[:-1], seg[1:]):
            ka = kpoint_dict[a]
            kb = kpoint_dict[b]
            fmt = lambda lbl, c: "{} {:.6f} {:.6f} {:.6f}".format(lbl, *c)  # noqa: E731
            lines.append("{} {}".format(a.replace("\\Gamma", "GAMMA"), b.replace("\\Gamma", "GAMMA")))
            lines.append(fmt("", ka).strip() + "   " + fmt("", kb).strip())
    return "\n".join(lines) + "\n"

def generate_vasp_inputs(
    poscar_text: str,
    calc_type: str = "relax",
    encut: Optional[int] = None,
    kpoint_density: Optional[float] = None,
    ismear: Optional[int] = None,
    save: bool = True,
    ivdw: Optional[int] = None,
    ldau_u: Optional[str] = None,
    ldau_l: Optional[str] = None,
    magmom: Optional[str] = None,
    ispin: Optional[int] = None,
    project: Optional[str] = None,
) -> str:
    """生成 VASP 输入文件（INCAR + KPOINTS + POTCAR 拼接脚本）。

    Args:
        poscar_text: POSCAR 文件内容（多行文本，作为结构输入）。
        calc_type: 计算类型: relax / static / bands / dos / elastic。
        encut: 平面波截断能 (eV)；缺省按体系给建议值。
        kpoint_density: 倒空间 k 点密度 (1/Å)；缺省 0.04。
        ismear: ISMEAR 覆盖值（-5 绝缘体/半导体, 0 需 SIGMA, 1 金属）。
        save: 是否将输入文件写入 outputs 目录（默认 True）。
        project: 项目名；给出时输入集写到 outputs/<project>/inputs/<formula>_<type>_<ts>/，
            缺省写 outputs/ 根（旧行为，仅兼容）。
        ivdw: 色散校正（11=Grimme D3, 12=D3(BJ)）；None 不写 IVDW 行。
        ldau_u: +U 有效 U(eV)，格式 "元素=数值,元素=数值"（如 "Ti=4.5,Mn=4.0"）；
            固定 Dudarev 方案（LDAUTYPE=2、LDAUJ=0、LMAXMIX=4）；
            未指定的元素 LDAUL=-1 / LDAUU=0。
        ldau_l: 可选，角动量通道覆盖（d=2 / f=3），格式同上；
            缺省：被 +U 的元素取 d(2)，其余 -1。
        magmom: 元素初始磁矩(μB)，格式同上；自动展开为按 POSCAR 元素块的
            "N*数值" 向量（VASP 重复语法），未指定元素取默认 0.6；
            给出 magmom 且未显式传 ispin 时自动 ISPIN=2。
        ispin: 自旋极化开关（1/2）；缺省由 magmom 推导。

    Returns:
        INCAR / KPOINTS / POTCAR 脚本文本 + 参数校验报告。
    """
    # 1. 解析结构
    try:
        structure = Poscar.from_str(poscar_text).structure
    except Exception as e:  # noqa: BLE001
        return f"错误：POSCAR 解析失败（{e}）"
    comp = structure.composition
    els = [el.symbol for el in comp.elements]

    # 2. 计算类型校验
    if calc_type not in _INCAR_TEMPLATES:
        return f"错误：不支持的 calc_type '{calc_type}'，可选: {', '.join(_INCAR_TEMPLATES)}"

    # 3. 参数与校验
    warnings: list[str] = []

    has_metal = any(el in _METALS for el in els)
    if ismear is None:
        if has_metal:
            ismear = 1
        else:
            ismear = -5
    if has_metal and ismear == -5:
        warnings.append("体系含金属元素，ISMEAR=-5（tetrahedron）不建议用于金属；建议 ISMEAR=1 + SIGMA=0.1")
    if not has_metal and ismear == 1:
        warnings.append("体系为绝缘体/半导体，ISMEAR=1 可接受但 ISMEAR=-5 更精确（需致密 k 点）")

    encut = encut or 500
    if not 200 <= encut <= 1000:
        warnings.append(f"ENCUT={encut} eV 超出常见范围（200-1000），请核对 POTCAR 的 ENMAX")

    density = kpoint_density or 0.04
    if not 0.01 <= density <= 0.2:
        warnings.append(f"k 点密度 {density} 1/Å 超出常见范围（0.02-0.1），请核对")

    # 3.5 高级参数：+U / 色散 / 磁矩（NMO 实战接口）
    def _parse_kv(spec: str, tag: str) -> dict[str, float]:
        """解析 'Ti=4.5,Mn=4.0' 形式的元素键值参数；符号必须属于当前体系。"""
        kv: dict[str, float] = {}
        for part in spec.replace(" ", "").split(","):
            if not part:
                continue
            sym, sep, raw = part.partition("=")
            if not sep:
                raise ValueError(f"{tag} 项 '{part}' 格式应为 元素=数值")
            try:
                kv[sym] = float(raw)
            except ValueError:
                raise ValueError(f"{tag} 项 '{part}' 数值非法") from None
            if sym not in els:
                raise ValueError(f"{tag} 指定元素 {sym} 不在体系中 ({', '.join(els)})")
        return kv

    try:
        ldau_map = _parse_kv(ldau_u, "ldau_u") if ldau_u else None
        ldau_l_map = _parse_kv(ldau_l, "ldau_l") if ldau_l else None
        magmom_map = _parse_kv(magmom, "magmom") if magmom else None
    except ValueError as e:
        return f"错误：{e}"

    eff_ispin = ispin
    if eff_ispin is None and magmom_map:
        eff_ispin = 2  # 给了初始磁矩，自旋极化是前提
        warnings.append("已根据 magmom 自动设置 ISPIN=2")
    if ivdw is not None and ivdw not in (10, 11, 12):
        warnings.append(f"IVDW={ivdw} 非常见取值（11=D3, 12=D3BJ），请核对")

    # 4. KPOINTS 网格（Monkhorst-Pack 自动网格，按倒空间密度）
    grid = []
    for i in range(3):
        n = max(1, int(math.ceil(2.0 * math.pi / (density * structure.lattice.abc[i]))))
        grid.append(n)
    kpoints_text = (
        "Automatic k-mesh\n"
        "0\n"
        "Monkhorst-Pack\n"
        f"{grid[0]} {grid[1]} {grid[2]}\n"
        "0 0 0\n"
    )

    # 5. INCAR
    tpl = _INCAR_TEMPLATES[calc_type]
    lines = [
        "### MatCalcAgent 生成的 INCAR（请按体系核对后使用） ###",
        f"SYSTEM = {comp.reduced_formula} ({calc_type})",
        f"ENCUT = {encut}",
        "PREC = Accurate",
        f"EDIFF = 1E-5",
        "LREAL = Auto",
    ]
    for key, val in tpl.items():
        if key == "ISMEAR":
            continue  # ISMEAR 在循环后统一写入（含用户覆盖值）
        if val is None:
            continue
        if key == "SIGMA":
            lines.append(f"SIGMA = {val}")
        elif key == "EDIFFG":
            lines.append(f"EDIFFG = {val}")
        else:
            lines.append(f"{key} = {val}")
    lines.append(f"ISMEAR = {ismear}")
    if calc_type in ("relax", "static", "dos", "elastic"):
        lines.append("LCHARG = .TRUE.")
    elif calc_type == "bands":
        lines.append("ICHARG = 11")
    if calc_type == "bands":
        lines.append("# 能带计算需两段：先用 static 生成 CHGCAR，再设 ICHARG=11 + 高对称路径 KPOINTS")
    if calc_type == "elastic":
        lines.append("# 弹性常数建议使用独立脚本对 6 个应变方向分别计算，或采用 IBRION=6 一次性方案")

    # 5.1 高级块：自旋极化 / DFT+U / 色散（均仅在用户给出对应参数时写入）
    if eff_ispin is not None or magmom_map:
        lines.append("")
        lines.append("# ===== 自旋极化 =====")
        if eff_ispin is not None:
            lines.append(f"ISPIN = {eff_ispin}")
        if magmom_map:
            reps = []
            for el in comp.elements:  # 按 POSCAR 元素块顺序展开
                reps.append(f"{int(comp[el])}*{magmom_map.get(el.symbol, 0.6):.2f}")
            lines.append("MAGMOM = " + " ".join(reps))
    if ldau_map:
        lines.append("")
        lines.append("# ===== DFT+U（Dudarev, LDAUTYPE=2, LDAUJ=0）=====")
        l_vec: list[str] = []
        u_vec: list[str] = []
        for el in comp.elements:
            sym = el.symbol
            has_u = sym in ldau_map
            lv = (ldau_l_map or {}).get(sym, 2 if has_u else -1)
            l_vec.append(str(int(lv)) if float(lv).is_integer() else f"{lv:g}")
            u_vec.append(f"{ldau_map[sym]:.2f}" if has_u else "0.00")
        lines.append("LDAU = .TRUE.")
        lines.append("LDAUTYPE = 2")
        lines.append(f"LDAUL = {' '.join(l_vec)}")
        lines.append(f"LDAUU = {' '.join(u_vec)}")
        lines.append("LDAUJ = " + " ".join("0.00" for _ in comp.elements))
        lines.append("LMAXMIX = 4  # d 电子混入能级上限（含 f 电子体系需改 6）")
    if ivdw is not None:
        lines.append("")
        lines.append("# ===== 色散校正 =====")
        lines.append(f"IVDW = {ivdw}  # 11=Grimme D3, 12=D3(BJ)")
    incar_text = "\n".join(lines) + "\n"
    _check_stage_consistency(incar_text, calc_type)

    # 6. POTCAR 拼接脚本（不捆绑版权数据）
    script_lines = [
        "#!/bin/bash",
        "# MatCalcAgent 生成的 POTCAR 拼接脚本（不包含 POTCAR 数据本身，请自行获取）",
        "# 用法: 设置 VASP_POTCAR_DIR 指向你的 VASP 赝势目录（如 ~/potpaw_PBE），然后运行本脚本",
        f"# 所需元素: {' '.join(els)}",
        "",
        'VASP_POTCAR_DIR="${VASP_POTCAR_DIR:-/path/to/potpaw_PBE}"',
        "OUT=POTCAR",
        "rm -f $OUT",
        *[f'cat "${{VASP_POTCAR_DIR}}/POTCAR.{el}" >> $OUT' for el in els],
        "echo 'POTCAR 拼接完成，检查 ENMAX 并与 INCAR 的 ENCUT 匹配（建议 ENCUT >= 1.3 * max(ENMAX)）'",
    ]
    potcar_script = "\n".join(script_lines) + "\n"

    # 7. 校验报告
    report = [
        f"计算类型: {calc_type}",
        f"元素: {', '.join(els)}",
        f"ENCUT: {encut} eV（建议 >= 1.3 × POTCAR 最大 ENMAX）",
        f"ISMEAR: {ismear}（{'金属建议 1' if has_metal else '绝缘体/半导体建议 -5'}）",
        f"k 点网格: {grid[0]}×{grid[1]}×{grid[2]}（密度 {density} 1/Å）",
    ]
    if ldau_map:
        report.append(
            "+U(Dudarev): " + ", ".join(f"{s}={v:g} eV" for s, v in ldau_map.items())
            + "；未指定元素 LDAUU=0/LDAUL=-1，LMAXMIX=4"
        )
    if ivdw is not None:
        report.append(f"色散校正: IVDW={ivdw}")
    if magmom_map:
        detail = ", ".join(f"{s}:{v:g}μB" for s, v in magmom_map.items())
        report.append(f"MAGMOM: {detail}（其余原子默认 0.6）；ISPIN={eff_ispin}")
    report.extend(f"- 警告: {w}" for w in warnings)
    if not warnings:
        report.append("- 参数校验通过，无警告")

    # 8. 保存
    save_note = ""
    if save:
        tag = f"{comp.reduced_formula}_{calc_type}_{int(time.time())}"
        d = os.path.join(_out_dir(project, "input"), tag)
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "INCAR"), "w", encoding="utf-8") as f:
            f.write(incar_text)
        with open(os.path.join(d, "KPOINTS"), "w", encoding="utf-8") as f:
            f.write(kpoints_text)
        with open(os.path.join(d, "POSCAR"), "w", encoding="utf-8") as f:
            f.write(poscar_text)
        with open(os.path.join(d, "make_potcar.sh"), "w", encoding="utf-8") as f:
            f.write(potcar_script)
        save_note = f"\n输入文件已保存到目录: {d}（INCAR / KPOINTS / POSCAR / make_potcar.sh）"

    return (
        f"## 参数校验报告\n" + "\n".join(report) + "\n\n"
        f"## INCAR\n```\n{incar_text}```\n"
        f"## KPOINTS\n```\n{kpoints_text}```\n"
        f"## POTCAR 拼接脚本（bash）\n```bash\n{potcar_script}```{save_note}"
    )

def generate_sbatch(
    job_name: str = "matcalc",
    command: Optional[str] = None,
    partition: Optional[str] = None,
    ntasks: int = 1,
    cpus_per_task: Optional[int] = None,
    walltime: str = "01:00:00",
    modules: Optional[str] = None,
    extra_sbatch: Optional[str] = None,
    scheduler: str = "slurm",
) -> str:
    """生成 HPC 提交脚本（支持 Slurm sbatch 与 Torque/PBS qsub 两种调度后端）。

    Args:
        job_name: 作业名。
        command: 实际执行命令；缺省用配置的 vasp_cmd（如 vasp_std），
            自动加 mpirun 前缀（若含 vasp）。
        partition: 队列/分区名（Slurm --partition / Torque -q）；缺省取配置。
        ntasks: 总核数（Slurm --ntasks / Torque ppn）。
        cpus_per_task: 每任务核数（仅 Slurm 有效，可选）。
        walltime: 时限，如 "01:00:00"。
        modules: 模块加载命令（如 "module load apps/vasp/5.4.4"）；缺省取配置。
        extra_sbatch: 附加 #SBATCH 行（仅 Slurm）。
        scheduler: 调度后端 "slurm"（默认）或 "torque"。

    Returns:
        提交脚本文本（Slurm: run.sbatch / Torque: run.pbs）。
    """
    cfg = remote.load_config()
    partition = partition or cfg["partition"] or ""
    modules = modules or cfg["modules"] or ""

    if command is None:
        vasp_cmd = cfg["vasp_cmd"] or "vasp_std"
        if scheduler.lower() == "torque":
            command = (
                'NP=$(cat $PBS_NODEFILE | wc -l)\n'
                f"mpirun -np $NP -machinefile $PBS_NODEFILE {vasp_cmd}"
            )
        else:
            command = f"mpirun -np $SLURM_NTASKS {vasp_cmd}"

    if scheduler.lower() == "torque":
        lines = [
            "#!/bin/bash",
            f"#PBS -N {job_name}",
            f"#PBS -l nodes=1:ppn={ntasks}",
            "#PBS -e ./job.stderr",
            "#PBS -o ./job.stdout",
        ]
        if partition:
            lines.append(f"#PBS -q {partition}")
        lines += ["#PBS -V", "#PBS -S /bin/bash"]
        if modules:
            lines.append(modules)
        lines += [
            "",
            "cd $PBS_O_WORKDIR",
            'echo "Job started: $(date)"',
            command,
            'echo "Job finished: $(date)"',
        ]
        return "\n".join(lines) + "\n"

    # ---- Slurm 后端（默认） ----
    if command is None:
        pass  # 已在上面构造
    lines = [
        "#!/bin/bash",
        "#SBATCH --job-name=" + job_name,
        f"#SBATCH --ntasks={ntasks}",
    ]
    if cpus_per_task:
        lines.append(f"#SBATCH --cpus-per-task={cpus_per_task}")
    if partition:
        lines.append(f"#SBATCH --partition={partition}")
    lines.append(f"#SBATCH --time={walltime}")
    if extra_sbatch:
        lines.append(extra_sbatch)
    lines += [
        "",
        "# 环境",
        "module purge 2>/dev/null || true",
        modules or "# (未配置模块加载，请按集群环境补充 module load)",
        "",
        "cd $SLURM_SUBMIT_DIR",
        "echo \"Job started: $(date)\"",
        command,
        "echo \"Job finished: $(date)\"",
    ]
    return "\n".join(lines) + "\n"

def generate_band_inputs(poscar_text: str, line_density: int = 20, encut: Optional[int] = None, project: Optional[str] = None) -> str:
    """生成两段式能带计算输入（借鉴 VASPKIT 303）：SCF 电荷步 + 非自洽能带步。

    自动生成标准原胞与高对称路径 KPOINTS（line-mode）。

    Args:
        poscar_text: POSCAR 文本（任意惯用胞，将自动转为标准原胞）。
        line_density: 每段高对称路径的插值点数（默认 20）。
        encut: 平面波截断能 (eV)；缺省按体系估算。

    Returns:
        输入文件清单与使用说明（SCF → NSCF 两步流程）。
    """
    struct = Poscar.from_str(poscar_text).structure
    prim, segments, kdict = _primitive_and_kpath(struct)
    comp = prim.composition
    encut_v = encut if encut else max(400, int(max(float(Element(el.symbol).Z) for el in comp.elements) * 50))
    prim_poscar = _to_vasp5_poscar(prim)

    incar_scf = "\n".join(
        [
            "### Step1 SCF：收敛电荷密度（生成 CHGCAR）###",
            f"SYSTEM = {comp.reduced_formula} band-scf",
            f"ENCUT = {encut_v}",
            "PREC = Accurate",
            "EDIFF = 1E-6",
            f"ISMEAR = 0",
            "SIGMA = 0.05",
            "LCHARG = .TRUE.",
            "LWAVE = .FALSE.",
            "NCORE = 4",
            "",
        ]
    )
    incar_band = "\n".join(
        [
            "### Step2 NSCF：沿高对称路径算本征值（读 Step1 的 CHGCAR）###",
            f"SYSTEM = {comp.reduced_formula} band-nscf",
            f"ENCUT = {encut_v}",
            "PREC = Accurate",
            "EDIFF = 1E-6",
            "ICHARG = 11          ! 非自洽：固定电荷",
            "LCHARG = .FALSE.",
            "LWAVE = .FALSE.",
            "NCORE = 4",
            "",
        ]
    )
    kpoints_band = _line_mode_kpoints_text(segments, kdict, line_density)
    potcar_sh = (
        "#!/bin/bash\n# POTCAR 拼接脚本（设置 VASP_POTCAR_DIR 后运行）\n"
        'VASP_POTCAR_DIR="${VASP_POTCAR_DIR:?请设置赝势目录}"\n'
        "rm -f POTCAR\nfor el in @ELS@ ; do\n"
        '  cat "$VASP_POTCAR_DIR/$el/POTCAR" >> POTCAR || exit 1\ndone\necho done\n'
    ).replace("@ELS@", " ".join(el.symbol for el in comp.elements))
    saved = _save_input_set(
        "band_inputs",
        {
            "POSCAR": prim_poscar,
            "INCAR_step1_SCF": incar_scf,
            "INCAR_step2_NSCF": incar_band,
            "KPOINTS_band": kpoints_band,
            "make_potcar.sh": potcar_sh,
        },
        project=project,
    )
    labels = "-".join(seg[0] + ".." + seg[-1] for seg in segments)
    return (
        saved
        + "\n\n使用流程:\n"
        + "1. make_potcar.sh 生成 POTCAR\n"
        + "2. 用目录内 POSCAR + INCAR_step1_SCF + 普通 Gamma 网格 KPOINTS 做 SCF（得到 CHGCAR）\n"
        + "3. 复制 CHGCAR，换 INCAR_step2_NSCF + KPOINTS_band 做非自洽能带\n"
        + f"4. 高对称路径段: {labels}\n"
        + "5. 完成后下载 vasprun.xml，用 plot_band 工具绘图"
    )


def generate_dos_inputs(poscar_text: str, nedos: int = 2001, encut: Optional[int] = None, include_pdos: bool = True, project: Optional[str] = None) -> str:
    """生成态密度（DOS/PDOS）计算输入（借鉴 VASPKIT 111/112）。

    Args:
        poscar_text: POSCAR 文本。
        nedos: 态密度采样点数（默认 2001，VASPKIT 推荐 ≥2000）。
        encut: 平面波截断能 (eV)；缺省按体系估算。
        include_pdos: 是否开启投影态密度（LORBIT=11）。

    Returns:
        输入文件清单与说明。
    """
    struct = Poscar.from_str(poscar_text).structure
    prim, _, _ = _primitive_and_kpath(struct)
    comp = prim.composition
    encut_v = encut if encut else max(400, int(max(float(Element(el.symbol).Z) for el in comp.elements) * 50))
    # DOS 需要精细 k 网格：在自动网格基础上加密一倍
    kden = 0.05  # 更密的密度（M1 默认 0.04 → 这里更细）
    a_len = max(prim.lattice.abc)
    n_k = max(4, min(40, math.ceil(2 * math.pi / (kden * a_len))))
    kpoints_txt = (
        "Automatic dense mesh for DOS (MatCalcAgent)\n0\nGamma\n"
        f"{n_k} {n_k} {n_k}\n0 0 0\n"
    )
    incar = ["### DOS 计算 INCAAR（MatCalcAgent 生成，请核对体系后使用） ###",
             f"SYSTEM = {comp.reduced_formula} dos",
             f"ENCUT = {encut_v}",
             "PREC = Accurate",
             "EDIFF = 1E-6",
             "ISMEAR = -5          # 四面体方法（绝缘体/半导体最佳；金属请改 ISMEAR=1 且减小 SIGMA）",
             f"NEDOS = {nedos}",
             "LORBIT = 11          # 输出 PDOS（分波态密度）" if include_pdos else "# 未开启 PDOS",
             "LCHARG = .TRUE.",
             "LWAVE = .FALSE.",
             "NCORE = 4", ""]
    potcar_sh = (
        "#!/bin/bash\nVASP_POTCAR_DIR=\"${VASP_POTCAR_DIR:?请设置赝势目录}\"\n"
        "rm -f POTCAR\nfor el in @ELS@ ; do\n"
        '  cat "$VASP_POTCAR_DIR/$el/POTCAR" >> POTCAR || exit 1\ndone\necho done\n'
    ).replace("@ELS@", " ".join(el.symbol for el in comp.elements))
    saved = _save_input_set(
        "dos_inputs",
        {"POSCAR": _to_vasp5_poscar(prim), "INCAR": "\n".join(incar), "KPOINTS": kpoints_txt, "make_potcar.sh": potcar_sh},
        project=project,
    )
    return saved + f"\n\n说明: k 网格 {n_k}x{n_k}x{n_k}；完成后下载 vasprun.xml 用 plot_dos 工具绘图"

def generate_optical_inputs(poscar_text: str, encut: Optional[int] = None, nedos: int = 2000, cshift: float = 0.1, omegamax: float = 40.0, project: Optional[str] = None) -> str:
    """生成光学性质（介电函数/吸收谱）两步计算输入（借鉴 VASPKIT 711-714）。

    Step1 SCF 收敛电荷；Step2 LOPTICS=.TRUE. 非自洽计算虚部介电函数。

    Args:
        poscar_text: POSCAR 文本。
        encut: 截断能 (eV)；缺省按体系估算。
        nedos: 光谱采样点数。
        cshift: 展宽参数 CSHIFT (eV)。
        omegamax: 最大频率 OMEGAMAX (eV)。

    Returns:
        输入文件清单与流程说明。
    """
    struct = Poscar.from_str(poscar_text).structure
    comp = struct.composition
    encut_v = encut if encut else max(400, int(max(float(Element(el.symbol).Z) for el in comp.elements) * 50))
    incar1 = "\n".join([
        "### Step1 SCF（生成 CHGCAR）###", f"SYSTEM = {comp.reduced_formula} opt-scf",
        f"ENCUT = {encut_v}", "EDIFF = 1E-6", "ISMEAR = 0", "SIGMA = 0.05",
        "LCHARG = .TRUE.", "LWAVE = .FALSE.", "",
    ])
    incar2 = "\n".join([
        "### Step2 光学：非自洽 + LOPTICS（读 CHGCAR，输出实/虚介电函数到 vasprun.xml）###",
        f"SYSTEM = {comp.reduced_formula} optical",
        f"ENCUT = {encut_v}", "ICHARG = 11", "LOPTICS = .TRUE.",
        f"CSHIFT = {cshift}", f"OMEGAMAX = {omegamax}", f"NEDOS = {nedos}",
        "ISMEAR = 0", "SIGMA = 0.05", "LWAVE = .FALSE.", "LCHARG = .FALSE.", "",
    ])
    saved = _save_input_set("optical_inputs", {"POSCAR": _to_vasp5_poscar(struct), "INCAR_step1_SCF": incar1, "INCAR_step2_optics": incar2}, project=project)
    return saved + "\n\n说明: 完成后 vasprun.xml 含 dielectric function；吸收系数 α(ω)、折射率等可由实虚部 ε1/ε2 后处理得到"


def generate_elastic_inputs(poscar_text: str, encut: Optional[int] = None, pstress: float = 0.0, project: Optional[str] = None) -> str:
    """生成弹性常数计算输入（VASP 内置 IBRION=6 应力-应变法，借鉴 VASPKIT 20x）。

    Args:
        poscar_text: POSCAR 文本（建议先用充分弛豫的 CONTCAR）。
        encut: 截断能 (eV)。
        pstress: 扰动应力上限 (kBar)，默认 0（VASP 自动选步长）。

    Returns:
        输入文件清单与结果提取说明。
    """
    struct = Poscar.from_str(poscar_text).structure
    comp = struct.composition
    encut_v = encut if encut else max(500, int(max(float(Element(el.symbol).Z) for el in comp.elements) * 60))
    incar = "\n".join([
        "### 弹性常数（IBRION=6 应力-应变法；要求结构已充分弛豫）###",
        f"SYSTEM = {comp.reduced_formula} elastic",
        f"ENCUT = {encut_v}",
        "EDIFF = 1E-6          # 必须比常规更紧",
        "IBRION = 6            # 计算弹性常数",
        "ISIF = 3              # 计算刚性离子弹性常数 + 内应变张量",
        "NFREE = 4             # 每个形变用 4 个位移",
        f"PSTRESS = {pstress}",
        "NSW = 1",
        "PREC = High",
        "ISMEAR = 0",
        "SIGMA = 0.05",
        "NCORE = 4", "",
    ])
    saved = _save_input_set(
        "elastic_inputs",
        {"POSCAR": _to_vasp5_poscar(struct), "INCAR": incar},
        project=project,
    )
    return saved + "\n\n说明: OUTCAR 末尾 'ELASTIC MODULI' 表给出对称化弹性常数矩阵（GPa）；立方体系看 C11/C12/C44，可算体模量 B=(C11+2C12)/3。注意 k 网格需收敛良好"


def generate_eos_inputs(poscar_text: str, scale_min: float = 0.96, scale_max: float = 1.04, n_points: int = 7, project: Optional[str] = None) -> str:
    """生成状态方程（EOS）体积扫描输入集：按晶格缩放生成 n 个结构目录。

    Args:
        poscar_text: 已弛豫的 POSCAR 文本。
        scale_min/scale_max: 晶格缩放因子范围（如 0.96~1.04 即 ±4% 体积扫描）。
        n_points: 采样点数（默认 7）。

    Returns:
        各缩放点目录清单；跑完后收集 E-V 数据调用 fit_eos 拟合。
    """
    from pymatgen.core.lattice import Lattice

    struct = Poscar.from_str(poscar_text).structure
    v0 = struct.volume
    scales = [scale_min + i * (scale_max - scale_min) / (n_points - 1) for i in range(n_points)]
    rows = [f"EOS 扫描集（{n_points} 点，缩放 {scale_min}~{scale_max}）已保存:"]
    for i, s in enumerate(scales, 1):
        st = struct.copy()
        st.scale_lattice(v0 * s**3)
        d = os.path.join(_out_dir(project, "input"), f"eos_scan_{int(time.time())}_{i:02d}")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "POSCAR"), "w", encoding="utf-8", newline="\n") as f:
            f.write(_to_vasp5_poscar(st))
        rows.append(f"- {d}  缩放 {s:.4f}, V={st.volume:.3f} Å³")
    rows.append("\n流程: 对每个目录做同参数 static 计算 → 收集 (V, E) → 调用 fit_eos 得到平衡体积/体模量")
    return "\n".join(rows)


def generate_bader_inputs(poscar_text: str, encut: Optional[int] = None, project: Optional[str] = None) -> str:
    """生成 Bader 电荷分析计算输入（LAECHG=.TRUE. 输出 AECCAR0/AECCAR2）。

    Args:
        poscar_text: POSCAR 文本。
        encut: 截断能 (eV)；缺省按体系估算。
        project: 可选项目名——产物保存到 outputs/<project>/inputs/。

    Returns:
        输入文件清单与后处理流程说明（需自备 Henkelman bader 程序）。
    """
    struct = Poscar.from_str(poscar_text).structure
    comp = struct.composition
    encut_v = encut if encut else max(500, int(max(float(Element(el.symbol).Z) for el in comp.elements) * 50))
    incar = "\n".join([
        "### Bader 电荷分析 static（MatCalcAgent 生成）###",
        f"SYSTEM = {comp.reduced_formula} bader",
        f"ENCUT = {encut_v}",
        "PREC = Accurate",
        "EDIFF = 1E-6",
        "ISMEAR = 0",
        "SIGMA = 0.05",
        "NSW = 0",
        "IBRION = -1",
        "LAECHG = .TRUE.       ! 输出 AECCAR0 / AECCAR2（Bader 必需）",
        "LCHARG = .TRUE.",
        "LWAVE = .FALSE.",
        "NGXF = 96             # 可选：加密 FFT 网格提升 Bader 精度（按体系调整）",
        "NGYF = 96",
        "NGZF = 96",
        "",
    ])
    saved = _save_input_set("bader_inputs", {"POSCAR": _to_vasp5_poscar(struct), "INCAR": incar}, project=project)
    flow = (
        "\n\n后处理流程（远程机器需安装 Henkelman group bader 程序）:\n"
        "1. VASP 跑完得到 AECCAR0 AECCAR2 CHGCAR\n"
        "2. chgsum.pl AECCAR0 AECCAR2        # 生成 CHGCAR_sum\n"
        "3. bader CHGCAR -ref CHGCAR_sum     # 生成 ACF.dat AVF.dat BvAt.dat\n"
        "4. 下载 ACF.dat 后调用 parse_bader_acf 解析各原子电荷"
    )
    return saved + flow


def generate_aimd_inputs(
    poscar_text: str,
    temperature: float = 300.0,
    nsw: int = 5000,
    potim: float = 1.0,
    encut: Optional[int] = None,
    tebeg: Optional[float] = None,
    teend: Optional[float] = None,
    nblock: int = 1,
    smass: float = 0.0,
    ispin: Optional[int] = None,
    magmom: Optional[str] = None,
    ldau_u: Optional[str] = None,
    ldau_l: Optional[str] = None,
    project: Optional[str] = None,
    save: bool = True,
) -> str:
    """【MCP 工具】生成从头算分子动力学（AIMD）VASP 输入集。

    对齐常见 NVT AIMD 设定：IBRION=0 / MDALGO=2(Nose-Hoover) / TEBEG=TEEND。
    适合层状氧化物（如 O3-NaMnO2）短时热涨落与离子扩散初筛；生产级长轨迹
    建议更小 POTIM、更高 ENCUT 与超胞。

    Args:
        poscar_text: POSCAR（建议已弛豫的 CONTCAR，且足够大）。
        temperature: 目标温度 K（同时作为 TEBEG/TEEND，除非覆盖）。
        nsw: MD 步数（总时长 ≈ nsw × potim fs）。
        potim: 时间步长 fs（氧化物常用 0.5–1.0；含 H 则 ≤0.5）。
        encut: 截断能 eV；缺省 520。
        tebeg / teend: 起始/终止温度；缺省均为 temperature（恒温）。
        nblock: 每 nblock 步写一次 OSZICAR/轨迹信息。
        smass: Nose 质量参数（-1 初始；0/正数见 VASP 手册；缺省 0）。
        ispin / magmom: 自旋与初始磁矩（格式同 generate_vasp_inputs）。
        ldau_u / ldau_l: +U 参数（如 "Mn=4.0"），层状氧化物常用。
        project / save: 落盘控制。

    Returns:
        INCAR/KPOINTS/POSCAR 说明 + 使用提示；失败"错误："。
    """
    try:
        struct = Poscar.from_str(poscar_text).structure
    except Exception as e:  # noqa: BLE001
        return f"错误：[E_PARSE] POSCAR 解析失败（{e}）"
    comp = struct.composition
    els = [el.symbol for el in comp.elements]
    if len(struct) < 8:
        note_small = "⚠ 单胞过小，AIMD 易出现有限尺寸伪影；建议先 make_supercell ≥ 2×2×2\n"
    else:
        note_small = ""

    t0 = float(tebeg if tebeg is not None else temperature)
    t1 = float(teend if teend is not None else temperature)
    encut_v = int(encut or 520)
    nsw = int(nsw)
    potim = float(potim)
    if nsw <= 0:
        return "错误：[E_PARAM] nsw 需为正整数"
    if not 0.1 <= potim <= 5.0:
        return "错误：[E_PARAM] potim 建议 0.1–5.0 fs"
    if not 100 <= t0 <= 5000:
        return "错误：[E_PARAM] tebeg 温度异常"

    # +U / magmom 复用 vasp_inputs 的展开逻辑（简化：直接写行）
    extra = []
    if ldau_u:
        extra.append(f"LDAUU = {ldau_u}")
        extra.append("LDAUTYPE = 2")
        extra.append("LDAUJ = 0")
        extra.append("LMAXMIX = 4")
        if ldau_l:
            extra.append(f"LDAUL = {ldau_l}")
    mag_line = ""
    if magmom:
        mag_line = f"MAGMOM = {magmom}"
        extra.append(mag_line)
        if ispin is None:
            ispin = 2
    if ispin:
        extra.append(f"ISPIN = {ispin}")

    incar_lines = [
        "### AIMD NVT (MatCalcAgent) ###",
        f"SYSTEM = {comp.reduced_formula} aimd",
        f"ENCUT = {encut_v}",
        "PREC = Accurate",
        "EDIFF = 1E-5          # 电子步收敛（AIMD 可适当放宽）",
        "IBRION = 0            # 分子动力学",
        f"NSW = {nsw}",
        f"POTIM = {potim}",
        "MDALGO = 2            # Nose-Hoover 恒温",
        f"TEBEG = {t0}",
        f"TEEND = {t1}",
        f"NBLOCK = {nblock}",
        f"SMASS = {smass}",
        "ISYM = 0              # MD 中关闭对称性",
        "LWAVE = .FALSE.",
        "LCHARG = .FALSE.",
        "ISMEAR = 0",
        "SIGMA = 0.05",
    ] + extra + [""]

    # AIMD 通常用 Gamma 点或稀疏网格（大超胞）
    n_at = len(struct)
    if n_at >= 24:
        kpts = "K-Points\n0\nGamma\n1 1 1\n0 0 0\n"
        k_note = "大体系 Gamma 点（按需加密）"
    else:
        kpts = "K-Points\n0\nGamma\n2 2 2\n0 0 0\n"
        k_note = "小体系 2×2×2 Gamma 网格"

    files = {
        "POSCAR": _to_vasp5_poscar(struct),
        "INCAR": "\n".join(incar_lines),
        "KPOINTS": kpts,
    }
    saved = _save_input_set("aimd_inputs", files, project=project) if save else "（未落盘）"
    total_ps = nsw * potim / 1000.0
    tips = (
        f"\n\n总时长 ≈ {total_ps:.2f} ps（NSW={nsw} × POTIM={potim} fs）；"
        f"恒温 {t0:g}–{t1:g} K；{k_note}。\n"
        "运行后用 monitor_aimd(outcar, oscar, target_steps=NSW, target_temp=T) 监控。\n"
        "提示：AIMD 机时高，先短轨迹（~1 ps）试跑；扩散系数需更长轨迹与 MSD 分析。"
    )
    return note_small + saved + tips
