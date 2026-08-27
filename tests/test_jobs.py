"""作业守护层回归：NODES 注册表 / run.pbs 生成 / LF 规范化（全离线）。"""
import pytest

import server.main as mc


# ---------- NODES 注册表（本机真实拓扑一致性；CI example 引导下跳过） ----------

def _has_real_topology() -> bool:
    return {"master", "hzw"} <= set(mc.NODES)


def test_nodes_registry_keys():
    if not _has_real_topology():
        pytest.skip("本机真实拓扑(master/hzw)不在——CI example 引导下跳过实机断言")
    assert set(mc.NODES) == {"master", "hzw"}


def test_master_profile():
    if not _has_real_topology():
        pytest.skip("本机真实拓扑不在——跳过")
    n = mc.NODES["master"]
    assert n["queue"] == "amd256c"
    assert n["max_ppn"] == 128
    assert n["vasp_setup"] == "module load apps/vasp/5.4.4"
    assert n["vasp_exe"] == "vasp_std"


def test_hzw_profile():
    if not _has_real_topology():
        pytest.skip("本机真实拓扑不在——跳过")
    n = mc.NODES["hzw"]
    assert n["queue"] == "hzw"
    assert n["max_ppn"] == 96
    assert "oneapi/setvars.sh" in n["vasp_setup"]
    assert n["vasp_exe"].endswith("vasp.6.6.0/bin/vasp_std")


# ---------- run.pbs 生成 ----------

def test_make_run_pbs_master():
    if not _has_real_topology():
        pytest.skip("本机真实拓扑不在——跳过")
    s = mc._make_run_pbs("master", "jobtest", 48)
    assert s.startswith("#!/bin/bash")
    assert "#PBS -q amd256c" in s
    assert "#PBS -N jobtest" in s
    assert "#PBS -l nodes=1:ppn=48" in s
    assert "module load apps/vasp/5.4.4" in s
    assert "mpirun -np $NP -machinefile $PBS_NODEFILE vasp_std > vasp.out 2>&1" in s
    assert "\r" not in s  # 生成的脚本文本天然 LF


def test_make_run_pbs_hzw():
    if not _has_real_topology():
        pytest.skip("本机真实拓扑不在——跳过")
    s = mc._make_run_pbs("hzw", "jobhz", 96)
    assert "#PBS -q hzw" in s
    assert "/home/hzw/software/vasp6.6/vasp.6.6.0/bin/vasp_std" in s
    assert "setvars.sh" in s


def test_make_run_pbs_unknown_node():
    with pytest.raises(KeyError):
        mc._make_run_pbs("__no_such_node__", "x", 8)


# ---------- LF 规范化 ----------

def test_normalize_lf(tmp_path):
    p = tmp_path / "t.txt"
    p.write_bytes(b"a\r\nb\rc\n")
    mc._normalize_lf(str(p))
    assert p.read_bytes() == b"a\nb\nc\n"


def test_normalize_lf_idempotent(tmp_path):
    p = tmp_path / "t.txt"
    p.write_bytes(b"x\r\ny\n")
    mc._normalize_lf(str(p))
    once = p.read_bytes()
    mc._normalize_lf(str(p))
    assert p.read_bytes() == once == b"x\ny\n"


# ---------- submit_and_watch 离线干跑（真机冒烟前的输入门禁回归） ----------

def test_submit_rejects_missing_local_dir_offline(tmp_path):
    """目录不存在时必须在联网前报错退出——保证坏输入不会打到集群。"""
    out = mc.submit_and_watch(
        project="pytest_dry", local_dir=str(tmp_path / "no_such_dir"),
        poll_seconds=1, max_polls=1,
    )
    assert out.startswith("错误"), out[:200]


def test_submit_unknown_node_offline():
    out = mc.submit_and_watch(
        project="pytest_dry", local_dir=".", node="__nope__",
        poll_seconds=1, max_polls=1,
    )
    assert out.startswith("错误"), out[:200]
