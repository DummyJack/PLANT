# Defines expert conflict pair review prompt.
from typing import Any, Dict, List, Optional

from agents.profile.base import pair_review_response_contract

from ...rules import conflict_rules, issue_task
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
        task_block=issue_task,
        rules_block=f"""# 回應契約
{pair_review_response_contract(known_pair_ids=known_pair_ids, include_reason_evidence=True)}""",
        category_hint=conflict_rules,
        is_pair_review=True,
    )
