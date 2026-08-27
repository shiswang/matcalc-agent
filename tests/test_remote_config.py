"""R4 远程配置统一回归：remote.py 读 clusters.json 视图 / configure_remote merge 写回。

安全红线：clusters.json 全程不得出现 password 类字段。
"""
import json
from pathlib import Path

import pytest

from server import remote
from server.matcalc import clusters as clusters_mod


# ---------- 节点字段 -> 工具视图（自包含：用下方 fake_clusters，不依赖真实拓扑） ----------

def test_load_config_default_node_view(fake_clusters):
    cfg = remote.load_config()  # default = master（来自临时 clusters.json）
    assert cfg["host"] == "10.20.119.71"          # 从 "ls@10.20.119.71" 拆解
    assert cfg["user"] == "ls"
    assert str(cfg["port"]) == "22"
    assert "id_rsa_192_168_10_152" in cfg["ssh_key"]
    assert cfg["partition"] == "amd256c"          # queue -> partition
    assert cfg["modules"] == "module load apps/vasp/5.4.4"  # vasp_setup -> modules
    assert cfg["vasp_cmd"] == "vasp_std"
    assert cfg["remote_workdir"] == "~/matcalc"


def test_load_config_explicit_hzw(fake_clusters):
    cfg = remote.load_config("hzw")
    assert cfg["user"] == "hzw"
    assert cfg["partition"] == "hzw"
    assert cfg["vasp_cmd"].endswith("/path/vasp_std")


# ---------- save_config：merge 写回，不破坏既有内容 ----------

_MINIMAL_CLUSTERS = {
    "schema_version": 1,
    "default_node": "master",
    "local_potcar_lib": "potcars/potpaw_PBE",
    "nodes": {
        "master": {
            "host": "ls@10.20.119.71", "port": 22, "ssh_key": "~/.ssh/id_rsa_192_168_10_152",
            "scheduler": "torque", "queue": "amd256c", "max_ppn": 128,
            "vasp_setup": "module load apps/vasp/5.4.4", "vasp_exe": "vasp_std",
            "lammps_exe": None, "workroot": "~/matcalc", "notes": ["keep-me-1"],
        },
        "hzw": {
            "host": "hzw@10.20.112.88", "port": 22, "ssh_key": "~/.ssh/id_rsa",
            "scheduler": "torque", "queue": "hzw", "max_ppn": 96,
            "vasp_setup": "source oneapi", "vasp_exe": "/path/vasp_std",
            "lammps_exe": "~/.dp1s/envs/dp1s/bin/lmp", "workroot": "~/matcalc",
            "notes": ["keep-me-2"],
        },
    },
}


@pytest.fixture()
def fake_clusters(tmp_path, monkeypatch):
    p = tmp_path / "clusters.json"
    p.write_text(json.dumps(_MINIMAL_CLUSTERS, ensure_ascii=False, indent=2), encoding="utf-8")
    monkeypatch.setattr(clusters_mod, "CLUSTERS_PATH", str(p))
    monkeypatch.setattr(clusters_mod, "_CACHE", None)
    return p


def test_save_config_merges_and_keeps_notes(fake_clusters):
    out = remote.save_config(node="master", partition="amd256x")
    assert out["partition"] == "amd256x"  # 返回的是新视图

    data = json.loads(fake_clusters.read_text(encoding="utf-8"))
    m = data["nodes"]["master"]
    assert m["queue"] == "amd256x"                # partition 落到 queue 字段
    assert m["host"] == "ls@10.20.119.71"         # 未给 host/user 时保持原值
    assert m["notes"] == ["keep-me-1"]            # 其余内容不被触碰
    assert data["schema_version"] == 1


def test_save_config_host_user_merge_semantics(fake_clusters):
    remote.save_config(node="hzw", host="10.20.112.99", user="hzw2")
    data = json.loads(fake_clusters.read_text(encoding="utf-8"))
    assert data["nodes"]["hzw"]["host"] == "hzw2@10.20.112.99"


def test_save_config_combined_host_form_wins(fake_clusters):
    remote.save_config(node="hzw", host="someone@10.0.0.1", user="ignored")
    data = json.loads(fake_clusters.read_text(encoding="utf-8"))
    assert data["nodes"]["hzw"]["host"] == "someone@10.0.0.1"


def test_save_config_unknown_node_raises(fake_clusters):
    with pytest.raises(KeyError):
        remote.save_config(node="__nope__", partition="x")


def test_load_config_unknown_node_raises():
    # 不依赖真实配置：对任意环境都成立
    with pytest.raises(KeyError):
        remote.load_config("__nope__")


# ---------- 安全边界 ----------

def test_whitelist_still_blocks_shell_escape():
    assert remote._check_command("rm -rf x && echo pwned") is not None
    assert remote._check_command("cat /etc/passwd; echo") is not None
    assert remote._check_command("tail -20 OSZICAR") is None


def test_no_password_anywhere_in_real_clusters_json():
    text = Path(clusters_mod.CLUSTERS_PATH).read_text(encoding="utf-8")
    assert "password" not in text.lower()
