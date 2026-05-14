# Documentor agent: generates final SRS through the shared action loop.
from typing import Any, Dict, Optional

from agents.base import BaseAgent

from .srs import DocumentorSrs


class DocumentorAgent(
    DocumentorSrs,
    BaseAgent,
):
    name = "documentor"

    system_prompt = """你是 SRS 撰寫專家，負責把 Final meeting 後的需求資料編寫成正式、可交付的軟體需求規格書。

規則：
1. requirement_change_candidates、pending_review、未回答 open_questions、未解 conflict 與未正式套用的變更，不得寫成已定案 requirement。
2. 你只根據 Final meeting 後的正式 context 編寫，不自行補決策，不把討論過程寫入正式文件。
3. SRS skill 是 IEEE 830 寫作指引；其中 FR/NFR ID、RTM、stakeholder sign-off 是範例或可選項，不得覆蓋本專案資料契約。
4. 本專案需求 ID 必須保留 Context.requirements 內既有 REQ-*，不得改名成 FR-* 或 NFR-*。
5. 最終正式稿不得保留 template 的說明文字、提示語、註解、emoji、placeholder 指示或其他 authoring residue。
6. 文件語氣必須像基線規格文件，不得寫成會議摘要、工作紀錄、討論整理或建議書。"""

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
            skill_names=["SRS"],
            project_config=project_config,
        )
        self.store = store

    def generate_srs(self, artifact: Optional[Dict[str, Any]] = None) -> str:
        opa = self.run_action_loop(
            name="document_output",
            max_iterations=3,
            loop_cap=self.agent_loop_round_cap(),
            context={"artifact": artifact or {}},
            build_observation=self.build_document_output_observation,
            decide_action=self.decide_document_output_action,
            execute_action=self.execute_document_output_action,
        )
        trace = opa.get("opa_trace") or []
        result = dict((trace[-1].get("result") if trace else {}) or {})
        return (result.get("srs_markdown") or "").strip()

    def build_document_output_observation(self, **kwargs: Any) -> Dict[str, Any]:
        artifact = kwargs.get("artifact") or {}
        latest_version = self.store.get_draft_version()
        return {
            "draft_version": latest_version,
            "has_draft": latest_version >= 0,
            "requirements_count": len(artifact.get("requirements", []) or []),
            "decisions_count": len(artifact.get("decisions", []) or []),
            "conflicts_count": len(artifact.get("conflicts", []) or []),
            "iteration": kwargs.get("iteration", 0) + 1,
            "max_iterations": kwargs.get("max_iterations", 1),
        }

    def decide_document_output_action(
        self,
        *,
        observation: Dict[str, Any],
        last_result: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        if isinstance(last_result, dict) and not last_result.get("error"):
            return {
                "action": "done",
                "params": {},
                "reasoning": "上一輪已完成 SRS 生成，結束本次輸出。",
            }
        return {
            "action": "generate_srs",
            "params": {},
            "reasoning": "Final meeting 已完成，生成正式 SRS。",
        }

    def execute_document_output_action(
        self,
        *,
        decision: Dict[str, Any],
        **kwargs: Any,
    ) -> Dict[str, Any]:
        srs = self.generate_srs_internal(kwargs.get("artifact"))
        return {
            "action": decision.get("action", ""),
            "status": "success",
            "srs_markdown": srs,
            "summary": "完成 documentor SRS generation",
        }
