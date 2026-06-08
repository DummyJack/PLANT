# Defines modeler elicitation response prompt.
from typing import Any, Dict, List, Optional

from utils.language import current_output_language

from ...rules import elicitation_rules, elicitation_task, modeler_elicitation
from .issue import render_response_prompt


def issue_response(
    *,
    issue: Dict[str, Any],
    previous_responses: Optional[List[Dict[str, Any]]],
    related_context: Optional[Dict[str, Any]],
) -> str:
    stop_phrase = (
        "I have gathered enough information"
        if current_output_language() == "en"
        else "我已蒐集足夠資訊"
    )
    return render_response_prompt(
        issue=issue,
        previous_responses=previous_responses,
        related_context=related_context,
        task_block=elicitation_task(stop_phrase),
        rules_block=elicitation_rules(stop_phrase),
        elicitation_hint=modeler_elicitation,
    )
