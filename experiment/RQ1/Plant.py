import json
import os
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
import numpy as np

RQ1_DIR = Path(__file__).resolve().parent
BASE_DIR = RQ1_DIR.parent.parent

if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))
if str(RQ1_DIR) not in sys.path:
    sys.path.insert(0, str(RQ1_DIR))

from flow import Flow
from agents.profile.user import UserAgent
from Baseline.env.prompts import generate_user_response, judge_interviewer_action
from metric import compute_ora, compute_overall_metrics, compute_tkqr
from utils import CostTracker, json_dump_no_scientific, model_has_token_pricing

RESULTS_DIR = RQ1_DIR / "results"
DEFAULT_CONFIG_PATH = RQ1_DIR / "Plant_config.json"
FLOW_CONFIG_PATH = (RQ1_DIR / "../../config.json").resolve()
DEFAULT_DATA_PATH = (RQ1_DIR / "ReqElicitBench_10.json").resolve()
PROMPT_FOR_MAX_TASKS = True
PROMPT_FOR_RUNS = True
OUTPUT_PREFIX = "Plant"

load_dotenv(BASE_DIR / ".env")


class ExperimentLogger:
    def __init__(self, verbose: bool = True):
        self.verbose = bool(verbose)

    @staticmethod
    def _fmt(args: tuple) -> str:
        if not args:
            return ""
        if len(args) == 1:
            return str(args[0])
        msg = str(args[0])
        fmt_args = args[1:]
        try:
            return msg % fmt_args
        except Exception:
            return " ".join(str(x) for x in args)

    def info(self, *args, **kwargs):
        if self.verbose:
            print(self._fmt(args))

    def warning(self, *args, **kwargs):
        print(f"[Flow][WARN] {self._fmt(args)}")

    def error(self, *args, **kwargs):
        print(f"[Flow][ERROR] {self._fmt(args)}")


class ExperimentStore:
    """實驗用 no-op store，避免建立完整專案輸出。"""

    def __init__(self) -> None:
        self.project_id = "rq1_plant_elicitation"
        self.output_dir = RESULTS_DIR
        self.project_dir = RESULTS_DIR

    def save_artifact(self, data: Dict[str, Any]):
        pass

    def save_json(self, data: Dict[str, Any], filepath: str, indent: int = 2):
        pass

    def save_markdown(self, content: str, filename: str):
        pass

    def save_plantuml_files(self, model_data: Dict[str, Any]):
        pass

    def save_draft(self, content: str, version: int):
        pass

    def get_draft_version(self) -> int:
        return -1

    def load_draft(self, version: int):
        return None


@dataclass
class OracleConfigs:
    judge_model_config: Dict[str, Any]
    user_model_config: Dict[str, Any]


class OracleUserAgent(UserAgent):
    """將 RQ1 oracle user 接到 Plant flow 的 user agent。"""

    def __init__(
        self,
        model,
        oracle_configs: OracleConfigs,
        tools: Optional[list] = None,
        registry=None,
        project_config=None,
    ):
        super().__init__(
            model=model,
            tools=tools,
            registry=registry,
            project_config=project_config,
        )
        self.oracle = oracle_configs
        self.current_task: Dict[str, Any] = {}
        self.remaining_requirements: List[Dict[str, Any]] = []
        self.conversation_history: List[Dict[str, str]] = []
        self.last_action_info: Dict[str, Any] = {}
        self.oracle_trace: List[Dict[str, Any]] = []
        self.oracle_usage_total: Dict[str, Dict[str, int]] = {
            "judge": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            "user": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        }
        self.oracle_runtime_total_s: Dict[str, float] = {"judge": 0.0, "user": 0.0}

    @staticmethod
    def _merge_usage(dst: Dict[str, int], usage: Dict[str, Any]) -> None:
        if not isinstance(usage, dict):
            return
        dst["prompt_tokens"] = int(dst.get("prompt_tokens", 0) or 0) + int(
            usage.get("prompt_tokens", 0) or 0
        )
        dst["completion_tokens"] = int(dst.get("completion_tokens", 0) or 0) + int(
            usage.get("completion_tokens", 0) or 0
        )
        dst["total_tokens"] = int(dst.get("total_tokens", 0) or 0) + int(
            usage.get("total_tokens", 0) or 0
        )

    @staticmethod
    def _estimate_cost(model_name: str, prompt_tokens: int, completion_tokens: int) -> float:
        tracker = CostTracker(str(model_name or ""))
        return float(tracker.estimateCost(int(prompt_tokens or 0), int(completion_tokens or 0)))

    def export_cost_summary(self) -> Dict[str, Any]:
        user_usage = self.oracle_usage_total.get("user", {})

        # 成本摘要口徑：僅統計 oracle user，不納入 LLM judge。
        input_tokens = int(user_usage.get("prompt_tokens", 0) or 0)
        output_tokens = int(user_usage.get("completion_tokens", 0) or 0)
        total_tokens = int(user_usage.get("total_tokens", 0) or 0)

        user_model = str((self.oracle.user_model_config or {}).get("model_name") or "")
        estimated_cost = self._estimate_cost(
            user_model,
            int(user_usage.get("prompt_tokens", 0) or 0),
            int(user_usage.get("completion_tokens", 0) or 0),
        )

        return {
            "model": user_model,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": total_tokens,
            "run_time(s)": round(float(self.oracle_runtime_total_s.get("user", 0.0) or 0.0), 3),
            "estimated_cost(USD)": round(float(estimated_cost), 8),
        }

    def set_task(self, task: Dict[str, Any]) -> None:
        self.current_task = task
        self.conversation_history = []
        self.oracle_trace = []
        initial = str(task.get("initial_requirements") or "").strip()
        if initial:
            self.conversation_history.append({"role": "user", "content": initial})
        self.remaining_requirements = []
        for i, req in enumerate(task.get("Implicit Requirements", []) or [], start=1):
            if not isinstance(req, dict):
                continue
            text = str(req.get("RequirementText") or "").strip()
            if not text:
                continue
            self.remaining_requirements.append(
                {
                    "id": f"IR-{i:02d}",
                    "aspect": str(req.get("Aspect") or "").strip() or "Unknown",
                    "requirement": text,
                }
            )
        self.stakeholders = [
            {
                "name": "Oracle User",
                "text": [initial] if initial else ["請透過提問挖掘我的隱性需求。"],
            }
        ]

    def propose_stakeholders(self, rough_idea: str) -> List[Dict[str, str]]:
        return [{"name": "Oracle User", "reason": "RQ1 oracle stakeholder"}]

    def generate_stakeholder_requirements(
        self, rough_idea: str, selected_stakeholders: List[str]
    ) -> List[Dict[str, Any]]:
        initial = str(self.current_task.get("initial_requirements") or rough_idea).strip()
        return [
            {
                "name": "Oracle User",
                "text": [initial] if initial else ["請透過提問挖掘我的隱性需求。"],
            }
        ]

    def _latest_interviewer_inputs(
        self,
        topic: Dict[str, Any],
        previous_responses: Optional[List[Dict[str, Any]]],
    ) -> tuple[Dict[str, str], str]:
        interviewer_roles = ("analyst", "expert", "modeler")
        if previous_responses:
            latest_by_role: Dict[str, str] = {}
            for item in reversed(previous_responses):
                if not isinstance(item, dict):
                    continue
                role = str(item.get("agent") or "").strip()
                if role not in interviewer_roles or role in latest_by_role:
                    continue
                resp = item.get("response", {}) if isinstance(item.get("response"), dict) else {}
                text = str(resp.get("statement") or resp.get("content") or "").strip()
                if text:
                    latest_by_role[role] = text
                if len(latest_by_role) == len(interviewer_roles):
                    break
            if latest_by_role:
                asker = str((topic or {}).get("asker_agent") or "").strip()
                if asker and asker in latest_by_role:
                    latest_by_role = {asker: latest_by_role[asker]}
                lines = [
                    "[STRUCTURED_INTERVIEWER_ACTION]",
                    f"topic_id: {str(topic.get('id') or '').strip()}",
                    "interviewer_round_inputs:",
                ]
                for role in interviewer_roles:
                    if role in latest_by_role:
                        lines.append(f"- role: {role}")
                        lines.append(f"  statement: {latest_by_role[role]}")
                return latest_by_role, "\n".join(lines)
        fallback = str(topic.get("description") or topic.get("title") or "").strip()
        return {}, fallback

    def judge_interviewer_action_type(self, action_text: str) -> str:
        """用 oracle judge 直接判斷 interviewer 動作型態（clarify/probe/finish）。"""
        text = str(action_text or "").strip()
        if not text:
            return "probe"
        judge_t0 = time.perf_counter()
        judgement, judge_usage = judge_interviewer_action(
            action=text,
            task=self.current_task,
            model_config=self.oracle.judge_model_config,
            conversation_history=self.conversation_history,
            remaining_requirements=self.remaining_requirements,
            return_usage=True,
        )
        self.oracle_runtime_total_s["judge"] += max(0.0, time.perf_counter() - judge_t0)
        self._merge_usage(self.oracle_usage_total["judge"], judge_usage or {})
        if isinstance(judgement, dict):
            return str(judgement.get("action_type") or "probe").strip().lower() or "probe"
        return "probe"

    def respond_to_topic(self, topic, previous_responses=None, artifact_snapshot=None):
        interviewer_actions, merged_action = self._latest_interviewer_inputs(
            topic, previous_responses
        )
        topic_id = str((topic or {}).get("id") or "")
        mediator_turn = parse_mediator_turn(topic_id)
        judge_details: List[Dict[str, Any]] = []
        selected_role = ""
        selected_action = merged_action
        selected_judgement: Dict[str, Any] = {
            "action_type": "probe",
            "is_relevant_to_implied_requirements": False,
            "relevant_implied_requirements_id": None,
            "reasoning": "",
        }

        if interviewer_actions:
            ordered_roles = [r for r in ("analyst", "expert", "modeler") if r in interviewer_actions]
            for role in ordered_roles:
                action_text = interviewer_actions[role]
                judge_t0 = time.perf_counter()
                judgement, judge_usage = judge_interviewer_action(
                    action=action_text,
                    task=self.current_task,
                    model_config=self.oracle.judge_model_config,
                    conversation_history=self.conversation_history,
                    remaining_requirements=self.remaining_requirements,
                    return_usage=True,
                )
                self.oracle_runtime_total_s["judge"] += max(0.0, time.perf_counter() - judge_t0)
                self._merge_usage(self.oracle_usage_total["judge"], judge_usage or {})
                judge_details.append(
                    {
                        "role": role,
                        "action": action_text,
                        "judgement": judgement or {},
                    }
                )
                if (
                    not selected_role
                    and isinstance(judgement, dict)
                    and bool(judgement.get("is_relevant_to_implied_requirements", False))
                ):
                    selected_role = role
                    selected_action = action_text
                    selected_judgement = judgement

            if not selected_role and judge_details:
                first = judge_details[0]
                selected_role = str(first.get("role") or "")
                selected_action = str(first.get("action") or merged_action)
                selected_judgement = first.get("judgement") or selected_judgement
        else:
            selected_role = "merged"
            judge_t0 = time.perf_counter()
            judgement, judge_usage = judge_interviewer_action(
                action=selected_action,
                task=self.current_task,
                model_config=self.oracle.judge_model_config,
                conversation_history=self.conversation_history,
                remaining_requirements=self.remaining_requirements,
                return_usage=True,
            )
            self.oracle_runtime_total_s["judge"] += max(0.0, time.perf_counter() - judge_t0)
            self._merge_usage(self.oracle_usage_total["judge"], judge_usage or {})
            selected_judgement = judgement or selected_judgement

        user_response = ""
        user_usage: Dict[str, Any] = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        action_type = str(selected_judgement.get("action_type") or "").strip().lower()
        if action_type != "finish":
            user_t0 = time.perf_counter()
            user_response, user_usage = generate_user_response(
                action=selected_action,
                action_judgement=selected_judgement,
                conversation_history=self.conversation_history,
                simulator_model_config=self.oracle.user_model_config,
                remaining_requirements=self.remaining_requirements,
                return_usage=True,
            )
            self.oracle_runtime_total_s["user"] += max(0.0, time.perf_counter() - user_t0)
        self._merge_usage(self.oracle_usage_total["user"], user_usage or {})

        elicited_req_ids: List[str] = []
        is_relevant = bool(selected_judgement.get("is_relevant_to_implied_requirements", False))
        relevant_req_id = selected_judgement.get("relevant_implied_requirements_id")
        if is_relevant and relevant_req_id:
            for req in self.remaining_requirements:
                if req.get("id") == relevant_req_id:
                    elicited_req_ids.append(str(relevant_req_id))
                    break

        if elicited_req_ids:
            hit_ids = set(elicited_req_ids)
            self.remaining_requirements = [
                req for req in self.remaining_requirements if req.get("id") not in hit_ids
            ]
        self.conversation_history.append({"role": "interviewer", "content": selected_action})
        self.conversation_history.append({"role": "user", "content": user_response})
        self.last_action_info = selected_judgement or {}
        self.oracle_trace.append(
            {
                "turn": len(self.oracle_trace) + 1,
                "topic_id": topic_id,
                "mediator_turn": mediator_turn,
                "interviewer_action": selected_action,
                "interviewer_action_merged": merged_action,
                "selected_interviewer_role": selected_role,
                "judge_per_role": judge_details,
                "user_response": user_response,
                "judge": self.last_action_info,
                "revealed_ids": list(elicited_req_ids or []),
                "remaining_implicit": len(self.remaining_requirements),
                "usage": {
                    "judge": {"checked_actions": len(judge_details) if judge_details else 1},
                    "user": user_usage or {},
                },
            }
        )
        return {
            "agent": self.name,
            "statement": user_response,
            "open_questions": [],
            "oracle_action_type": self.last_action_info.get("action_type", ""),
            "oracle_is_relevant": bool(
                self.last_action_info.get("is_relevant_to_implied_requirements", False)
            ),
            "oracle_revealed_ids": elicited_req_ids,
        }


def load_json(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise TypeError(f"設定檔必須是 JSON object: {path}")
    return data


def next_result_index(prefix: str, results_dir: Path) -> int:
    """取得下一個輸出編號（同 prefix 下取現有最大值 +1）。"""
    pat = re.compile(rf"^(?:result|record|cost)_{re.escape(prefix)}_(\d+)\.json$")
    max_idx = 0
    for p in results_dir.glob(f"*_{prefix}_*.json"):
        m = pat.match(p.name)
        if not m:
            continue
        try:
            max_idx = max(max_idx, int(m.group(1)))
        except ValueError:
            continue
    return max_idx + 1


def is_likely_english(text: str) -> bool:
    s = str(text or "").strip()
    if not s:
        return False
    letters = re.findall(r"[A-Za-z]", s)
    cjk = re.findall(r"[\u4e00-\u9fff]", s)
    if not letters:
        return False
    if not cjk:
        return True
    return len(letters) >= (len(cjk) * 2)


def parse_mediator_turn(topic_id: str) -> int:
    m = re.search(r"ELICIT-R\d+-T(\d+)", str(topic_id or ""))
    if not m:
        return 0
    try:
        return int(m.group(1))
    except Exception:
        return 0


def resolve_role_model_name(flow_cfg: Dict[str, Any], role: str) -> str:
    agent_models = flow_cfg.get("agent_models", {})
    if not isinstance(agent_models, dict):
        return ""
    role_cfg = agent_models.get(role, {})
    if isinstance(role_cfg, dict):
        model = str(role_cfg.get("model") or "").strip()
        if model:
            return model
    default_cfg = agent_models.get("default", {})
    if isinstance(default_cfg, dict):
        model = str(default_cfg.get("model") or "").strip()
        if model:
            return model
    return ""


def _enabled_interviewer_agents(flow_cfg: Dict[str, Any]) -> List[str]:
    base_roles = ["analyst", "expert", "modeler"]
    enabled = flow_cfg.get("enable_agents") or {}
    if not isinstance(enabled, dict):
        return base_roles
    out = [r for r in base_roles if bool(enabled.get(r, True))]
    return out or ["analyst"]


def _format_interviewer_roles_with_models(flow_cfg: Dict[str, Any], roles: List[str]) -> str:
    rows: List[str] = []
    for role in roles:
        role_name = str(role or "").strip()
        if not role_name:
            continue
        model_name = resolve_role_model_name(flow_cfg, role_name)
        if model_name:
            rows.append(f"{role_name}:{model_name}")
        else:
            rows.append(role_name)
    return ", ".join(rows)


def _build_plant_interviewer_models(flow_cfg: Dict[str, Any]) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for role in _enabled_interviewer_agents(flow_cfg):
        out[role] = resolve_role_model_name(flow_cfg, role)
    return out


def resolve_interviewer_model_label(flow_cfg: Dict[str, Any], per_task: Dict[str, Any]) -> str:
    # 回傳實際參與的 interviewer agents + 對應模型。
    participants: List[str] = []

    # 優先以每輪 contributions 推回實際有發言的 interviewer。
    for tlog in (per_task.get("elicitation_log", []) or []):
        if not isinstance(tlog, dict):
            continue
        for row in (tlog.get("contributions", []) or []):
            if not isinstance(row, dict):
                continue
            agent = str(row.get("agent") or "").strip()
            if agent in ("analyst", "expert", "modeler") and agent not in participants:
                participants.append(agent)

    if not participants:
        plan = per_task.get("elicitation_plan", {})
        if isinstance(plan, dict):
            for role in (plan.get("interviewers") or []):
                role_name = str(role or "").strip()
                if role_name in ("analyst", "expert", "modeler") and role_name not in participants:
                    participants.append(role_name)

    if not participants:
        participants = _enabled_interviewer_agents(flow_cfg)

    return _format_interviewer_roles_with_models(flow_cfg, participants)


def assert_models_have_pricing(flow_cfg: Dict[str, Any], exp_cfg: Dict[str, Any]) -> None:
    for agent, info in (flow_cfg.get("agent_models") or {}).items():
        if agent == "default" or not isinstance(info, dict):
            continue
        model_name = str(info.get("model") or "").strip()
        if model_name and (not model_has_token_pricing(model_name)):
            print(
                f"警告：沒有找到 token 的定價：agent_models.{agent} 模型「{model_name}」。"
                "請在 utils.py 的 CostTracker.DEFAULT_PRICING_PER_1M_TOKENS 補上定價。"
            )
            sys.exit(1)
    for k in ("oracle_user", "oracle_judge"):
        model_name = str((exp_cfg.get(k) or {}).get("model") or "").strip()
        if model_name and (not model_has_token_pricing(model_name)):
            print(
                f"警告：沒有找到 token 的定價：{k} 模型「{model_name}」。"
                "請在 utils.py 的 CostTracker.DEFAULT_PRICING_PER_1M_TOKENS 補上定價。"
            )
            sys.exit(1)


def build_flow(flow_cfg: Dict[str, Any], *, verbose: bool) -> Flow:
    return Flow(
        config=flow_cfg,
        store=ExperimentStore(),
        logger=ExperimentLogger(verbose=verbose),
    )


def build_oracle_configs(exp_cfg: Dict[str, Any], api_key: str, base_url: str) -> OracleConfigs:
    user_cfg = exp_cfg.get("oracle_user") or {}
    judge_cfg = exp_cfg.get("oracle_judge") or {}
    oracle_user = {
        "api_key": api_key,
        "base_url": base_url,
        "model_name": str(user_cfg.get("model") or ""),
        "temperature": float(user_cfg.get("temperature", 0.7)),
        "max_tokens": int(user_cfg.get("max_tokens", 1024)),
        "timeout": float(user_cfg.get("timeout", 30.0)),
    }
    oracle_judge = {
        "api_key": api_key,
        "base_url": base_url,
        "model_name": str(judge_cfg.get("model") or ""),
        "temperature": float(judge_cfg.get("temperature", 0.0)),
        "max_tokens": int(judge_cfg.get("max_tokens", 1024)),
        "timeout": float(judge_cfg.get("timeout", 30.0)),
    }
    return OracleConfigs(
        judge_model_config=oracle_judge,
        user_model_config=oracle_user,
    )


def ensure_artifact(task: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "rough_idea": str(task.get("initial_requirements") or ""),
        "stakeholders": [],
        "scope": {"in_scope": [], "out_of_scope": [], "description": ""},
        "requirements": [],
        "conflicts": [],
        "feedback": {},
        "system_models": {},
        "open_questions": [],
        "decisions": [],
        "discussions": [],
        "meta": {},
        "elicitation_candidates": [],
    }


def run_one_task(
    flow: Flow,
    oracle_user: OracleUserAgent,
    task: Dict[str, Any],
    *,
    show_trace: bool,
) -> Dict[str, Any]:
    initial_req = str(task.get("initial_requirements") or "")
    os.environ["PLANT_OUTPUT_LANGUAGE"] = "en" if is_likely_english(initial_req) else "zh-Hant"
    artifact = ensure_artifact(task)
    oracle_user.set_task(task)

    stakeholders = oracle_user.generate_stakeholder_requirements(
        rough_idea=artifact["rough_idea"],
        selected_stakeholders=["Oracle User"],
    )
    artifact["stakeholders"] = stakeholders
    flow.user_agent.stakeholders = stakeholders

    analysis = flow.analyst_agent.run_requirements_analyst(
        "analyze_requirements",
        stakeholders=stakeholders,
    )
    artifact["requirements"] = analysis.get("requirements", [])
    req_before = len(artifact["requirements"])

    def _apply_candidates_into_requirements(local_artifact: Dict[str, Any]) -> None:
        if not local_artifact.get("elicitation_candidates"):
            return
        for cand in local_artifact["elicitation_candidates"]:
            if not isinstance(cand, dict):
                continue
            cand.setdefault("status", "draft")
            if any(
                isinstance(r, dict) and r.get("text") == cand.get("text")
                for r in local_artifact.get("requirements", [])
            ):
                continue
            local_artifact["requirements"].append(cand)

    artifact = flow.meeting.run_hidden_requirement_elicitation_meeting(
        artifact,
        round_num=0,
    )
    _apply_candidates_into_requirements(artifact)

    req_after = len(artifact["requirements"])
    elicitation_log = artifact.get("elicitation_log", []) or []

    return {
        "name": task.get("name", ""),
        "application_type": task.get("application_type", ""),
        "initial_requirements": task.get("initial_requirements", ""),
        "implicit_total": len(task.get("Implicit Requirements", []) or []),
        "requirements_before_elicitation": req_before,
        "elicitation_candidates": len(artifact.get("elicitation_candidates", []) or []),
        "requirements_after_elicitation": req_after,
        "elicitation_turns": len(artifact.get("elicitation_log", []) or []),
        "termination_reason": artifact.get("elicitation_termination_reason", ""),
        "coverage": artifact.get("elicitation_coverage", {}),
        "oracle_remaining_implicit": len(oracle_user.remaining_requirements),
        "oracle_revealed_count": len({
            str(rid)
            for tr in (oracle_user.oracle_trace or [])
            for rid in (tr.get("revealed_ids") or [])
            if rid
        }),
        "elicitation_plan": artifact.get("elicitation_plan", {}),
        "elicitation_log": elicitation_log,
        "oracle_trace": list(oracle_user.oracle_trace),
    }


def build_cost_payload(flow: Flow, oracle_user: OracleUserAgent) -> Dict[str, Any]:
    cost_by_agent: Dict[str, Any] = {}
    enabled = flow.config.get("enable_agents") or {}
    for agent_name, m in flow.agent_models.items():
        if isinstance(enabled, dict) and not bool(enabled.get(agent_name, True)):
            continue
        if agent_name == "user":
            continue
        if hasattr(m, "costTracker"):
            cost_by_agent[agent_name] = m.costTracker.export_summary_dict()
    if not isinstance(enabled, dict) or bool(enabled.get("user", True)):
        cost_by_agent["user"] = oracle_user.export_cost_summary()
    totals = {
        "input_tokens": sum(int(v.get("input_tokens", 0) or 0) for v in cost_by_agent.values()),
        "output_tokens": sum(int(v.get("output_tokens", 0) or 0) for v in cost_by_agent.values()),
        "total_tokens": sum(int(v.get("total_tokens", 0) or 0) for v in cost_by_agent.values()),
        "run_time(s)": round(
            sum(float(v.get("run_time(s)", 0.0) or 0.0) for v in cost_by_agent.values()),
            3,
        ),
        "estimated_cost(USD)": round(
            sum(float(v.get("estimated_cost(USD)", 0.0) or 0.0) for v in cost_by_agent.values()),
            8,
        ),
    }
    return {"agents": cost_by_agent, "totals": totals}


def _extract_action_type_effectiveness(conversation: List[Dict[str, Any]]) -> Dict[str, Any]:
    stats: Dict[str, Dict[str, float]] = {}
    for turn in conversation:
        action_type = str(turn.get("action_type") or "unknown")
        is_hit = bool(turn.get("is_relevant_to_url", False))
        if action_type not in stats:
            stats[action_type] = {"total": 0, "effective": 0}
        stats[action_type]["total"] += 1
        if is_hit:
            stats[action_type]["effective"] += 1
    out: Dict[str, Any] = {}
    for k, v in stats.items():
        total = int(v["total"])
        eff = int(v["effective"])
        out[k] = {
            "total": total,
            "effective": eff,
            "effectiveness_ratio": (eff / total) if total > 0 else 0.0,
        }
    return out


def _compute_aspect_type_elicitation(
    task: Dict[str, Any],
    revealed_ids: set,
) -> Dict[str, Any]:
    # 與 ReqElicitGym 一樣：以 Implicit Requirements 的 Aspect 作為分母，
    # 命中 requirement id 作為分子。
    totals = {"Interaction": 0, "Content": 0, "Style": 0}
    elicited = {"Interaction": 0, "Content": 0, "Style": 0}
    implicit = task.get("Implicit Requirements", []) or []
    for i, req in enumerate(implicit, start=1):
        if not isinstance(req, dict):
            continue
        aspect = str(req.get("Aspect") or "").strip()
        if aspect not in totals:
            continue
        rid = f"IR-{i:02d}"
        totals[aspect] += 1
        if rid in revealed_ids:
            elicited[aspect] += 1
    out: Dict[str, Any] = {}
    for aspect in ("Interaction", "Content", "Style"):
        total = totals[aspect]
        hit = elicited[aspect]
        out[aspect] = {
            "total": total,
            "elicited": hit,
            "elicitation_ratio": (hit / total) if total > 0 else 0.0,
        }
    return out


def _build_task_record(
    *,
    task_idx: int,
    task: Dict[str, Any],
    per_task: Dict[str, Any],
    interviewer_model: str,
    user_answer_quality: str,
    token_cost: int,
) -> Dict[str, Any]:
    implicit_total = int(per_task.get("implicit_total", 0) or 0)
    # 與 run_one_task 的 oracle_revealed_count 同口徑：以 oracle_trace 的 revealed_ids 去重後計算。
    oracle_revealed_ids = {
        str(rid)
        for tr in (per_task.get("oracle_trace", []) or [])
        if isinstance(tr, dict)
        for rid in (tr.get("revealed_ids") or [])
        if rid
    }
    elicited = len(oracle_revealed_ids)
    elicitation_ratio = (elicited / implicit_total) if implicit_total > 0 else 0.0

    conversation: List[Dict[str, Any]] = []
    revealed_seen: set = set()
    hit_sequence: List[int] = []

    trace_by_turn: Dict[int, Dict[str, Any]] = {}
    for trace in per_task.get("oracle_trace", []) or []:
        if not isinstance(trace, dict):
            continue
        turn_no = int(trace.get("mediator_turn", 0) or 0)
        if turn_no <= 0:
            turn_no = int(trace.get("turn", 0) or 0)
        agg = trace_by_turn.setdefault(
            turn_no,
            {
                "user_texts": [],
                "action_types": [],
                "is_hit": False,
                "revealed_ids": set(),
            },
        )
        user_text = str(trace.get("user_response") or "").strip()
        if user_text:
            agg["user_texts"].append(user_text)
        action_type = str((trace.get("judge") or {}).get("action_type") or "").strip()
        if action_type:
            agg["action_types"].append(action_type)
        if bool((trace.get("judge") or {}).get("is_relevant_to_implied_requirements", False)):
            agg["is_hit"] = True
        for rid in (trace.get("revealed_ids") or []):
            if rid:
                agg["revealed_ids"].add(str(rid))

    turn_logs = per_task.get("elicitation_log", []) or []
    accumulated_candidates: List[str] = []
    accumulated_candidates_seen: set = set()
    for tlog in turn_logs:
        if not isinstance(tlog, dict):
            continue
        turn_no = int(tlog.get("turn", 0) or 0)
        contributions = tlog.get("contributions", []) or []

        analyst_parts: List[str] = []
        expert_parts: List[str] = []
        modeler_parts: List[str] = []
        user_parts: List[str] = []
        for row in contributions:
            if not isinstance(row, dict):
                continue
            agent = str(row.get("agent") or "").strip()
            stmt = str(row.get("statement") or "").strip()
            if not agent or not stmt:
                continue
            if agent == "user":
                user_parts.append(stmt)
            elif agent == "analyst":
                analyst_parts.append(stmt)
            elif agent == "expert":
                expert_parts.append(stmt)
            elif agent == "modeler":
                modeler_parts.append(stmt)
            else:
                # 其他角色目前不列為 interviewer 三角色欄位。
                pass

        agg = trace_by_turn.get(
            turn_no,
            {"user_texts": [], "action_types": [], "is_hit": False, "revealed_ids": set()},
        )
        for rid in agg.get("revealed_ids", set()):
            revealed_seen.add(str(rid))
        hit = bool(agg.get("is_hit", False))
        hit_sequence.append(1 if hit else 0)

        action_types = agg.get("action_types", []) or []
        forced_finish = bool(tlog.get("forced_finish", False))
        turn_candidates = [
            str(x).strip()
            for x in (tlog.get("new_candidate_texts", []) or [])
            if str(x).strip()
        ]
        for cand in turn_candidates:
            key = cand.lower()
            if key in accumulated_candidates_seen:
                continue
            accumulated_candidates_seen.add(key)
            accumulated_candidates.append(cand)
        if forced_finish:
            action_type = "finish"
            user_text = ""
        else:
            action_type = action_types[0] if action_types else ""
            user_text = "\n".join(user_parts) if user_parts else "\n".join(agg.get("user_texts", []) or [])

        turn_entry = {
            "turn": turn_no,
            "analyst": "\n\n".join(analyst_parts),
            "expert": "\n\n".join(expert_parts),
            "modeler": "\n\n".join(modeler_parts),
            "user": user_text,
            "action_type": action_type,
            "is_relevant_to_url": hit,
            "elicitation_ratio": (
                len(revealed_seen) / implicit_total if implicit_total > 0 else 0.0
            ),
        }
        if action_type == "finish":
            # 僅在收尾輪附上整場累積（去重）候選需求。
            turn_entry["new_candidate_texts"] = list(accumulated_candidates)

        conversation.append(turn_entry)

    if not conversation:
        for turn_no in sorted(trace_by_turn.keys()):
            agg = trace_by_turn[turn_no]
            for rid in agg.get("revealed_ids", set()):
                revealed_seen.add(str(rid))
            hit = bool(agg.get("is_hit", False))
            hit_sequence.append(1 if hit else 0)
            action_types = agg.get("action_types", []) or []
            conversation.append(
                {
                    "turn": turn_no,
                    "analyst": "",
                    "expert": "",
                    "modeler": "",
                    "user": "\n".join(agg.get("user_texts", []) or []),
                    "action_type": action_types[0] if action_types else "",
                    "is_relevant_to_url": hit,
                    "elicitation_ratio": (
                        len(revealed_seen) / implicit_total if implicit_total > 0 else 0.0
                    ),
                }
            )
    num_rounds = len(conversation)
    tkqr = compute_tkqr(hit_sequence, implicit_total)
    ora = compute_ora(num_rounds, implicit_total)
    # 面向統計改與 total_elicited 採同一來源，避免 turn 對齊差異導致口徑不一致。
    aspect_type_elicitation = _compute_aspect_type_elicitation(task, oracle_revealed_ids)

    app_type = str(
        task.get("application_type")
        or task.get("Application Type")
        or ((task.get("Category") or {}).get("primary_category") if isinstance(task.get("Category"), dict) else "")
        or "Unknown"
    ).strip() or "Unknown"

    return {
        "task_id": f"task_{task_idx}",
        "task_name": task.get("name", ""),
        "application_type": app_type,
        "initial_requirements": task.get("initial_requirements", ""),
        "user_stories": task.get("URL", []) or [],
        "user_answer_quality": user_answer_quality,
        "interviewer_model": interviewer_model,
        "conversation": conversation,
        "total_turns": len(conversation),
        # 對齊 result.task_results 結構
        "total_requirements": implicit_total,
        "total_elicited": elicited,
        "elicitation_ratio": elicitation_ratio,
        "tkqr": tkqr,
        "ora": ora,
        "num_rounds": num_rounds,
        "optimal_rounds": implicit_total + 1,
        "token_cost": int(token_cost),
        "action_type_effectiveness": _extract_action_type_effectiveness(conversation),
        "aspect_type_elicitation": aspect_type_elicitation,
    }


def _build_result_payload(
    *,
    flow_cfg: Dict[str, Any],
    exp_cfg: Dict[str, Any],
    task_results: List[Dict[str, Any]],
) -> Dict[str, Any]:
    summary = compute_overall_metrics(task_results)
    overall = {
        "total_test_samples": int(summary.get("total_tasks", 0) or 0),
        "total_hidden_requirements": int(summary.get("total_requirements_all_tasks", 0) or 0),
        "total_elicited": int(summary.get("total_elicited_all_tasks", 0) or 0),
        "average_elicitation_ratio": float(summary.get("elicitation_ratio", 0.0) or 0.0),
        "average_tkqr": float(summary.get("tkqr", 0.0) or 0.0),
        "average_ora": float(summary.get("ora", 0.0) or 0.0),
        "variance_elicitation_ratio": float(summary.get("variance_elicitation_ratio", 0.0) or 0.0),
        "variance_tkqr": float(summary.get("variance_tkqr", 0.0) or 0.0),
        "variance_ora": float(summary.get("variance_ora", 0.0) or 0.0),
        "average_token_cost": float(summary.get("average_token_cost", 0.0) or 0.0),
        "variance_token_cost": float(summary.get("variance_token_cost", 0.0) or 0.0),
        "elicitation_ratio_from_totals": float(summary.get("elicitation_ratio_from_totals", 0.0) or 0.0),
        "action_type_effectiveness": summary.get("action_type_effectiveness", {}) or {},
        "aspect_type_elicitation": summary.get("aspect_type_elicitation", {}) or {},
        "application_type_statistics": summary.get("application_type_statistics", {}) or {},
    }

    return {
        "config": {
            "Plant": _build_plant_interviewer_models(flow_cfg),
            "judge_model": str((exp_cfg.get("oracle_judge", {}) or {}).get("model", "")),
            "user_model": str((exp_cfg.get("oracle_user", {}) or {}).get("model", "")),
            "user_answer_quality": str(exp_cfg.get("user_answer_quality", "high")),
            "max_steps": int(flow_cfg.get("elicitation_max_turns", 0) or 0),
        },
        "overall_evaluation": overall,
        "task_results": [
            {
                "task_id": t["task_id"],
                "total_requirements": t["total_requirements"],
                "total_elicited": t["total_elicited"],
                "elicitation_ratio": t["elicitation_ratio"],
                "tkqr": t["tkqr"],
                "ora": t["ora"],
                "num_rounds": t["num_rounds"],
                "optimal_rounds": t["optimal_rounds"],
                "token_cost": t["token_cost"],
                "action_type_effectiveness": t["action_type_effectiveness"],
                "aspect_type_elicitation": t["aspect_type_elicitation"],
            }
            for t in task_results
        ],
    }


def _print_final_summary(result: Dict[str, Any], records: List[Dict[str, Any]]) -> None:
    overall = result.get("overall_evaluation", {}) or {}
    app_stats = overall.get("application_type_statistics", {}) or {}
    action_stats = overall.get("action_type_effectiveness", {}) or {}
    aspect_stats = overall.get("aspect_type_elicitation", {}) or {}

    print("\n" + "=" * 60)
    print("所有任務完成！")
    print("=" * 60)
    print(f"總任務數：{len(records)}")
    avg_turns = (
        sum(int(r.get("total_turns", 0) or 0) for r in records) / len(records)
        if records
        else 0.0
    )
    print(f"平均對話輪數：{avg_turns:.1f}")

    print("\n評估指標總結：")
    print(f"  總測試樣本數：{int(overall.get('total_test_samples', 0) or 0)}")
    print(f"  總隱式需求數：{int(overall.get('total_hidden_requirements', 0) or 0)}")
    print(f"  總取得數：{int(overall.get('total_elicited', 0) or 0)}")
    print("\n平均指標（基於測試樣本平均）：")
    print(f"  平均取得比例：{float(overall.get('average_elicitation_ratio', 0.0) or 0.0):.2%}")
    print(f"  平均 TKQR：{float(overall.get('average_tkqr', 0.0) or 0.0):.4f}")
    print(f"  平均 ORA：{float(overall.get('average_ora', 0.0) or 0.0):.4f}")
    print("\n變異數：")
    print(f"  取得比例變異數：{float(overall.get('variance_elicitation_ratio', 0.0) or 0.0):.6f}")
    print(f"  TKQR 變異數：{float(overall.get('variance_tkqr', 0.0) or 0.0):.6f}")
    print(f"  ORA 變異數：{float(overall.get('variance_ora', 0.0) or 0.0):.6f}")
    print("\n總體比例（基於總計數）：")
    print(f"  總取得比例：{float(overall.get('elicitation_ratio_from_totals', 0.0) or 0.0):.2%}")

    if app_stats:
        print("\n依應用類型統計：")
        print(f"{'Application Type':<40} {'任務數':<10} {'平均取得比例':<15} {'平均TKQR':<12} {'平均ORA':<12}")
        print("-" * 100)
        for app in sorted(app_stats.keys()):
            s = app_stats[app] or {}
            print(
                f"{app:<40} {int(s.get('num_tasks', 0) or 0):<10} "
                f"{float(s.get('average_elicitation_ratio', 0.0) or 0.0):>13.2%} "
                f"{float(s.get('average_tkqr', 0.0) or 0.0):>10.4f} "
                f"{float(s.get('average_ora', 0.0) or 0.0):>10.4f}"
            )

    if action_stats:
        print("\n動作類型有效性：")
        for action_type, s in action_stats.items():
            print(
                f"  {action_type}: {int(s.get('effective', 0) or 0)}/"
                f"{int(s.get('total', 0) or 0)} = "
                f"{float(s.get('effectiveness_ratio', 0.0) or 0.0):.2%}"
            )

    if aspect_stats:
        print("\n面向類型取得比例：")
        for aspect in ("Interaction", "Content", "Style"):
            s = aspect_stats.get(aspect, {}) or {}
            total = int(s.get("total", 0) or 0)
            if total <= 0:
                continue
            print(
                f"  {aspect}: {int(s.get('elicited', 0) or 0)}/{total} = "
                f"{float(s.get('elicitation_ratio', 0.0) or 0.0):.2%}"
            )


def main() -> None:
    cfg_path = DEFAULT_CONFIG_PATH.resolve()
    exp_cfg = load_json(cfg_path)

    flow_cfg_path = FLOW_CONFIG_PATH
    flow_cfg = load_json(flow_cfg_path)
    if isinstance(exp_cfg.get("enable_agents"), dict):
        flow_cfg["enable_agents"] = exp_cfg["enable_agents"]
    if isinstance(exp_cfg.get("agent_models"), dict):
        flow_cfg["agent_models"] = exp_cfg["agent_models"]
    flow_cfg["enable_elicitation"] = True
    flow_cfg["elicitation_stop_mode"] = "baseline"

    # 只做「需求分析 + 挖掘會議」，不進正式 round。
    flow_cfg["rounds"] = 0

    if exp_cfg.get("elicitation_max_turns") is not None:
        flow_cfg["elicitation_max_turns"] = int(exp_cfg["elicitation_max_turns"])

    data_path = DEFAULT_DATA_PATH
    print(f"正在載入資料檔案：{data_path}")
    with data_path.open("r", encoding="utf-8") as f:
        tasks = json.load(f)
    if not isinstance(tasks, list):
        raise TypeError(f"資料檔格式錯誤，必須是 list: {data_path}")
    total_tasks_in_file = len(tasks)

    max_tasks = None
    if max_tasks is None:
        if PROMPT_FOR_MAX_TASKS:
            raw = input("請輸入要執行的任務數量（Enter: 全做）：").strip()
            if raw:
                try:
                    max_tasks = int(raw)
                except ValueError:
                    max_tasks = None
    # None 或 <=0：跑全部；僅在正整數時切片。
    if max_tasks is not None and max_tasks > 0:
        tasks = tasks[:max_tasks]

    runs = None
    if runs is None and PROMPT_FOR_RUNS:
        raw_runs = input("請輸入要重複執行幾次：").strip()
        if not raw_runs:
            print("錯誤：請輸入重複執行次數")
            sys.exit(1)
        try:
            runs = int(raw_runs)
        except ValueError:
            print("錯誤：重複執行次數必須是整數")
            sys.exit(1)
    if runs is None:
        if PROMPT_FOR_RUNS:
            print("錯誤：請在互動模式下輸入重複執行次數（正整數）")
            sys.exit(1)
        runs = 1
    if runs <= 0:
        print("錯誤：runs 必須為正整數")
        sys.exit(1)
    if len(tasks) == total_tasks_in_file:
        print(f"資料檔案包含 {total_tasks_in_file} 個任務，將對全部任務進行評估")
    else:
        print(f"資料檔案包含 {total_tasks_in_file} 個任務，將對前 {len(tasks)} 個任務進行評估")

    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        print("錯誤：請先在 .env 或環境變數設定 OPENAI_API_KEY")
        sys.exit(1)
    base_url = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")

    assert_models_have_pricing(flow_cfg, exp_cfg)

    verbose = bool(exp_cfg.get("verbose", True))
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    run_results: List[Dict[str, Any]] = []
    run_metrics: List[Dict[str, Any]] = []
    run_costs_usd: List[float] = []
    run_total_tokens: List[int] = []
    run_total_runtime_s: List[float] = []
    round_ids_used: List[str] = []

    for run_i in range(runs):
        run_id = str(next_result_index(OUTPUT_PREFIX, RESULTS_DIR))
        round_ids_used.append(run_id)

        print(f"\n=== Run {run_i + 1}/{runs}（run_id={run_id}）===")
        print("\n正在建立環境...")
        flow = build_flow(flow_cfg, verbose=verbose)
        oracle_cfg = build_oracle_configs(exp_cfg, api_key, base_url)
        oracle_user = OracleUserAgent(
            model=flow.agent_models["user"],
            oracle_configs=oracle_cfg,
            registry=flow.registry,
            project_config=flow.config,
        )
        flow.user_agent = oracle_user
        flow.registry.register("user", oracle_user)
        print("\n" + "=" * 60)
        print("開始執行全量評估實驗...")
        print("=" * 60)

        records: List[Dict[str, Any]] = []
        task_result_rows: List[Dict[str, Any]] = []
        t0 = time.perf_counter()
        for i, task in enumerate(tasks, start=1):
            print()
            print(f"任務 {i}/{len(tasks)}：task_{i-1}")
            print(f"系統名稱：{task.get('name', 'N/A')}")
            print(f"應用類型：{task.get('application_type', 'N/A')}")
            print(f"初始需求：{str(task.get('initial_requirements', 'N/A'))[:100]}...")
            print(f"總需求數：{len(task.get('Implicit Requirements', []) or [])}")
            print("\n開始對話...\n")
            token_before = 0
            for m in flow.agent_models.values():
                if hasattr(m, "costTracker"):
                    token_before += int(m.costTracker.export_summary_dict().get("total_tokens", 0) or 0)
            one = run_one_task(flow, oracle_user, task, show_trace=verbose)
            token_after = 0
            for m in flow.agent_models.values():
                if hasattr(m, "costTracker"):
                    token_after += int(m.costTracker.export_summary_dict().get("total_tokens", 0) or 0)
            task_token_cost = max(0, token_after - token_before)
            records.append(one)
            task_record = _build_task_record(
                task_idx=i - 1,
                task=task,
                per_task=one,
                interviewer_model=resolve_interviewer_model_label(flow_cfg, one),
                user_answer_quality=str(exp_cfg.get("user_answer_quality", "high")),
                token_cost=task_token_cost,
            )
            task_result_rows.append(task_record)
            print(
                f"\n任務 {i} 完成：總輪數={int(task_record.get('total_turns', 0) or 0)}，"
                f"已取得需求數={int(task_record.get('total_elicited', 0) or 0)}"
            )

        _ = round(time.perf_counter() - t0, 3)
        print(f"\n已執行所有 {len(tasks)} 個任務，停止。")
        result = _build_result_payload(
            flow_cfg=flow_cfg,
            exp_cfg=exp_cfg,
            task_results=task_result_rows,
        )

        prefix = OUTPUT_PREFIX
        result_path = RESULTS_DIR / f"result_{prefix}_{run_id}.json"
        record_path = RESULTS_DIR / f"record_{prefix}_{run_id}.json"
        cost_path = RESULTS_DIR / f"cost_{prefix}_{run_id}.json"

        with result_path.open("w", encoding="utf-8") as f:
            json_dump_no_scientific(result, f, indent=2, ensure_ascii=False)
        with record_path.open("w", encoding="utf-8") as f:
            # record 對齊 conversation 結構
            json_dump_no_scientific(
                [
                    {
                        "task_id": t["task_id"],
                        "task_name": t["task_name"],
                        "initial_requirements": t["initial_requirements"],
                        "user_stories": t["user_stories"],
                        "user_answer_quality": t["user_answer_quality"],
                        "interviewer_model": t["interviewer_model"],
                        "conversation": t["conversation"],
                    }
                    for t in task_result_rows
                ],
                f,
                indent=2,
                ensure_ascii=False,
            )
        cost_payload = build_cost_payload(flow, oracle_user)
        with cost_path.open("w", encoding="utf-8") as f:
            json_dump_no_scientific(cost_payload, f, indent=2, ensure_ascii=False)

        _print_final_summary(result, task_result_rows)

        run_results.append(result)
        run_metrics.append(result.get("overall_evaluation", {}) or {})
        totals = cost_payload.get("totals", {}) if isinstance(cost_payload, dict) else {}
        run_costs_usd.append(float(totals.get("estimated_cost(USD)", 0.0) or 0.0))
        run_total_tokens.append(int(totals.get("total_tokens", 0) or 0))
        run_total_runtime_s.append(float(totals.get("run_time(s)", 0.0) or 0.0))

    if runs > 1:
        metric_keys = [
            ("average_elicitation_ratio", "IRE", "平均取得比例", "percent"),
            ("average_tkqr", "TKQR", "平均 TKQR", "float4"),
            ("average_ora", "ORA", "平均 ORA", "float4"),
        ]
        print("\n多次執行結果統計（平均值 ± 標準差）：")
        summary_metrics: Dict[str, Any] = {}
        for src_key, out_key, label, fmt in metric_keys:
            vals = []
            for m in run_metrics:
                v = m.get(src_key, None)
                if isinstance(v, (int, float)):
                    vals.append(float(v))
            if not vals:
                continue
            mu = float(np.mean(vals))
            sd = float(np.std(vals))
            summary_metrics[out_key] = {
                "mean": mu,
                "std": sd,
                "per_round_values": vals,
            }
            if fmt == "percent":
                print(f"  {label}：{mu:.2%} ± {sd:.2%}")
            else:
                print(f"  {label}：{mu:.4f} ± {sd:.4f}")

        summary_cost: Optional[Dict[str, Any]] = None
        if run_costs_usd:
            cost_mu = float(np.mean(run_costs_usd))
            cost_sd = float(np.std(run_costs_usd))
            token_mu = float(np.mean(run_total_tokens))
            token_sd = float(np.std(run_total_tokens))
            rt_mu = float(np.mean(run_total_runtime_s))
            rt_sd = float(np.std(run_total_runtime_s))
            print(f"  平均 token：{token_mu:.1f} ± {token_sd:.1f}")
            print(f"  平均成本(USD)：{cost_mu:.8f} ± {cost_sd:.8f}")
            print(f"  平均執行時間(s)：{rt_mu:.3f} ± {rt_sd:.3f}")
            summary_cost = {
                "average_token": {
                    "mean": token_mu,
                    "std": token_sd,
                    "per_round_values": [int(x) for x in run_total_tokens],
                },
                "average_cost(USD)": {
                    "mean": cost_mu,
                    "std": cost_sd,
                    "per_round_values": [float(x) for x in run_costs_usd],
                },
                "average_run_time(s)": {
                    "mean": rt_mu,
                    "std": rt_sd,
                    "per_round_values": [float(x) for x in run_total_runtime_s],
                },
            }
        else:
            print("  平均成本(USD)：N/A（本次執行未成功產生成本檔）")

        # 固定欄位順序：runs -> metrics -> cost
        summary_payload = {"runs": runs}
        if summary_metrics:
            summary_payload["metrics"] = summary_metrics
        if summary_cost is not None:
            summary_payload["cost"] = summary_cost

        summary_path = RESULTS_DIR / f"summary_{OUTPUT_PREFIX}.json"
        with summary_path.open("w", encoding="utf-8") as f:
            json_dump_no_scientific(summary_payload, f, indent=2, ensure_ascii=False)
        print(f"已儲存至：{summary_path}")


if __name__ == "__main__":
    main()

