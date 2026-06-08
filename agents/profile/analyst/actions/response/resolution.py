# Defines conflict resolution stance response prompt.
from typing import Any, Dict, List, Optional

from ...rules import resolution_rules, resolution_task
from .issue import render_response_prompt


def issue_response(
    *,
    issue: Dict[str, Any],
    previous_responses: Optional[List[Dict[str, Any]]],
    related_context: Optional[Dict[str, Any]],
) -> str:
    return render_response_prompt(
        issue=issue,
        previous_responses=previous_responses,
        related_context=related_context,
        task_block=resolution_task,
        rules_block=f"""# Resolution Response Boundary
- 本 response 只針對既有 conflict resolution options 做取捨或調整建議。
- 不重新執行 conflict detection、不改變 Conflict/Neutral label。
- 不直接更新 artifact；若需要修改 URL，放在 stance.proposal.url_updates 供會議流程處理。

{resolution_rules}""",
    )
