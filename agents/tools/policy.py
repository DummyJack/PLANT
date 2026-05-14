# Tool and skill policy: agent/skill/tool assignment boundaries.
from dataclasses import dataclass, field
from typing import Dict, List, Set


DEFAULT_AGENT_SKILL_MAPPING: Dict[str, List[str]] = {
    "analyst": ["requirements-analyst", "conflict-analyzer"],
    "expert": ["domain-research"],
    "modeler": ["UML"],
    "documentor": ["SRS"],
    "mediator": [],
    "user": [],
}

DEFAULT_AGENT_TOOL_MAPPING: Dict[str, List[str]] = {
    "analyst": ["artifact_query"],
    "expert": ["web_search", "file_parser", "artifact_query"],
    "modeler": ["plantuml_validate", "artifact_query"],
    "documentor": [],
    "mediator": ["artifact_query"],
    "user": ["artifact_query"],
}

DEFAULT_SKILL_TOOL_ALLOWLIST: Dict[str, List[str]] = {
    "domain-research": ["web_search", "file_parser", "artifact_query"],
    "requirements-analyst": ["artifact_query"],
    "conflict-analyzer": ["artifact_query"],
    "UML": ["plantuml_validate", "artifact_query"],
    "SRS": ["artifact_query"],
}


@dataclass
class AgentSkillToolPolicy:
    """集中式 policy：鎖定 agent/skill/tool 邊界並做執行期檢查。"""

    agent_skill_mapping: Dict[str, List[str]] = field(
        default_factory=lambda: dict(DEFAULT_AGENT_SKILL_MAPPING)
    )
    agent_tool_mapping: Dict[str, List[str]] = field(
        default_factory=lambda: dict(DEFAULT_AGENT_TOOL_MAPPING)
    )
    skill_tool_allowlist: Dict[str, List[str]] = field(
        default_factory=lambda: dict(DEFAULT_SKILL_TOOL_ALLOWLIST)
    )

    def allowed_skills_for_agent(self, agent_name: str) -> List[str]:
        return list(self.agent_skill_mapping.get(agent_name, []))

    def allowed_tools_for_agent(self, agent_name: str) -> List[str]:
        return list(self.agent_tool_mapping.get(agent_name, []))

    def can_agent_use_skill(self, agent_name: str, skill_name: str) -> bool:
        return skill_name in set(self.agent_skill_mapping.get(agent_name, []))

    def can_agent_use_tool(self, agent_name: str, tool_name: str) -> bool:
        return tool_name in set(self.agent_tool_mapping.get(agent_name, []))

    def can_skill_use_tool(self, skill_name: str, tool_name: str) -> bool:
        if skill_name not in self.skill_tool_allowlist:
            return False
        return tool_name in set(self.skill_tool_allowlist.get(skill_name, []))

    def validate_agent_assignment(
        self,
        agent_name: str,
        skills: List[str],
        tools: List[str],
    ) -> None:
        allowed_skills: Set[str] = set(self.allowed_skills_for_agent(agent_name))
        allowed_tools: Set[str] = set(self.allowed_tools_for_agent(agent_name))

        invalid_skills = [s for s in skills if s not in allowed_skills]
        invalid_tools = [t for t in tools if t not in allowed_tools]
        if invalid_skills or invalid_tools:
            raise ValueError(
                f"Policy violation for agent '{agent_name}': "
                f"invalid_skills={invalid_skills}, invalid_tools={invalid_tools}, "
                f"allowed_skills={sorted(allowed_skills)}, allowed_tools={sorted(allowed_tools)}"
            )

    def validate_mapping_integrity(self) -> None:
        mapped_skills: Set[str] = set()
        for skill_list in self.agent_skill_mapping.values():
            mapped_skills.update(skill_list)
        missing_allowlist = sorted(
            s for s in mapped_skills if s not in self.skill_tool_allowlist
        )
        if missing_allowlist:
            raise ValueError(
                "Policy integrity violation: missing skill_tool_allowlist entries for "
                f"{missing_allowlist}"
            )
