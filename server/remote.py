"""远程计算工具层（SSH / SCP 封装；R4 起配置源统一为 clusters.json）。

- 使用系统自带 OpenSSH（ssh / scp），SSH key 认证，零额外依赖。
- 连接配置唯一真源 = 项目根 clusters.json（加载层见 matcalc/clusters.py）；
  本模块将节点字段适配为工具所需的 host/user/port/... 视图。
- 远程命令执行受白名单约束（安全边界）。

字段映射（clusters.json 节点字段 -> 本模块视图）：
    host("user@ip") -> user + host
    queue -> partition；vasp_setup -> modules；vasp_exe -> vasp_cmd
    workroot -> remote_workdir；port / ssh_key 同名
"""

from __future__ import annotations

import json
import os
import subprocess
from typing import Optional

# 远程命令白名单前缀（安全边界：模型只能执行这些）
# 含 Slurm 与 Torque/PBS 两族（master=Torque qstat/qsub；hzw 侧 sinfo 兼容）
_ALLOWED_COMMANDS = (
    "sbatch", "squeue", "sacct", "scancel", "sinfo",
    "qsub", "qstat", "qdel", "tracejob", "pbsnodes", "showq",
    "ls", "cat", "tail", "head", "mkdir", "cp", "mv", "rm", "touch",
    "nohup", "module", "which", "echo", "pwd", "hostname", "date", "df",
    "vasp_std", "vasp_gam", "vasp_ncl", "lammps", "mpirun", "srun",
    "grep", "wc", "du",
)


def _clusters_mod():
    """延迟导入 clusters 加载层（避免包/脚本两种运行方式下的导入问题）。"""
    try:
        from .matcalc import clusters as mod
    except ImportError:  # pragma: no cover —— 直接以脚本方式导入本模块时
        from matcalc import clusters as mod
    return mod


def load_config(node: Optional[str] = None) -> dict:
    """读取远程连接配置视图（来自 clusters.json 的指定节点或缺省节点）。"""
    cmod = _clusters_mod()
    n = dict(cmod.get_node(node))  # 拷贝，避免污染缓存中的真源数据
    full_host = str(n.get("host", ""))
    if "@" in full_host:
        user, _, ip = full_host.partition("@")
    else:
        user, ip = "", full_host
    return {
        "host": ip,
        "user": user,
        "port": str(n.get("port", 22)),
        "ssh_key": n.get("ssh_key") or "",
        "partition": n.get("queue", ""),
        "modules": n.get("vasp_setup", ""),
        "vasp_cmd": n.get("vasp_exe", ""),
        "remote_workdir": n.get("workroot", "~/matcalc"),
        "node_name": node or cmod.load_clusters().get("default_node"),
    }


# 视图字段 -> clusters.json 节点字段的写回映射（host/user 特殊处理合并语义）
_FIELD_TO_NODE = {
    "port": "port",
    "ssh_key": "ssh_key",
    "partition": "queue",
    "modules": "vasp_setup",
    "vasp_cmd": "vasp_exe",
    "remote_workdir": "workroot",
}


def save_config(node: Optional[str] = None, **kwargs) -> dict:
    """更新 clusters.json 中目标节点的连接字段（读-改-写回，不触碰 notes 等其余内容）。

    兼容旧调用约定：host/user 可分开提供，内部合并为 "user@ip" 存储节点 host 字段；
    未提供的字段保持原值；未知键忽略。
    """
    cmod = _clusters_mod()
    data = cmod.load_clusters(force=True)
    name = node or data.get("default_node")
    if name not in data.get("nodes", {}):
        raise KeyError(f"未知节点 '{name}'；可用节点: {', '.join(sorted(data['nodes']))}")
    n = data["nodes"][name]

    new_host = kwargs.get("host")
    new_user = kwargs.get("user")
    if isinstance(new_host, str) and "@" in new_host:
        n["host"] = new_host.strip()
    else:
        cur_user, _, cur_ip = str(n.get("host", "")).partition("@")
        if isinstance(new_user, str) and new_user.strip():
            cur_user = new_user.strip()
        if isinstance(new_host, str) and new_host.strip():
            cur_ip = new_host.strip()
        n["host"] = f"{cur_user}@{cur_ip}" if (cur_user and cur_ip) else cur_ip

    for k, field in _FIELD_TO_NODE.items():
        v = kwargs.get(k)
        if v is None:
            continue
        n[field] = v if isinstance(v, (int, float)) else str(v).strip()

    cmod._CACHE = None  # 使缓存失效，后续读取立即可见
    with open(cmod.CLUSTERS_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")
    return load_config(name)


def _check_command(command: str) -> Optional[str]:
    """远程命令白名单校验。返回错误信息或 None。"""
    cmd = command.strip()
    if not cmd:
        return "错误：[E_PARAM] 命令为空"
    first = cmd.split()[0]
    # 允许 bash 包装的常见组合，但首词必须在白名单
    if first not in _ALLOWED_COMMANDS:
        return (
            f"错误：[E_PARAM] 远程命令 '{first}' 不在白名单内。"
            f"允许: {', '.join(_ALLOWED_COMMANDS[:14])} …\n"
            "请将任务拆分为白名单命令执行。"
        )
    # 禁止明显的危险重定向/管道逃逸
    for bad in ("&&", "||", ";", "|", ">", "<", "`", "$("):
        if bad in command:
            return f"错误：[E_PARAM] 命令包含不允许的字符 '{bad}'（安全限制）"
    return None


_SSH_EXE = r"C:\Windows\System32\OpenSSH\ssh.exe"
_SCP_EXE = r"C:\Windows\System32\OpenSSH\scp.exe"


def _ssh_bin() -> str:
    """优先系统自带 OpenSSH 绝对路径；规避服务进程 PATH 解析差异导致的挂起。"""
    return _SSH_EXE if os.path.exists(_SSH_EXE) else "ssh"


def _scp_bin() -> str:
    return _SCP_EXE if os.path.exists(_SCP_EXE) else "scp"


def _ssh_base(cfg: dict, extra: str = "") -> list[str]:
    cmd = [
        _ssh_bin(), "-p", str(cfg["port"]),
        "-o", "BatchMode=yes",
        "-o", "ConnectTimeout=15",
        "-o", "StrictHostKeyChecking=accept-new",
        "-n",  # 不读 stdin：根除无头环境下任何交互挂起的可能
    ]
    if cfg.get("ssh_key"):
        cmd += ["-i", os.path.expanduser(cfg["ssh_key"])]
    if extra:
        cmd.append(extra)
    cmd.append(f'{cfg["user"]}@{cfg["host"]}')
    return cmd


def _diag_write(line: str) -> None:
    """旁路诊断日志：outputs/_ssh_diag.log（定位无头环境 ssh 行为用，可随时摘除）。"""
    try:
        p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "outputs", "_ssh_diag.log")
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:  # noqa: BLE001
        pass


def ssh_prefix_for_node(node_cfg: dict, scp: bool = False) -> list[str]:
    """【jobs 层唯一真源】由 clusters.json 节点字典构造 ssh/scp 完整选项前缀。

    此前 jobs 层(main._run_local/_ssh_base)与本模块各持一套 subprocess/认证
    构造，导致无头挂起类缺陷需两处修（2026-08-27 实证）——现统一经由本函数。
    scp 不支持 -n，且端口旗标为 -P，故分叉处理。
    """
    port = str(node_cfg.get("port", 22))
    args = [
        _scp_bin() if scp else _ssh_bin(),
        "-o", "BatchMode=yes",
        "-o", "ConnectTimeout=20",
        "-o", "StrictHostKeyChecking=accept-new",
    ]
    args += ["-P" if scp else "-p", port]
    if not scp:
        args.append("-n")  # 不读 stdin：根除无头环境交互挂起
    if node_cfg.get("ssh_key"):
        args += ["-i", os.path.expanduser(str(node_cfg["ssh_key"]))]
    return args


def _run(cmd_list: list[str], timeout: int = 120) -> dict:
    import time as _t

    t0 = _t.time()
    _diag_write(f"START {_t.strftime('%H:%M:%S')} {' '.join(cmd_list[:4])}...")
    try:
        proc = subprocess.run(
            cmd_list, capture_output=True, text=True, timeout=timeout, encoding="utf-8",
            errors="replace",
        )
        out = {
            "exit": proc.returncode,
            "stdout": proc.stdout[-8000:],
            "stderr": proc.stderr[-4000:],
        }
        _diag_write(f"END   耗时{_t.time()-t0:.1f}s exit={proc.returncode}")
        return out
    except FileNotFoundError:
        _diag_write(f"END   耗时{_t.time()-t0:.1f}s FileNotFound")
        return {"exit": 127, "stdout": "", "stderr": "[E_SSH] 错误：未找到 ssh/scp 命令（请确认 OpenSSH 已安装）"}
    except subprocess.TimeoutExpired:
        _diag_write(f"END   耗时{_t.time()-t0:.1f}s TIMEOUT({timeout}s)")
        return {"exit": 124, "stdout": "", "stderr": f"[E_SSH] 错误：执行超时（>{timeout}s）"}
    except Exception as e:  # noqa: BLE001
        _diag_write(f"END   耗时{_t.time()-t0:.1f}s EXC:{e}")
        return {"exit": 1, "stdout": "", "stderr": f"[E_SSH] 错误：执行异常: {e}"}


def ssh_run(command: str, remote_dir: Optional[str] = None) -> dict:
    """在远程主机执行白名单命令。

    Args:
        command: 白名单内的远程命令（如 "sbatch run.sh"、"tail -20 OUTCAR"）。
        remote_dir: 可选，先 cd 到该远程目录再执行。

    Returns:
        {"exit": 退出码, "stdout": ..., "stderr": ...}
    """
    cfg = load_config()
    if not cfg["host"] or not cfg["user"]:
        return {"exit": 2, "stdout": "",
                "stderr": "未配置远程主机。请先调用 configure_remote 设置 host/user（SSH key 认证）。"}

    err = _check_command(command)
    if err:
        return {"exit": 2, "stdout": "", "stderr": err}

    full = f"cd {remote_dir or cfg['remote_workdir']} && {command}" if (remote_dir or cfg["remote_workdir"]) else command
    cmd_list = _ssh_base(cfg) + [full]
    return _run(cmd_list)


def upload(local_path: str, remote_path: Optional[str] = None) -> dict:
    """上传本地文件到远程（scp，BatchMode）。

    Args:
        local_path: 本地文件路径。
        remote_path: 远程目标路径；缺省为配置的 remote_workdir 下的同名文件。
    """
    cfg = load_config()
    if not cfg["host"] or not cfg["user"]:
        return {"exit": 2, "stdout": "", "stderr": "未配置远程主机。请先调用 configure_remote。"}
    if not os.path.isfile(local_path):
        return {"exit": 2, "stdout": "", "stderr": f"错误：[E_PARAM] 本地文件不存在 {local_path}"}
    dest = remote_path or f"{cfg['remote_workdir']}/{os.path.basename(local_path)}"
    cmd = [
        _scp_bin(), "-P", str(cfg["port"]),
        "-o", "BatchMode=yes", "-o", "ConnectTimeout=15",
        "-o", "StrictHostKeyChecking=accept-new",
    ]
    if cfg.get("ssh_key"):
        cmd += ["-i", os.path.expanduser(cfg["ssh_key"])]
    cmd += [local_path, f'{cfg["user"]}@{cfg["host"]}:{dest}']
    return _run(cmd)


def download(remote_path: str, local_path: Optional[str] = None) -> dict:
    """从远程下载文件到本地（scp，BatchMode）。

    Args:
        remote_path: 远程文件路径。
        local_path: 本地保存路径；缺省保存到 server/outputs 下同名文件。
    """
    cfg = load_config()
    if not cfg["host"] or not cfg["user"]:
        return {"exit": 2, "stdout": "", "stderr": "未配置远程主机。请先调用 configure_remote。"}
    dest = local_path or os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "outputs", os.path.basename(remote_path)
    )
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    cmd = [
        _scp_bin(), "-P", str(cfg["port"]),
        "-o", "BatchMode=yes", "-o", "ConnectTimeout=15",
        "-o", "StrictHostKeyChecking=accept-new",
    ]
    if cfg.get("ssh_key"):
        cmd += ["-i", os.path.expanduser(cfg["ssh_key"])]
    cmd += [f'{cfg["user"]}@{cfg["host"]}:{remote_path}', dest]
    return _run(cmd)


def check_connection() -> dict:
    """测试 SSH 连接与关键命令可用性（BatchMode key 认证）。"""
    cfg = load_config()
    if not cfg["host"] or not cfg["user"]:
        return {"exit": 2, "stdout": "", "stderr": "未配置远程主机。请先调用 configure_remote。"}
    probe = _run(_ssh_base(cfg) + ["hostname && which squeue && which vasp_std || true"])
    probe["note"] = "已探测：hostname / squeue / vasp_std"
    return probe
