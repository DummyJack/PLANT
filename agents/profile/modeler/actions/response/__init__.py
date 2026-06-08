# Routes modeler response prompts by meeting issue type.
from typing import Any, Dict, List, Optional

from . import answer, conflict, elicitation, issue as issue_prompt, resolution


def issue_response(
    *,
    issue: Dict[str, Any],
    previous_responses: Optional[List[Dict[str, Any]]],
    related_context: Optional[Dict[str, Any]],
) -> str:
    issue_id = str(issue.get("id") or "").strip()
    category = str(issue.get("category") or "").strip()
    contract = issue.get("conflict_review_contract") if isinstance(issue.get("conflict_review_contract"), dict) else {}
    is_pair_review = (
        category == "resolve_conflict"
        and str(contract.get("type") or "").strip() == "pair_reviews"
    )
    if issue_id == "OQ":
        target = answer
    elif issue_id.startswith("ELICIT-"):
        target = elicitation
    elif is_pair_review:
        target = conflict
    elif category == "resolve_conflict":
        target = resolution
    else:
        target = issue_prompt
    return target.issue_response(
        issue=issue,
        previous_responses=previous_responses,
        related_context=related_context,
    )
