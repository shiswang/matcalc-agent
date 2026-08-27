"""作业守护层（自 main.py 落包，R6）：提交管线 / 轮询 / 状态查询。

设计：
- 与 remote.py 的关系：ssh/scp 前缀与子进程执行全部委托 remote 单点
  （本模块不再自行 subprocess——双轨病灶已除，账本第 28 条）；
- 配置唯一真源仍为 clusters.json（经 matcalc.clusters 加载层）；
- submit_only 是无轮询的最小提交单元：submit_and_watch 与 workflow
  的 auto_submit 都建立在其上（幂等护栏由调用方负责记录 submitted_job）。
"""
from __future__ import annotations

import os
import time
from typing import Optional

try:  # 兼容包导入与脚本直跑
    # 注意：remote 在 server/ 层（main 的兄弟模块），相对导入须上溯两级
    from .. import remote as _remote
    from .clusters import load_clusters as _load_clusters, local_potcar_lib as _potcar_lib
except ImportError:  # pragma: no cover
    from clusters import load_clusters as _load_clusters, local_potcar_lib as _potcar_lib
    import remote as _remote

NODES = _load_clusters()["nodes"]
LOCAL_POTCAR_LIB = _potcar_lib()


# ── 远程原语（薄委托 remote） ──

def ssh_base(node: str) -> list:
    """ssh 前缀——单点构造（含 -n 禁读 stdin）。"""
    return _remote.ssh_prefix_for_node(NODES[node], scp=False)


def scp_base(node: str) -> list:
    """scp 前缀——单点构造（-P 端口、无 -n）。"""
    return _remote.ssh_prefix_for_node(NODES[node], scp=True)


def run_local(cmd: list, timeout: int = 120) -> tuple[int, str]:
    """本地代发远程命令；输出沿用历史契约 stdout+stderr 拼接。"""
    r = _remote._run(list(cmd), timeout=timeout)
    return r["exit"], (r["stdout"] or "") + (r["stderr"] or "")


def make_run_pbs(node: str, job_name: str, ppn: int) -> str:
    cfg = NODES[node]
    return "\n".join([
        "#!/bin/bash",
        f"#PBS -q {cfg['queue']}",
        f"#PBS -N {job_name}",
        f"#PBS -l nodes=1:ppn={ppn}",
        "#PBS -l walltime=99:00:00",
        "#PBS -j oe",
        "",
        "cd $PBS_O_WORKDIR",
        cfg["vasp_setup"],
        "NP=$(cat $PBS_NODEFILE | wc -l)",
        'echo "started $(date) NP=$NP"',
        f"mpirun -np $NP -machinefile $PBS_NODEFILE {cfg['vasp_exe']} > vasp.out 2>&1",
        'echo "finished $(date)"',
        "",
    ])


def normalize_lf(path: str) -> None:
    with open(path, "rb") as f:
        data = f.read()
    data = data.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    with open(path, "wb") as f:
        f.write(data)


# ── 最小提交单元 ──

def submit_only(project: str, local_dir: str, node: str = "master", ppn: int = 48,
                job_name: Optional[str] = None,
                potcar_elements: Optional[str] = None) -> tuple[bool, str]:
    """校验输入→POTCAR 拼接→run.pbs→上传→qsub。成功返回 (True, job_id)，失败 (False, 错误文本)。"""
    if node not in NODES:
        return False, f"错误: [E_PARAM] 未知节点 '{node}'，可选 {list(NODES)}"
    cfg = NODES[node]
    ppn = min(ppn, cfg["max_ppn"])
    local_dir = os.path.abspath(local_dir)
    if not os.path.isdir(local_dir):
        return False, f"错误: [E_PARAM] 目录不存在 {local_dir}"
    job_name = job_name or os.path.basename(local_dir.rstrip("/\\"))

    need = ["INCAR", "KPOINTS", "POSCAR"]
    missing = [f for f in need if not os.path.isfile(os.path.join(local_dir, f))]
    if missing:
        return False, f"错误: [E_PARAM] 缺少输入文件 {missing}"
    for f in need:
        normalize_lf(os.path.join(local_dir, f))

    potcar_path = os.path.join(local_dir, "POTCAR")
    if potcar_elements and not os.path.isfile(potcar_path):
        els = [e.strip() for e in potcar_elements.split(",") if e.strip()]
        poscar_head = open(os.path.join(local_dir, "POSCAR")).read().splitlines()[5].split()
        if els != poscar_head:
            return False, f"错误: [E_PARAM] potcar_elements ({els}) 与 POSCAR 元素行 ({poscar_head}) 不一致"
        with open(potcar_path, "wb") as out:
            for el in els:
                seg = os.path.join(LOCAL_POTCAR_LIB, el, "POTCAR")
                if not os.path.isfile(seg):
                    os.remove(potcar_path)
                    return False, f"错误: [E_CLUSTER] 本地赝势库缺少 {el} ({seg})"
                with open(seg, "rb") as fh:
                    out.write(fh.read())
    if not os.path.isfile(potcar_path):
        return False, "错误: [E_PARAM] 缺少 POTCAR 且未提供 potcar_elements"

    pbs_path = os.path.join(local_dir, "run.pbs")
    with open(pbs_path, "w", newline="\n") as f:
        f.write(make_run_pbs(node, job_name.replace("_", "-"), ppn))

    remote_dir = f"{cfg['workroot']}/{project}/{job_name}"
    rc, out = run_local(ssh_base(node) + [cfg["host"], f"mkdir -p {remote_dir}"])
    if rc != 0:
        return False, f"错误: [E_CLUSTER] 远端建目录失败 {out[:200]}"
    for f in need + ["POTCAR", "run.pbs"]:
        rc, out = run_local(scp_base(node) + [os.path.join(local_dir, f), f"{cfg['host']}:{remote_dir}/{f}"])
        if rc != 0:
            return False, f"错误: [E_CLUSTER] 上传 {f} 失败 {out[:200]}"

    rc, out = run_local(ssh_base(node) + [cfg["host"],
                        f"cd {remote_dir} && dos2unix -q INCAR KPOINTS POSCAR run.pbs 2>/dev/null; qsub run.pbs"])
    if rc != 0 or not out.strip():
        return False, f"错误: [E_CLUSTER] qsub 失败 {out[:300]}"
    job_id = out.strip().splitlines()[-1].strip()
    return True, job_id


def poll_once(job_id: str, node: str, remote_dir: str) -> tuple[bool, str]:
    """查一次队列 + OSZICAR 尾行。返回 (队列中是否仍可见, OSZICAR 尾行文本)。"""
    cfg = NODES[node]
    rc, out = run_local(ssh_base(node) + [cfg["host"],
                        f"qstat -a 2>/dev/null | grep -c '{job_id.split('.')[0]}' ; tail -1 {remote_dir}/OSZICAR 2>/dev/null"])
    tail = out.strip().splitlines()
    running = tail[0].strip() if tail else "0"
    osz = tail[1].strip() if len(tail) > 1 else "(无OSZICAR)"
    return running != "0", osz


def submit_and_watch_impl(project: str, local_dir: str, node: str = "master", ppn: int = 48,
                          job_name: Optional[str] = None, potcar_elements: Optional[str] = None,
                          poll_seconds: int = 120, max_polls: int = 3) -> str:
    ok, payload = submit_only(project, local_dir, node=node, ppn=ppn,
                              job_name=job_name, potcar_elements=potcar_elements)
    if not ok:
        return payload
    job_id = payload
    cfg = NODES[node]
    jname = job_name or os.path.basename(os.path.abspath(local_dir).rstrip("/\\"))
    remote_dir = f"{cfg['workroot']}/{project}/{jname}"

    status_lines = [f"已提交: {job_id} @ {node} ({project}/{jname}, ppn={min(ppn, cfg['max_ppn'])})"]
    for k in range(max_polls):
        time.sleep(poll_seconds)
        still, osz = poll_once(job_id, node, remote_dir)
        status_lines.append(f"[{(k + 1) * poll_seconds}s] {'结束' if not still else '运行中'} | {osz}")
        if not still:
            break
    status_lines.append(f"远端目录: {remote_dir}")
    status_lines.append("后续查询: check_job(job_id=..., node=...)")
    return "\n".join(status_lines)


def check_job_impl(job_id: str, node: str = "master", remote_dir: Optional[str] = None) -> str:
    """查询作业状态：工作目录反查链=显式参数 > qstat -f 反解 > find-newest 兜底。"""
    if node not in NODES:
        return f"错误: [E_PARAM] 未知节点 '{node}'（可用: {', '.join(NODES)}）"
    cfg = NODES[node]
    jnum = job_id.split(".")[0]
    rd = remote_dir or ""
    if not rd:
        rc_f, out_f = run_local(ssh_base(node) + [cfg["host"], f"qstat -f {jnum}"])
        if rc_f == 0 and out_f.strip():
            import re
            m = re.search(r"Output_Path\s*=\s*[^:\s]*:(\S+)", out_f)
            if m:
                rd = os.path.dirname(m.group(1))
            else:
                m2 = re.search(r"PBS_O_WORKDIR=(\S+)", out_f)
                if m2:
                    rd = m2.group(1)
    if not rd:
        rd = ("$(find ~/matcalc -maxdepth 2 -name OUTCAR -newer /etc/hostname "
              "2>/dev/null | head -1 | xargs dirname 2>/dev/null)")
    cmd = (f"qstat -a 2>/dev/null | grep -c '{jnum}\\.' ; "
           f"D={rd}; echo DIR=$D; "
           f"tail -1 $D/OSZICAR 2>/dev/null; "
           f"grep -c 'reached required accuracy' $D/OUTCAR 2>/dev/null")
    rc, out = run_local(ssh_base(node) + [cfg["host"], cmd])
    return out.strip() or "(无输出)"
