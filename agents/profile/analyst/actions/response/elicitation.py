# Defines elicitation meeting response prompt.
from typing import Any, Dict, List, Optional

from agents.profile.base import elicitation_stop_phrase

from ...rules import (
    analyst_elicitation,
    analyst_elicitation_action_rules,
    analyst_elicitation_action_task,
)
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
        task_block=analyst_elicitation_action_task(stop_phrase),
        rules_block=analyst_elicitation_action_rules(stop_phrase),
        elicitation_hint=analyst_elicitation,
    )
