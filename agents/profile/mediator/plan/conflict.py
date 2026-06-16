# Handles shared agent profile prompts and helper behavior.
import json
from typing import Any, Dict, List, Optional

from agents.profile.analyst.conflicts import all_conflict_rows

from ..validation import conflict_review_plan


# ========
# Defines build conflict review function for this module workflow.
# ========
def build_conflict_review(
    *,
    participants: List[str],
    candidate_count: int,
) -> str:
    return f"""# 任務
安排衝突批次再審查的討論模式與參與者。

- sequential：參與者依 participants 陣列順序逐一發言。
- simultaneous：每位參與者各自獨立、同時提出看法（實作上並行蒐集發言），不強調逐一輪替。

- 待審項目數（Conflict + Neutral）：{max(1, candidate_count)}

# 可選參與者
{json.dumps(participants, ensure_ascii=False)}

# 輸出 JSON
{{
  "discussion_mode": "sequential 或 simultaneous",
  "participants": ["至少兩位可選參與者代號"]
}}

- participants 只能從可選參與者代號中挑選，不可包含 user。
- participants 至少需要兩位；若某角色角度對本批項目沒有幫助，可以不安排。
- conflict review 應依職責安排，不是讓所有 agent 都投票：
  - analyst：需求槽位、SRS 邊界、可驗證性、是否需要合併/改寫/裁定；通常應參與。
  - expert：只有待審項目涉及外部法規、標準、合規、安全、隱私、稽核、第三方限制、領域風險或品質底線時才安排。
  - modeler：只有待審項目涉及流程、狀態、資料、角色互動、責任邊界、模型多重度或可共存性時才安排。
- participants 的陣列順序即為 sequential 時的發言順序。
- 若需逐步比對證據、修正他人判準或逐筆重判，可優先 sequential；若只需快速蒐集獨立判斷可選 simultaneous。
"""


# ========
# Defines ConflictPlan class for this module workflow.
# ========
class ConflictPlan:
    # Defines plan conflict review internal function for this module workflow.
    def plan_conflict_review_internal(
        self,
        conflict: Dict[str, Any],
        artifact: Optional[Dict[str, Any]] = None,
        registry=None,
    ) -> Dict[str, Any]:
        participants_def: List[str] = []
        if registry:
            participants_def = [
                n
                for n in registry.get_names()
                if n in {"analyst", "expert", "modeler"}
            ]
        if not participants_def:
            participants_def = ["analyst", "expert", "modeler"]

        n_candidates = 0
        if isinstance(artifact, dict):
            for c in all_conflict_rows(artifact):
                if not isinstance(c, dict):
                    continue
                if str(c.get("label") or "").strip() in {"Conflict", "Neutral"}:
                    n_candidates += 1

        prompt = build_conflict_review(
            participants=participants_def,
            candidate_count=n_candidates,
        )
        try:
            messages = self.build_direct_messages(prompt)
            data = self.chat_json(messages)
        except Exception as e:
            raise RuntimeError(f"plan_conflict_review 輸出格式不合格: {e}") from e
        return conflict_review_plan(
            data,
            allowed_participants=participants_def,
        )
