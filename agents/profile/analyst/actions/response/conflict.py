# Defines conflict pair review response prompt.
from typing import Any, Dict, List, Optional

from agents.profile.base import pair_review_response_contract

from ...rules import conflict_rules, conflict_task
from .issue import render_response_prompt


def issue_response(
    *,
    issue: Dict[str, Any],
    previous_responses: Optional[List[Dict[str, Any]]],
    related_context: Optional[Dict[str, Any]],
) -> str:
    contract = issue.get("conflict_review_contract") if isinstance(issue.get("conflict_review_contract"), dict) else {}
    known_pair_ids = [
        str(pair_id).strip()
        for pair_id in (contract.get("known_pair_ids") or [])
        if str(pair_id).strip()
    ]
    return render_response_prompt(
        issue=issue,
        previous_responses=previous_responses,
        related_context=related_context,
        task_block=conflict_task,
        rules_block=f"""# Conflict Response Boundary
- 本 response 只提供 Analyst 對指定 pair/multiple conflict 的會議審查意見。
- 不直接更新 artifact；後續 signoff action 才會裁定 label。
- 不產生 resolution options、不改寫 URL 或 REQ。

{conflict_rules}
{pair_review_response_contract(known_pair_ids=known_pair_ids)}""",
        is_pair_review=True,
    )
