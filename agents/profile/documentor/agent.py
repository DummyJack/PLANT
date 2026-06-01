# Documentor agent: generates SRS from the latest draft.
from typing import Optional

from agents.base import BaseAgent

from .srs import DocumentorSrs
from .prompts import DOCUMENTOR_SYSTEM_PROMPT


class DocumentorAgent(
    DocumentorSrs,
    BaseAgent,
):
    name = "documentor"

    system_prompt = DOCUMENTOR_SYSTEM_PROMPT

    def __init__(
        self,
        model,
        store,
        tools: Optional[list] = None,
        registry=None,
        project_config=None,
    ):
        super().__init__(
            model,
            tools=tools,
            registry=registry,
            skill_names=[],
            project_config=project_config,
        )
        self.store = store

    def create_srs(self) -> str:
        return self.create_srs_from_latest_draft()
