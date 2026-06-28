# Defines action prompts and output contracts.
import json
from typing import Any, Dict

from utils.language import output_language_directive
from agents.profile.base import json_only_rules


def close_issue(
    *,
    issue: Dict[str, Any],
    discussion_text: str,
    readiness: Dict[str, Any],
) -> str:
    return f"""# 任務
根據已收斂的正式會議議題，整理可寫入 formal_meeting 的具體決議。

# Action Boundary
- action=mediator.close_issue
- 本 action 將已收斂議題整理成 formal_meeting decision JSON。
- decision、requirement_changes、model_changes 與 open_questions 只反映本議題已收斂內容。

# Issue
標題: {issue.get("title", "")}
類型: {issue.get("category", "")}
描述: {issue.get("description", "")}
預期結果: {issue.get("expect_outcome", "")}

# Readiness
{json.dumps(readiness, ensure_ascii=False, indent=2)}

# Discussion
{discussion_text or "（無發言紀錄）"}

# 決議規則
- 整理已明確收斂的內容。
- decision 必須是可執行決議，不要只寫「可以結束」。
- requirement_changes / model_changes 只列本議題造成或確認的變更；沒有就回空陣列。
- open_questions 只列仍會影響 SRS 的未解問題；沒有就回空陣列。
- affected_requirement_ids 使用議題來源追蹤中的 REQ-*；沒有就回空陣列。
- affected_conflict_ids 優先使用議題來源追蹤中的 CR-*；若本議題是解決需求衝突，必須包含每一個來源 CR-*。
- {output_language_directive()}

# Output JSON
{{
  "summary": "決議摘要",
  "decision": "具體決議",
  "agreed_points": ["已同意重點"],
  "affected_requirement_ids": ["REQ-1"],
  "affected_conflict_ids": ["CR-1"],
  "requirement_changes": [{{"id": "REQ-1", "change": "confirmed_or_updated"}}],
  "model_changes": [{{"id": "SM-1", "change": "updated"}}],
  "open_questions": [{{"question": "仍待確認問題", "related_source": "REQ-1"}}]
}}
{json_only_rules()}"""
