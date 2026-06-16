# Handles setup logic for project flow orchestration and stage execution.
from typing import Dict, Any, Optional
from agents.base import AgentRegistry
from agents.tools.policy import AgentSkillToolPolicy
from agents.profile import (
    UserAgent,
    AnalystAgent,
    ExpertAgent,
    MediatorAgent,
    ModelerAgent,
    DocumentorAgent,
)
from flow.meeting import MeetingCoordinator
from model import create_model
from .main import (
    run_project,
    run_continue_project,
    run_meeting_round as flow_run_meeting_round,
)
from .init_flow import (
    run_init_phase as flow_run_init_phase,
)
from .finalize_flow import (
    finalize as flow_finalize,
    generate_dr as flow_generate_dr,
    generate_srs as flow_generate_srs,
)
from storage import Store
from utils import Logger, human_setting
from agents.tools import ToolRegistry


MEETING_TYPE_ALIASES = {
    "new_requirement": [
        "clarify_requirement",
        "define_boundary",
        "align_model",
    ],
    "open_question": [
        "clarify_requirement",
    ],
    "conflict_discussion": [
        "tradeoff",
    ],
    "tradeoff": ["tradeoff"],
    "clarify_requirement": ["clarify_requirement"],
    "formalize_requirement": ["formalize_requirement"],
    "define_boundary": ["define_boundary"],
    "align_model": ["align_model"],
}


# ========
# Defines Flow class for this module workflow.
# ========
class Flow:
    # ========
    # Defines __init__ function for this module workflow.
    # ========
    def __init__(self, config: Dict[str, Any], store: Store, logger: Logger):
        self.config = config
        self.store = store
        self.logger = logger

        self.agent_models = {
            "user": self.build_agent_model("user"),
            "analyst": self.build_agent_model("analyst"),
            "expert": self.build_agent_model("expert"),
            "mediator": self.build_agent_model("mediator"),
            "modeler": self.build_agent_model("modeler"),
            "documentor": self.build_agent_model("documentor"),
        }

        self.registry = AgentRegistry()
        enable_agents = config.get("enable_agents") or {}
        self.policy = AgentSkillToolPolicy()
        artifact_path = None
        if getattr(self.store, "project_id", None) and hasattr(self.store, "artifact_dir"):
            artifact_path = str(self.store.artifact_dir)
        self.tool_registry = ToolRegistry(
            config=self.config,
            policy=self.policy,
            artifact_path=artifact_path,
        )

        analyst_tools = self.tool_registry.build_tools_for_agent("analyst")
        expert_tools = self.tool_registry.build_tools_for_agent("expert")
        mediator_tools = self.tool_registry.build_tools_for_agent("mediator")
        modeler_tools = self.tool_registry.build_tools_for_agent("modeler")
        documentor_tools = self.tool_registry.build_tools_for_agent("documentor")
        user_tools = self.tool_registry.build_tools_for_agent("user")

        self.user_agent = UserAgent(
            self.agent_models["user"],
            tools=user_tools,
            registry=self.registry,
            project_config=self.config,
        )
        self.analyst_agent = AnalystAgent(
            self.agent_models["analyst"],
            tools=analyst_tools,
            registry=self.registry,
            project_config=self.config,
        )
        self.expert_agent = ExpertAgent(
            self.agent_models["expert"],
            tools=expert_tools,
            registry=self.registry,
            doc_dir="doc",
            project_config=self.config,
        )
        self.mediator_agent = MediatorAgent(
            self.agent_models["mediator"],
            tools=mediator_tools,
            registry=self.registry,
            project_config=self.config,
        )
        self.modeler_agent = ModelerAgent(
            self.agent_models["modeler"],
            tools=modeler_tools,
            registry=self.registry,
            project_config=self.config,
        )
        self.documentor_agent = DocumentorAgent(
            self.agent_models["documentor"],
            self.store,
            tools=documentor_tools,
            registry=self.registry,
            project_config=self.config,
        )

        self.validate_policy_assignments()

        for name, agent in [
            ("user", self.user_agent),
            ("analyst", self.analyst_agent),
            ("expert", self.expert_agent),
            ("mediator", self.mediator_agent),
            ("modeler", self.modeler_agent),
            ("documentor", self.documentor_agent),
        ]:
            agent.logger = self.logger
            agent.policy = self.policy
            agent.runtime_store = self.store
            agent.runtime_run_id = getattr(self, "run_id", "")
            if enable_agents.get(name, True):
                self.registry.register(name, agent)

        self.mediator_agent.enable_human_judgment = bool(
            human_setting(config, "enable_human_judgment", True)
        )

        eat = config.get("enable_meeting")
        if isinstance(eat, dict):
            enabled_types = []
            for key, enabled in eat.items():
                if not enabled or key in {"elicitation", "conflict_review"}:
                    continue
                for issue_type_id in MEETING_TYPE_ALIASES.get(key, [key]):
                    if issue_type_id not in enabled_types:
                        enabled_types.append(issue_type_id)
            self.mediator_agent.enabled_issue_type_ids = enabled_types or None
        self.meeting = MeetingCoordinator(self)

    # ========
    # Defines validate policy assignments function for this module workflow.
    # ========
    def validate_policy_assignments(self) -> None:
        self.policy.validate_mapping_integrity()
        assignments = [
            ("user", self.user_agent),
            ("analyst", self.analyst_agent),
            ("expert", self.expert_agent),
            ("mediator", self.mediator_agent),
            ("modeler", self.modeler_agent),
            ("documentor", self.documentor_agent),
        ]
        for agent_name, agent in assignments:
            try:
                self.policy.validate_agent_assignment(
                    agent_name,
                    agent.skill_names,
                    list(agent.tools.keys()),
                )
            except ValueError as e:
                raise ValueError(
                    f"Agent policy validation failed for '{agent_name}': {e}"
                ) from e

    # ========
    # Defines ensure artifact contract function for this module workflow.
    # ========
    def ensure_artifact_contract(self, artifact: Dict[str, Any]) -> Dict[str, Any]:
        artifact.setdefault("URL", [])
        elicitation = artifact.setdefault("elicitation", {})
        elicitation.setdefault("plan", {})
        elicitation.setdefault("meeting", {})
        elicitation.setdefault("elicited_reqts", [])
        elicitation.setdefault("elicitation_stop_reason", "")
        artifact.setdefault("elicitation_trace", [])
        return artifact

    # ========
    # Defines touch artifact meta function for this module workflow.
    # ========
    @staticmethod
    def touch_artifact_meta(
        artifact: Dict[str, Any],
        *,
        round_num: Optional[int] = None,
    ) -> None:
        meta = artifact.setdefault("meta", {})
        if round_num is not None:
            meta["last_round"] = round_num

    # ========
    # Defines build agent model function for this module workflow.
    # ========
    def build_agent_model(self, agent_name: str):
        am = self.config.get("agent_models") or {}
        default_cfg = am.get("default") or {}
        per_agent = am.get(agent_name) or default_cfg

        def first_str(*candidates: Any) -> str:
            for v in candidates:
                if v is None:
                    continue
                s = str(v).strip()
                if s:
                    return s
            return ""

        provider = first_str(per_agent.get("provider"), default_cfg.get("provider"))
        model_name = first_str(per_agent.get("model"), default_cfg.get("model"))
        if not provider or not model_name:
            raise ValueError(
                "agent_models 必須在 default 或各 agent 區塊設定 provider 與 model；"
                f"目前無法建立 {agent_name!r} 的模型（缺 provider 或 model）。"
            )

        def pick_temperature(a: Dict[str, Any], b: Dict[str, Any]) -> Any:
            if "temperature" in a and a["temperature"] is not None:
                return a["temperature"]
            if "temperature" in b and b["temperature"] is not None:
                return b["temperature"]
            return None

        temperature = pick_temperature(per_agent, default_cfg)
        max_output_tokens = per_agent.get("max_output_tokens")
        if max_output_tokens is None:
            max_output_tokens = default_cfg.get("max_output_tokens")
        if max_output_tokens is None:
            max_output_tokens = per_agent.get("max_tokens")
        if max_output_tokens is None:
            max_output_tokens = default_cfg.get("max_tokens")

        kwargs = {"temperature": temperature}
        if max_output_tokens is not None:
            kwargs["max_output_tokens"] = max_output_tokens
        passthrough_keys = (
            "base_url",
            "api_key",
            "json_response_format",
        )
        for key in passthrough_keys:
            if per_agent.get(key) is not None:
                kwargs[key] = per_agent[key]
            elif default_cfg.get(key) is not None:
                kwargs[key] = default_cfg[key]
        return create_model(provider=provider, model_name=model_name, **kwargs)

    # ========
    # Defines run function for this module workflow.
    # ========
    def run(self, rough_idea: str) -> Dict[str, Any]:
        return run_project(self, rough_idea)

    # ========
    # Defines run continue function for this module workflow.
    # ========
    def run_continue(self, existing_artifact: Dict[str, Any]) -> Dict[str, Any]:
        return run_continue_project(self, existing_artifact)


    # ========
    # Defines run init phase function for this module workflow.
    # ========
    def run_init_phase(self, artifact: Dict[str, Any]) -> Dict[str, Any]:
        return flow_run_init_phase(self, artifact)


    # ========
    # Defines run meeting round function for this module workflow.
    # ========
    def run_meeting_round(
        self, artifact: Dict[str, Any], round_num: int
    ) -> Dict[str, Any]:
        return flow_run_meeting_round(self, artifact, round_num)


    # ========
    # Defines finalize function for this module workflow.
    # ========
    def finalize(
        self,
        artifact: Dict[str, Any],
    ) -> None:
        return flow_finalize(self, artifact)

    # ========
    # Defines generate DR function for this module workflow.
    # ========
    def generate_dr(
        self,
        artifact: Dict[str, Any],
    ) -> None:
        return flow_generate_dr(self, artifact)

    # ========
    # Defines generate SRS function for this module workflow.
    # ========
    def generate_srs(
        self,
        artifact: Dict[str, Any],
    ) -> None:
        return flow_generate_srs(self, artifact)

    # ========
    # Defines build cost summary function for this module workflow.
    # ========
    def build_cost_summary(self) -> Optional[Dict[str, Any]]:
        cost_by_agent = {}
        for agent_name, model in self.agent_models.items():
            summary = None
            if hasattr(model, "get_cost_summary"):
                summary = model.get_cost_summary()
            if not summary and hasattr(model, "costTracker"):
                summary = model.costTracker.export_summary_dict()
            if summary:
                cost_by_agent[agent_name] = summary

        total_input = sum(v.get("input_tokens", 0) for v in cost_by_agent.values())
        total_output = sum(v.get("output_tokens", 0) for v in cost_by_agent.values())
        total_tokens = sum(v.get("total_tokens", 0) for v in cost_by_agent.values())
        total_elapsed = sum(v.get("run_time(s)", 0.0) for v in cost_by_agent.values())
        total_cost = sum(v.get("estimated_cost(USD)", 0.0) for v in cost_by_agent.values())
        return {
            "project_id": self.store.project_id,
            "agents": cost_by_agent,
            "totals": {
                "input_tokens": total_input,
                "output_tokens": total_output,
                "total_tokens": total_tokens,
                "run_time(s)": round(total_elapsed, 3),
                "estimated_cost(USD)": round(total_cost, 8),
            },
        }
