"""相对路径回退到 outputs 根的逻辑：曾经漏 import，运行时直接 NameError。

背景：outputs 常量搬到 `server/matcalc/common.py` 时，`parsing.py` / `plotting.py` 里
"相对路径 → 去 outputs 根找" 的调用点没跟着改，名字 `_OUTPUTS_DIR` 在这两个模块里根本
不存在 → 走到那条分支就 `NameError: name '_OUTPUTS_DIR' is not defined`。
是 ruff 的 F821 找到的。下面的用例把它钉住。

注意：`common.OUTPUTS_DIR` 是**导入时**读环境变量的常量，所以测试用
`common.OUTPUTS_DIR` 本身（conftest 已把它指到沙箱），不要在用例里改环境变量。
"""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from server.matcalc import common, parsing, plotting


def test_modules_import_the_outputs_dir_they_use():
    """这两个模块用到的 _OUTPUTS_DIR 必须真的存在，且指向同一个 outputs 根。"""
    assert parsing._OUTPUTS_DIR == common.OUTPUTS_DIR
    assert plotting._OUTPUTS_DIR == common.OUTPUTS_DIR


@pytest.mark.parametrize(
    "call",
    [
        lambda: parsing.analyze_vasprun("no_such_dir/vasprun.xml"),
        lambda: plotting.plot_band("no_such_dir/vasprun.xml", "no_such_dir/KPOINTS"),
    ],
    ids=["analyze_vasprun", "plot_band"],
)
def test_relative_path_fallback_does_not_raise_name_error(call):
    """回退分支必须走到"文件不存在"这种可读错误，而不是 NameError。"""
    with pytest.raises(Exception) as ei:  # noqa: PT011 - 关心的是异常类型而不是具体类型
        call()
    assert not isinstance(ei.value, NameError), f"outputs 回退分支漏 import: {ei.value!r}"


def test_relative_path_is_resolved_against_outputs_root():
    """正向验证：相对路径若能在 outputs 根找到，必须被解析过去（而不是当成不存在）。"""
    d = Path(common.OUTPUTS_DIR) / "relprobe"
    d.mkdir(parents=True, exist_ok=True)
    (d / "vasprun.xml").write_text("<not-really-xml/>", encoding="utf-8")
    try:
        with pytest.raises(Exception) as ei:  # noqa: PT011 - 文件存在但内容无效，应报解析错
            parsing.analyze_vasprun("relprobe/vasprun.xml")
        assert not isinstance(ei.value, FileNotFoundError), "相对路径没有回退到 outputs 根"
    finally:
        shutil.rmtree(d, ignore_errors=True)
