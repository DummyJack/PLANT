from datetime import datetime, timezone
from typing import Dict, Any, List, Optional
from agents.base import AgentRegistry, AgentSkillToolPolicy
from agents.profile import (
    UserAgent,
    AnalystAgent,
    ExpertAgent,
    MediatorAgent,
    ModelerAgent,
    DocumentorAgent,
)
from agents.agenda import MeetingCoordinator
from model import create_model
from orchestration import (
    run_project,
    run_continue_project,
    run_init_phase as orchestration_run_init_phase,
    run_meeting_round as orchestration_run_meeting_round,
    finalize as orchestration_finalize,
)
from store import Store
from utils import Logger
from agents.tools import ToolRegistry


class Flow:
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
            artifact_path = str(self.store.artifact_dir / "artifact.json")
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

        self.user_agent = UserAgent(
            self.agent_models["user"],
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

        # policy 強制：由單一授權來源檢查所有 agent 的 skill/tool 指派。
        self._validate_policy_assignments()

        tool_max = config.get("tool_call_max_rounds", 3)
        for name, agent in [
            ("user", self.user_agent),
            ("analyst", self.analyst_agent),
            ("expert", self.expert_agent),
            ("mediator", self.mediator_agent),
            ("modeler", self.modeler_agent),
            ("documentor", self.documentor_agent),
        ]:
            agent.tool_call_max_rounds = tool_max
            agent.policy = self.policy
            if enable_agents.get(name, True):
                self.registry.register(name, agent)

        self.mediator_agent.enable_human_escalation = config.get(
            "enable_human_escalation", True
        )

        eat = config.get("enable_agenda_types")
        if isinstance(eat, dict):
            self.mediator_agent.enabled_agenda_type_ids = [
                k for k, v in eat.items() if v
            ]
        self.meeting_coordinator = MeetingCoordinator(self)

    def _validate_policy_assignments(self) -> None:
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

    def _ensure_artifact_contract(self, artifact: Dict[str, Any]) -> Dict[str, Any]:
        """集中初始化 artifact 目前需要的最小欄位。"""
        return artifact

    @staticmethod
    def _touch_artifact_meta(
        artifact: Dict[str, Any],
        *,
        updated_by: str,
        round_num: Optional[int] = None,
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        meta = artifact.setdefault("meta", {})
        meta.setdefault("schema_version", 1)
        meta.setdefault("created_at", now)
        meta["updated_at"] = now
        meta["updated_by"] = updated_by
        if round_num is not None:
            meta["last_round"] = round_num

    def _run_enabled_reviews(
        self,
        artifact: Dict[str, Any],
        *,
        recent_discussions: Optional[List[Dict[str, Any]]],
        roles: List[str],
    ) -> None:
        self.meeting_coordinator._run_enabled_reviews(
            artifact,
            recent_discussions=recent_discussions,
            roles=roles,
        )

    def _recent_topic_discussions(
        self,
        artifact: Dict[str, Any],
        *,
        rounds: int = 1,
    ) -> List[Dict[str, Any]]:
        return self.meeting_coordinator._recent_topic_discussions(
            artifact, rounds=rounds
        )

    def _normalize_topic_proposal(
        self,
        item: Dict[str, Any],
        *,
        proposed_by: str,
        round_num: int,
        index: int,
    ) -> Optional[Dict[str, Any]]:
        return self.meeting_coordinator._normalize_topic_proposal(
            item,
            proposed_by=proposed_by,
            round_num=round_num,
            index=index,
        )

    def _collect_topic_proposals(
        self,
        artifact: Dict[str, Any],
        *,
        round_num: int,
    ) -> List[Dict[str, Any]]:
        return self.meeting_coordinator._collect_topic_proposals(
            artifact,
            round_num=round_num,
        )

    def build_agent_model(self, agent_name: str):
        am = self.config.get("agent_models") or {}
        default_cfg = am.get("default") or {}
        per_agent = am.get(agent_name) or default_cfg
        provider = per_agent.get("provider", self.config.get("provider"))
        model_name = per_agent.get("model", self.config.get("model"))
        temperature = per_agent.get("temperature", self.config.get("temperature"))
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
        return create_model(provider=provider, model_name=model_name, **kwargs)

    def run(self, rough_idea: str) -> Dict[str, Any]:
        return run_project(self, rough_idea)

    def run_continue(self, existing_artifact: Dict[str, Any]) -> Dict[str, Any]:
        return run_continue_project(self, existing_artifact)

    # Phase 0: 初始草稿建立

    def run_init_phase(self, artifact: Dict[str, Any]) -> Dict[str, Any]:
        return orchestration_run_init_phase(self, artifact)

    # Round k: 開會

    def run_meeting_round(
        self, artifact: Dict[str, Any], round_num: int
    ) -> Dict[str, Any]:
        return orchestration_run_meeting_round(self, artifact, round_num)

    def _run_agenda_loop(self, runner: Any) -> None:
        self.meeting_coordinator._run_agenda_loop(runner)

    def _apply_mediator_updates(
        self,
        artifact: Dict[str, Any],
        updates: Dict[str, Any],
    ) -> Dict[str, Any]:
        return self.meeting_coordinator._apply_mediator_updates(artifact, updates)

    # Finalization

    def finalize(self, artifact: Dict[str, Any]):
        orchestration_finalize(self, artifact)

    def _build_cost_summary(self) -> Optional[Dict[str, Any]]:
        cost_by_agent = {}
        for agent_name, model in self.agent_models.items():
            if not hasattr(model, "getCostSummary"):
                continue
            summary = model.getCostSummary()
            if summary:
                cost_by_agent[agent_name] = summary
        if not cost_by_agent:
            return None

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

    def _build_agent_usage_summary(self) -> Dict[str, Any]:
        agents_context: Dict[str, Any] = {}
        total_in = total_out = total_all = 0
        api_calls = 0
        for agent_name, model in self.agent_models.items():
            records = (
                model.getUsageCallRecords()
                if hasattr(model, "getUsageCallRecords")
                else []
            )
            agents_context[agent_name] = {
                "model": getattr(model, "model_name", ""),
                "calls": records,
            }
            for r in records:
                total_in += int(r.get("input_tokens", 0) or 0)
                total_out += int(r.get("output_tokens", 0) or 0)
                total_all += int(r.get("total_tokens", 0) or 0)
                api_calls += 1

        return {
            "project_id": self.store.project_id,
            "agents": agents_context,
            "totals": {
                "input_tokens": total_in,
                "output_tokens": total_out,
                "total_tokens": total_all,
                "api_calls": api_calls,
            },
        }
