"""Materials Project 对接：结构抓取 + 工作流对照（离线可测）。

设计：
- fetch_mp_structure 优先用 mp-api 客户端（pip install mp-api），需 MP_API_KEY；
- mp_workflow_guide 不联网，把 MP 常见计算链映射到本仓库工具/模板；
- 无 key 时给出可操作错误，不阻断离线建模。
"""
from __future__ import annotations

import os
import time
from typing import Optional

from .common import out_dir as _out_dir

try:
    from .structures import _to_vasp5_poscar
except ImportError:  # pragma: no cover
    from matcalc.structures import _to_vasp5_poscar


def _mp_api_key() -> Optional[str]:
    return os.environ.get("MP_API_KEY") or os.environ.get("MAPI_KEY") or None


def fetch_mp_structure(
    query: str,
    api_key: Optional[str] = None,
    save: bool = True,
    project: Optional[str] = None,
) -> str:
    """从 Materials Project 拉取结构（mp-id 或化学式）。

    Args:
        query: 材料 id（如 "mp-22862"）或化学式（如 "NaCl"）。
        api_key: 可选；缺省读环境变量 MP_API_KEY / MAPI_KEY。
        save: 是否写入 outputs/<project>/structures/。
        project: 项目名。

    Returns:
        摘要 + 归一 POSCAR；失败返回"错误："（含无 key / 网络 / 无命中）。
    """
    key = api_key or _mp_api_key()
    if not key:
        return (
            "错误：[E_PARAM] 未配置 Materials Project API key。"
            "请设置环境变量 MP_API_KEY（https://next-gen.materialsproject.org/api）"
            "后重试；离线建模请用 build_structure / import_structure。"
        )
    q = (query or "").strip()
    if not q:
        return "错误：[E_PARAM] query 不能为空"

    try:
        from mp_api.client import MPRester
    except Exception as e:  # noqa: BLE001
        return (
            f"错误：[E_PARAM] 需要 mp-api 包（{e}）。"
            "请在 venv 中: pip install mp-api"
        )

    try:
        with MPRester(key) as mpr:
            if q.lower().startswith("mp-"):
                st = mpr.get_structure_by_material_id(q)
                meta = {"material_id": q}
                try:
                    summary = mpr.materials.summary.search(material_ids=[q])
                    if summary:
                        doc = summary[0]
                        meta["band_gap"] = getattr(doc, "band_gap", None)
                        meta["spacegroup"] = getattr(
                            getattr(doc, "symmetry", None), "number", None
                        )
                except Exception:  # noqa: BLE001
                    pass
            else:
                docs = mpr.materials.summary.search(formula=q, fields=[
                    "material_id", "structure", "band_gap", "symmetry",
                ])
                if not docs:
                    # 兜底：化学式精确匹配列表
                    docs = mpr.materials.summary.search(
                        formula=q, fields=["material_id", "structure"]
                    )
                if not docs:
                    return f"错误：[E_PARAM] MP 未命中化学式 '{q}'"
                doc = docs[0]
                st = getattr(doc, "structure", None)
                meta = {
                    "material_id": getattr(doc, "material_id", None),
                    "band_gap": getattr(doc, "band_gap", None),
                    "spacegroup": getattr(
                        getattr(doc, "symmetry", None), "number", None
                    ),
                }
    except Exception as e:  # noqa: BLE001
        return (
            f"错误：[E_CLUSTER] Materials Project 请求失败（{type(e).__name__}: {e}）。"
            "检查 key、网络，或改用本地 CIF/POSCAR。"
        )

    if st is None:
        return f"错误：[E_PARAM] MP 未返回结构（query={q}）"

    poscar = _to_vasp5_poscar(st)
    save_note = ""
    if save:
        fname = f"mp_{st.composition.reduced_formula}_{int(time.time())}.vasp"
        fpath = os.path.join(_out_dir(project, "structure"), fname)
        with open(fpath, "w", encoding="utf-8") as f:
            f.write(poscar)
        save_note = f"\n已保存: {fpath}"

    lines = [
        f"来源: Materials Project | query={q}",
        f"组成: {st.composition.reduced_formula} | 原子数 {len(st)}",
        f"a,b,c: {st.lattice.abc[0]:.4f}, {st.lattice.abc[1]:.4f}, {st.lattice.abc[2]:.4f} Å",
        f"体积: {st.volume:.4f} Å³",
    ]
    if meta:
        for k in ("material_id", "spacegroup", "band_gap", "total_magnetization"):
            if k in meta and meta[k] is not None:
                lines.append(f"{k}: {meta[k]}")
    lines += ["## POSCAR", "```", poscar, "```" + save_note]
    return "\n".join(lines)


def mp_workflow_guide(topic: str = "all") -> str:
    """Materials Project / atomate2 工作流知识 → 本仓库工具与模板对照（纯离线）。

    基于 MP 生产链与 atomate2 Makers 的公开设计整理，不是 MP 源码拷贝。

    Args:
        topic: all | structure | relax | electronic | dielectric | elastic |
               phonon | neb | settings | makers

    Returns:
        中文对照说明，供 Agent 编排；不执行计算。
    """
    t = (topic or "all").strip().lower()
    sections: dict[str, str] = {
        "structure": (
            "## MP: 结构准备\n"
            "1. MP 库: fetch_mp_structure(mp-id/化学式) → 自动 VASP5 POSCAR\n"
            "2. 自建: build_structure(prototype) / build_from_spacegroup(sg)\n"
            "3. 缺陷工程: edit_structure(substitute|vacancy|insert|scale)\n"
            "4. 约化/对称: primitive_cell / symmetry_report\n"
            "5. 预览: view_structure_ase\n"
            "6. 后处理: make_supercell / cleave_surface / interfaces.*"
        ),
        "relax": (
            "## MP RelaxMaker → 本仓库\n"
            "- 模板: mp_relax_static 或 mp_relax_band 的 relax 步\n"
            "- INCAR 对齐: PREC=Accurate, EDIFF=1e-5, EDIFFG=-0.02, IBRION=2, ISIF=3\n"
            "- 工具单步: generate_vasp_inputs(calc_type='relax')\n"
            "- MP 区分固定晶胞/全弛豫; 本仓库 mp 模板默认 ISIF=3\n"
            "- 力收敛后 advance → 下一步用 CONTCAR 作新 POSCAR（人工/脚本）"
        ),
        "electronic": (
            "## MP Static / Band / DOS → 本仓库\n"
            "- Static SCF: 步骤 vasp_static（NSW=0, LCHARG=.TRUE., ISMEAR=-5）\n"
            "- Band: 步骤 vasp_band（ICHARG=11 + 自动高对称 line-mode KPOINTS）\n"
            "- DOS: vasp_static_dos 或 generate_dos_inputs\n"
            "- 解析: analyze_vasprun / plot_band / plot_dos / plot_pdos\n"
            "- 模板: mp_relax_band = relax → static → bands → dos → extract → report"
        ),
        "dielectric": (
            "## MP Dielectric / Optics → 本仓库\n"
            "- 本仓库: generate_optical_inputs（LOPTICS 两步法）\n"
            "- MP DielectricMaker 多用 DFPT(LEPSILON); 此处未一等封装，光学近似可初筛"
        ),
        "elastic": (
            "## MP ElasticMaker → 本仓库\n"
            "- generate_elastic_inputs（IBRION=6 应变）\n"
            "- 体积扫描: generate_eos_inputs + fit_eos（Birch-Murnaghan）"
        ),
        "phonon": (
            "## MP Phonon / 声子\n"
            "- 尚未一等封装 phonopy/DFPT 链\n"
            "- 临时路径: 外部 phonopy + 本仓库生成 POSCAR/INCAR 集"
        ),
        "neb": (
            "## 过渡态 NEB（工程常用，非 MP 主线）\n"
            "- generate_neb_endpoints / generate_neb_images(IDPP) / generate_neb_incar\n"
            "- IDPP 依赖 pymatgen-analysis-diffusion"
        ),
        "settings": (
            "## MP 常见设置约定（工作流入库用）\n"
            "- ENCUT: MP 默认 520 eV 量级; 本仓库 generate_vasp_inputs 按 ENMAX 启发式\n"
            "- EDIFF/EDIFFG: 见 mp_relax INCAR（1e-5 / -0.02）\n"
            "- ISMEAR: 绝缘体 -5; 金属 1/0; mp 模板 static 用 -5\n"
            "- 磁性/U: suggest_u / suggest_magnetism + generate_vasp_inputs(ldau_u=...)\n"
            "- 色散: ivdw=11 (D3) 等\n"
            "- 真实结构: start_workflow params_json 注入 poscar_text/poscar_path"
        ),
        "makers": (
            "## atomate2 Maker → MatCalcAgent 映射\n"
            "| Maker | 本仓库 |\n"
            "|---|---|\n"
            "| RelaxMaker | workflow vasp_relax / generate_vasp_inputs(relax) |\n"
            "| StaticMaker | workflow vasp_static |\n"
            "| BandStructureMaker | workflow vasp_band / generate_band_inputs |\n"
            "| DOSMaker | workflow vasp_static_dos / generate_dos_inputs |\n"
            "| OpticsMaker | generate_optical_inputs |\n"
            "| ElasticMaker | generate_elastic_inputs |\n"
            "| EOS | generate_eos_inputs + fit_eos |\n"
            "| NEB | neb.* 工具 |\n"
            "| 飞行流程 jobflow | 本仓库 state.json + advance_workflow |\n"
            "| 模式存储 MongoDB | 本仓库 outputs/ 文件树（有意简化）"
        ),
    }
    order = ("structure", "relax", "electronic", "dielectric",
             "elastic", "phonon", "neb", "settings", "makers")
    if t == "all":
        return "\n\n".join(sections[k] for k in order) + (
            "\n\n## 推荐编排\n"
            "1) fetch_mp_structure 或 build_* / import_structure\n"
            "2) start_workflow('mp_relax_band') 或 'mp_relax_static'\n"
            "3) advance_workflow 直至 done（可用 expected_revision CAS）\n"
            "4) view_structure_ase / export_report / export_result_note\n"
        )
    if t not in sections:
        return (
            "错误：[E_PARAM] topic 仅支持 all|structure|relax|electronic|"
            f"dielectric|elastic|phonon|neb|settings|makers，收到 '{topic}'"
        )
    return sections[t]


TOOLS = [fetch_mp_structure, mp_workflow_guide]
