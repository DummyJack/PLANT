# 查詢當前專案 artifact 摘要，供分析師在討論時參考
import json
from typing import Dict, Any, Callable, Optional

from .base import BaseTool


class ArtifactQueryTool(BaseTool):
    """查詢當前專案狀態（需求、衝突、開放問題）摘要。由執行層在每輪討論前設定 artifact。"""

    name = "query_artifact"
    description = "查詢當前專案的需求列表、衝突列表與未回答的開放問題摘要，供發言時引用具體需求或衝突 id"
    parameters = {}

    def __init__(self, artifact_getter: Callable[[], Dict[str, Any]]):
        """
        Args:
            artifact_getter: 無參數 callable，回傳當前 artifact dict（由 agent 的 set_artifact 更新）
        """
        self.artifact_getter = artifact_getter

    def execute(self, **kwargs) -> str:
        artifact = self.artifact_getter() or {}
        summary = self._summarize(artifact)
        return json.dumps(summary, ensure_ascii=False, indent=2)

    @staticmethod
    def _summarize(artifact: Dict[str, Any]) -> Dict[str, Any]:
        """產出精簡摘要，避免 token 過多"""
        reqs = artifact.get("requirements", [])
        summary_reqs = [
            {"id": r.get("id"), "type": r.get("type"), "text": (r.get("text") or "")}
            for r in reqs
        ]
        conflicts = [
            {"id": c.get("id"), "description": (c.get("description") or "")}
            for c in artifact.get("conflicts", []) if c.get("label") == "Conflict"
        ]
        oqs = [
            {"from_agent": q.get("from_agent"), "question": (q.get("question") or "")}
            for q in artifact.get("open_questions", []) if q.get("status") != "answered"
        ]
        return {
            "requirements": summary_reqs,
            "conflicts": conflicts,
            "open_questions": oqs,
        }
