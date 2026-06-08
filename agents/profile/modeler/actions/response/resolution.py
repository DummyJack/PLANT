# Defines modeler conflict resolution stance prompt.
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
        rules_block=resolution_rules,
    )
