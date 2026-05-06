# Record helpers for hidden requirement elicitation meetings.
from typing import Any, Dict, List
def summarize_elicitation_meeting_conclusion(
    *,
    elicitation_log: List[Dict[str, Any]],
    candidates: List[Dict[str, Any]],
    termination_reason: str,
) -> Dict[str, Any]:
    candidate_texts = [
        str(c.get("text") or "").strip()
        for c in candidates or []
        if isinstance(c, dict) and str(c.get("text") or "").strip()
    ]
    phase_counts: Dict[str, int] = {}
    for row in elicitation_log or []:
        if not isinstance(row, dict):
            continue
        phase = str(row.get("meeting_phase") or "unknown").strip() or "unknown"
        phase_counts[phase] = phase_counts.get(phase, 0) + 1
    return {
        "termination_reason": termination_reason,
        "turns": len(elicitation_log or []),
        "phase_counts": phase_counts,
        "candidate_count": len(candidate_texts),
        "candidate_preview": candidate_texts[:5],
        "ready_for_requirement_draft": bool(candidate_texts) or termination_reason in {"judge_finish", "forced_finish_at_max_turn"},
    }
