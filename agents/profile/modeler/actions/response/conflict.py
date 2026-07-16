# Defines modeler conflict pair review prompt.
from typing import Any, Dict, List, Optional

from agents.profile.base import conflict_review_pair_ids, pair_review_response_contract

from ...rules import conflict_rules, conflict_task
from .issue import render_response_prompt


def issue_response(
    *,
    issue: Dict[str, Any],
    previous_responses: Optional[List[Dict[str, Any]]],
    related_context: Optional[Dict[str, Any]],
) -> str:
    known_pair_ids = conflict_review_pair_ids(issue)
    return render_response_prompt(
        issue=issue,
        previous_responses=previous_responses,
        related_context=related_context,
        task_block=conflict_task,
        rules_block=f"""{conflict_rules}
{pair_review_response_contract(known_pair_ids=known_pair_ids)}""",
        is_pair_review=True,
    )
