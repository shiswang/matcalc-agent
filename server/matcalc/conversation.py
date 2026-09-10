"""MatCalcAgent 的会话作用域路由适配。

长期事实只保存在 workflow 的 state.json；本模块不把全局任务广播到每个会话。
默认消息直接交给 DSH agent，只有显式计算控制意图才读取相关任务状态。
"""
from __future__ import annotations

import re
from typing import Optional

from . import workflows

_CONTINUE = re.compile(r"(?:^|\s)(?:继续|恢复|接着|推进|跑下去|往下做)(?:\s|$)|继续(?:一下|计算|任务)")
_STATUS = re.compile(
    r"(?:状态|进度|作业号|排队|运行到哪|完成了吗|查一下任务|任务列表|工作流列表|"
    r"列出.*工作流|查看.*工作流)"
)
_GLOBAL_STATUS = re.compile(r"(?:所有|全部|哪些|有什么|当前.*(?:计算|作业|任务)|在跑)")
_TARGET_CUE = re.compile(
    r"(?:继续|恢复|接着|推进|状态|进度|查看|查询|作业号|任务)\s*"
    r"(?:项目|工作流|workflow|wf[_-]?id)?\s*[A-Za-z][A-Za-z0-9_.+/-]{1,}", re.I
)
_EXPLANATION = re.compile(r"(?:什么是|怎么|如何|为什么|解释|介绍|区别|原理|学习)")
_CREATE = re.compile(
    r"(?:新建|开始|帮我(?:算|计算)|生成.*(?:输入|结构)|提交.*(?:弛豫|DOS|VASP)|"
    r"测试.*(?:体系|计算|workflow)|跑.*(?:简单|测试))"
)
_FORMULA = re.compile(
    r"(?<![A-Za-z])([A-Z][a-z]?(?:\d+(?:\.\d+)?)?"
    r"(?:[A-Z][a-z]?(?:\d+(?:\.\d+)?)?)*)"
)
_TEMPLATES = ("smoke_local_chain", "nmo_parent_compare", "relax_dos_standard")
_TASK_CUE = re.compile(r"(?:VASP|LAMMPS|workflow|POSCAR|OUTCAR|DOS|PDOS|弛豫|作业|集群|提交|计算|材料|结构)", re.I)
_SCOPE_CUE = re.compile(r"(?:wf[_-]?id|workflow|项目|作业号|[A-Za-z]+_[A-Za-z]+_\d+)", re.I)


def classify_message(text: str) -> str:
    """将当前消息分类为 general_chat/task_create/task_continue/task_status。"""
    text = (text or "").strip()
    if not text:
        return "general_chat"
    if _CONTINUE.search(text):
        return "task_continue"
    if _STATUS.search(text):
        return "task_status"
    if _CREATE.search(text) or any(t in text for t in _TEMPLATES):
        return "task_create"
    if "VASP" in text.upper() and _FORMULA.search(text):
        return "task_create"
    return "general_chat"


def _has_explicit_task_reference(text: str) -> bool:
    """判断消息是否明确寻址任务，而不是仅含一个泛化控制词。"""
    value = text or ""
    # 泛词“workflow/项目”本身不是地址；必须带 ID、项目名或控制词后的目标词。
    concrete_scope = re.search(
        r"(?:wf[_-]?id\s*[:=]?\s*[A-Za-z0-9_.-]+|"
        r"项目\s*[：:]?\s*[A-Za-z][A-Za-z0-9_.-]+)", value, re.I)
    if concrete_scope or _TARGET_CUE.search(value):
        return True
    # 化学式只在控制语境中视为任务地址；“解释 NaCl 的键”仍是普通问答。
    if _CONTINUE.search(value) or _STATUS.search(value):
        for match in _FORMULA.finditer(value):
            if match.group(1) not in {"VASP", "DOS", "POSCAR"}:
                return True
    return False


def extract_task_request(text: str) -> dict:
    """提取新任务元数据；只做编排建议，不创建或提交任务。"""
    text = (text or "").strip()
    formula = next((m.group(1) for m in _FORMULA.finditer(text)
                    if m.group(1) not in {"VASP", "DOS", "POSCAR"}), None)
    template = next((t for t in _TEMPLATES if t in text), None)
    return {
        "composition": formula,
        "template": template,
        "next_tool": "build_structure" if formula and template != "smoke_local_chain" else None,
        # 结构生成是低风险；缺少必要信息时由 agent 继续询问。
        "requires_confirmation": not bool(formula and template),
    }


def route_message(text: str, project: Optional[str] = None,
                  wf_id: Optional[str] = None,
                  workflow_ids: Optional[list[str]] = None,
                  session_focused: bool = False) -> dict:
    """路由当前消息；默认不读取全局状态，且绝不直接推进 workflow。

    ``workflow_ids`` 是当前会话的持久化焦点范围；没有焦点时，只有用户
    明确提出继续/状态意图才允许使用显式 project/wf_id 或候选选择。
    """
    intent = classify_message(text)
    if intent in ("task_continue", "task_status"):
        # 裸“继续/状态”不应因为系统里有任务就劫持普通话题；
        # 只有当前会话仍处于任务焦点、用户明确寻址，或显式要求全局看板时才路由。
        addressed = _has_explicit_task_reference(text)
        global_query = intent == "task_status" and bool(_GLOBAL_STATUS.search(text))
        has_binding = bool(wf_id or workflow_ids)
        if (not session_focused or (not has_binding and not addressed)) and not addressed and not global_query:
            return {"intent": intent, "action": "pass_through",
                    "mutates_workflow": False, "reason": "no_task_focus"}
        if intent == "task_status" and _GLOBAL_STATUS.search(text):
            # “全部/所有”是用户显式请求任务中心，不受当前 session 的历史 scope 限制。
            rows = workflows._active_workflow_records(project, None)
            return {
                "intent": intent, "action": "overview", "mutates_workflow": False,
                "candidates": rows,
                "message": workflows.list_active_workflows(project),
            }
        result = workflows.route_workflow_request(
            text, project=project, wf_id=wf_id, workflow_ids=workflow_ids)
        result["intent"] = intent
        result["mutates_workflow"] = False
        return result
    if intent == "task_create":
        task = extract_task_request(text)
        return {
            "intent": intent, "action": "create_required",
            "mutates_workflow": False, **task,
            "message": "这是新任务请求；请调用已有工具创建新的 workflow，不覆盖已有任务。",
        }
    # 关键：普通聊天返回决策数据，但不向模型注入提示。
    return {"intent": intent, "action": "pass_through", "mutates_workflow": False}


def startup_context(project: Optional[str] = None,
                    workflow_ids: Optional[list[str]] = None) -> str:
    """按会话焦点生成恢复摘要；无焦点时不应由插件主动调用。"""
    if not project and not workflow_ids:
        return ""
    return workflows.startup_recovery_summary(project, workflow_ids)
