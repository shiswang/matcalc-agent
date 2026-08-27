"""clusters.json 加载层 —— 集群机器字段唯一真源（《M5架构设计_v1》§3）。

纪律：
- 配置不含任何密码；ssh_key 只存路径（加载时 expanduser 展开）；
- 首次访问即全量校验，必填缺失直接抛错（fail-fast，宁可不跑不带病运行）;
- CLUSTERS.md 保留为人类运维档案（经验/踩坑），两者不自动同步。
"""
from __future__ import annotations

import json
import os
from typing import Any, Optional

# server/matcalc/clusters.py → 项目根
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CLUSTERS_PATH = os.path.join(ROOT, "clusters.json")

_REQUIRED_NODE_FIELDS = (
    "host", "scheduler", "queue", "max_ppn", "vasp_setup", "vasp_exe", "workroot",
)

_CACHE: Optional[dict[str, Any]] = None


def load_clusters(force: bool = False) -> dict[str, Any]:
    """读取并校验 clusters.json（结果缓存；force=True 强制重读）。"""
    global _CACHE
    if _CACHE is not None and not force:
        return _CACHE
    if not os.path.exists(CLUSTERS_PATH):
        raise FileNotFoundError(
            f"缺少集群配置 {CLUSTERS_PATH}（机器字段唯一真源；字段规范见《M5架构设计_v1》§3）"
        )
    with open(CLUSTERS_PATH, encoding="utf-8") as f:
        cfg = json.load(f)
    if cfg.get("schema_version") != 1:
        raise ValueError(
            f"clusters.json 的 schema_version 必须为 1，收到 {cfg.get('schema_version')!r}"
        )
    nodes = cfg.get("nodes") or {}
    if not nodes:
        raise ValueError("clusters.json 缺少 nodes 配置")
    for name, node in nodes.items():
        missing = [k for k in _REQUIRED_NODE_FIELDS if k not in node]
        if missing:
            raise ValueError(f"节点 {name} 缺少必填字段: {', '.join(missing)}")
        if node.get("ssh_key"):
            node["ssh_key"] = os.path.expanduser(str(node["ssh_key"]))
    _CACHE = cfg
    return cfg


def get_node(name: Optional[str] = None) -> dict[str, Any]:
    """取指定节点配置；缺省返回 default_node。未知节点报错并列出可用项。"""
    cfg = load_clusters()
    name = name or cfg.get("default_node")
    nodes = cfg["nodes"]
    if name not in nodes:
        raise KeyError(f"未知节点 '{name}'；可用节点: {', '.join(sorted(nodes))}")
    return nodes[name]


def local_potcar_lib() -> str:
    """本地赝势库绝对路径（clusters.json 的 local_potcar_lib 相对项目根解析）。"""
    cfg = load_clusters()
    p = cfg.get("local_potcar_lib") or "potcars/potpaw_PBE"
    if not os.path.isabs(p):
        p = os.path.join(ROOT, p)
    return p
