"""V 驱动与 Cu 驱动的"同构部分"守卫。

背景：两个驱动（`run_v2_campaign.py` / `cu/run_cu_campaign.py`）是照着写的，共享 15 个
函数名。2026-10-20 实测（AST 归一化后逐函数比较）：**只有 2 个函数真正逐字相同**
（`_assert_incar_stage`、`handle`），其余 13 个已按各自体系的约定/路径改写过 ——
所以"抽公共模块"的收益比最初估计的小，改造风险比估计的大。

这里不去动那两个驱动的实现（它们是本项目最难验证的代码：提交集群、无法离线跑通），
改为把**同构关系显式钉住**：

1. 共享的函数名不能悄悄消失（改名/删除会让人以为两套驱动已合并）；
2. 真正共享实现的两个函数必须保持逐字一致（漂移了就红）；
3. 两套驱动的 +U 约定必须覆盖同一批元素、且共享元素取值相同 ——
   这正是账本 #84 那种"按错键"事故的兜底。

改驱动时如果确实要让某个函数分叉，请同步更新下面的 EXPECTED_SHARED_NAMES /
EXPECTED_IDENTICAL，并在提交说明里写清为什么分叉。
"""
from __future__ import annotations

import ast
import io
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
CAMPAIGN_DIR = REPO / 'scripts' / 'campaigns' / '024_CuFeMn_V'
V2_PATH = CAMPAIGN_DIR / 'run_v2_campaign.py'
CU_PATH = CAMPAIGN_DIR / 'cu' / 'run_cu_campaign.py'

# 2026-10-20 实测：两驱动共有的函数名
EXPECTED_SHARED_NAMES = {
    '_assert_incar_stage', '_collect_one', '_read_submission', '_remote_submission',
    '_submit_remote', '_tar_dirs', 'assert_convention', 'defect_incar', 'defect_inputs',
    'defect_relax', 'energies', 'handle', 'parent_relax', 'statics', 'u_from_outcar',
}
# 其中实现必须逐字相同的（协议级共用）
EXPECTED_IDENTICAL = {'_assert_incar_stage', 'handle'}


def _functions(path: Path) -> dict[str, str]:
    tree = ast.parse(io.open(path, encoding='utf-8').read())
    out = {}
    for node in tree.body:
        if isinstance(node, ast.FunctionDef):
            out[node.name] = ast.unparse(node)
    return out


@pytest.fixture(scope='module')
def drivers():
    if not V2_PATH.exists() or not CU_PATH.exists():
        pytest.skip('campaign drivers not present')
    return _functions(V2_PATH), _functions(CU_PATH)


def test_shared_function_names_still_exist(drivers):
    v2, cu = drivers
    shared = set(v2) & set(cu)
    missing = EXPECTED_SHARED_NAMES - shared
    assert not missing, f'两驱动不再共有这些函数（改名或删除？）：{sorted(missing)}'


def test_protocol_functions_stay_identical(drivers):
    v2, cu = drivers
    for name in sorted(EXPECTED_IDENTICAL):
        assert name in v2 and name in cu, f'{name} 缺失'
        assert v2[name] == cu[name], (
            f'{name} 在两个驱动里已分叉：它属于协议级共用实现，'
            f'要么一起改，要么把它移出 EXPECTED_IDENTICAL 并写明原因'
        )


def test_u_conventions_cover_the_same_elements(drivers):
    """两套体系的 +U 约定必须覆盖同一批元素，共享元素取值相同（#84 的兜底）。"""
    if str(CAMPAIGN_DIR) not in sys.path:
        sys.path.insert(0, str(CAMPAIGN_DIR))
    sys.path.insert(0, str(CAMPAIGN_DIR / 'cu'))
    import run_cu_campaign as cu
    import run_v2_campaign as v2

    v_only = 'V'
    cu_only = 'Cu'
    v_shared = {k: val for k, val in v2.CONVENTION.items() if k != v_only}
    cu_shared = {k: val for k, val in cu.CONVENTION.items() if k != cu_only}
    assert set(v_shared) == set(cu_shared), (
        f'两套约定的元素集合不一致：仅 V 有 {set(v_shared) - set(cu_shared)}，'
        f'仅 Cu 有 {set(cu_shared) - set(v_shared)}'
    )
    diff = {k: (v_shared[k], cu_shared[k]) for k in v_shared if v_shared[k] != cu_shared[k]}
    assert not diff, f'共享元素的 +U 取值不一致：{diff}'
