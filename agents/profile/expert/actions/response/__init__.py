# Routes expert response prompts by meeting issue type.
from typing import Any, Dict, List, Optional

from agents.profile.base import response_prompt_kind

from . import answer, conflict, elicitation, issue as issue_prompt, resolution


def issue_response(
    *,
    issue: Dict[str, Any],
    previous_responses: Optional[List[Dict[str, Any]]],
    related_context: Optional[Dict[str, Any]],
) -> str:
    target = {
        "answer": answer,
        "conflict": conflict,
        "elicitation": elicitation,
        "issue": issue_prompt,
        "resolution": resolution,
    }[response_prompt_kind(issue)]
    return target.issue_response(
        issue=issue,
        previous_responses=previous_responses,
        related_context=related_context,
    )
