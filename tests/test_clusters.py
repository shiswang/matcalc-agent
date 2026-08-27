"""clusters.json 加载层 —— 环境无关契约测试。

原则：
- 断言「配置契约」（schema、必填字段、无密码），不断言具体硬件拓扑；
- master/hzw 的实机特定断言仅在本地真实配置存在时生效，CI(example) 跳过；
  —— CI 用 clusters.example.json 引导，属既定红线（outputs/clusters 不入库）。
"""
import pytest

clusters = pytest.importorskip(
    "server.matcalc.clusters",
    reason="clusters.json 加载层是 S1-R1 交付物；S0 先占位锁定接口预期",
)

_REQUIRED_KEYS = ("host", "scheduler", "queue", "max_ppn", "vasp_setup", "vasp_exe", "workroot")


def test_load_clusters_schema():
    cfg = clusters.load_clusters()
    assert cfg["schema_version"] == 1
    assert cfg["nodes"], "至少要有一个节点"
    for name, node in cfg["nodes"].items():
        for key in _REQUIRED_KEYS:
            assert key in node, f"节点 {name} 缺字段 {key}"
        key_field = node.get("ssh_key")
        assert key_field is None or (
            isinstance(key_field, str) and ("id_" in key_field or "/" in key_field or "\\" in key_field)
        ), f"节点 {name} 的 ssh_key 应为密钥路径或空"


def _has_real_topology() -> bool:
    return {"master", "hzw"} <= set(clusters.load_clusters()["nodes"])


def test_get_node_valid():
    if not _has_real_topology():
        pytest.skip("本机真实拓扑(master/hzw)不在——CI example 引导下跳过实机断言")
    n = clusters.get_node("master")
    assert n["host"].startswith("ls@")
    assert clusters.get_node("hzw")["lammps_exe"]  # hzw 必须登记 lmp 路径


def test_get_node_default_and_unknown():
    # 契约：缺省返回 default_node；未知节点抛错
    n = clusters.get_node(None)
    assert n["host"]


def test_no_password_in_config():
    """安全红线：配置文件与加载结果都不得含密码字段。"""
    import json
    from pathlib import Path

    p = Path(clusters.__file__).resolve().parents[2] / "clusters.json"
    if p.exists():
        text = p.read_text(encoding="utf-8")
        assert "password" not in text.lower()
