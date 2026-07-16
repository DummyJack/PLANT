# Defines expert elicitation response prompt.
from typing import Any, Dict, List, Optional

from agents.profile.base import elicitation_stop_phrase

from ...rules import expert_elicitation, elicitation_rules, elicitation_task
from .issue import render_response_prompt


def issue_response(
    *,
    issue: Dict[str, Any],
    previous_responses: Optional[List[Dict[str, Any]]],
    related_context: Optional[Dict[str, Any]],
) -> str:
    stop_phrase = elicitation_stop_phrase()
    return render_response_prompt(
        issue=issue,
        previous_responses=previous_responses,
        related_context=related_context,
        task_block=elicitation_task(stop_phrase),
        rules_block=elicitation_rules(stop_phrase),
        elicitation_hint=expert_elicitation,
    )
