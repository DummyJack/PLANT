import re
import os
from pathlib import Path
from typing import Any, Dict, List

from agents.profile.analyst.requirements import (
    build_requirement_candidates_from_requirements,
    merge_requirement_candidates,
    normalize_requirement_statuses,
    review_requirement_candidates_before_merge,
)


def next_result_index(prefix: str, results_dir: Path) -> int:
    """取得下一個輸出編號（同 prefix 下取現有最大值 +1）。"""
    pat = re.compile(rf"^(?:result|record|cost)_{re.escape(prefix)}_(\d+)\.json$")
    max_idx = 0
    for p in results_dir.glob(f"*_{prefix}_*.json"):
        m = pat.match(p.name)
        if not m:
            continue
        try:
            max_idx = max(max_idx, int(m.group(1)))
        except ValueError:
            continue
    return max_idx + 1


def is_likely_english(text: str) -> bool:
    s = str(text or "").strip()
    if not s:
        return False
    letters = re.findall(r"[A-Za-z]", s)
    cjk = re.findall(r"[\u4e00-\u9fff]", s)
    if not letters:
        return False
    if not cjk:
        return True
    return len(letters) >= (len(cjk) * 2)


def task_initial_requirements(task: Dict) -> str:
    return str(task.get("initial_requirements") or "").strip()


def task_implicit_requirements(task: Dict) -> List[Dict[str, str]]:
    normalized: List[Dict[str, str]] = []
    for req in (task.get("Implicit Requirements", []) or []):
        if not isinstance(req, dict):
            continue
        text = str(req.get("RequirementText") or "").strip()
        if not text:
            continue
        normalized.append(
            {
                "text": text,
                "aspect": str(req.get("Aspect") or "").strip() or "Unknown",
            }
        )
    return normalized


def ensure_artifact(task: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "rough_idea": task_initial_requirements(task),
        "stakeholders": [],
        "scope": {"in_scope": [], "out_of_scope": [], "description": ""},
        "requirements": [],
        "conflicts": [],
        "feedback": {},
        "system_models": {},
        "open_questions": [],
        "decisions": [],
        "discussions": [],
        "meta": {
            "elicitation_mode": "oracle",
            "force_elicitation_discussion_mode": "simultaneous",
        },
        "elicitation_candidates": [],
        "initial_requirement_candidates": [],
    }


def safe_turn_no(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def trace_turn_no(trace: Dict[str, Any]) -> int:
    turn_no = safe_turn_no(trace.get("mediator_turn"))
    if turn_no <= 0:
        turn_no = safe_turn_no(trace.get("turn"))
    return turn_no


def run_one_task(
    flow: Any,
    oracle_user: Any,
    task: Dict[str, Any],
) -> Dict[str, Any]:
    initial_req = task_initial_requirements(task)
    os.environ["PLANT_OUTPUT_LANGUAGE"] = "en" if is_likely_english(initial_req) else "zh-Hant"
    artifact = ensure_artifact(task)
    oracle_user.set_task(task)

    stakeholders = oracle_user.generate_stakeholder_requirements(
        rough_idea=artifact["rough_idea"],
        selected_stakeholders=["Oracle User"],
    )
    artifact["stakeholders"] = stakeholders
    flow.user_agent.stakeholders = stakeholders

    analysis = flow.analyst_agent.run_requirements_analyst(
        "analyze_requirements",
        stakeholders=stakeholders,
    )
    analyzed_requirements = [
        row for row in (analysis.get("requirements", []) if isinstance(analysis, dict) else [])
        if isinstance(row, dict) and str(row.get("text") or "").strip()
    ]
    normalize_requirement_statuses(analyzed_requirements)
    initial_candidates = build_requirement_candidates_from_requirements(
        analyzed_requirements,
        candidate_source="initial_requirement_analysis",
    )
    artifact["initial_requirement_candidates"] = initial_candidates
    initial_review = review_requirement_candidates_before_merge(
        artifact,
        initial_candidates,
        stage="initial_requirement_analysis",
        round_num=0,
        candidate_source="initial_requirement_analysis",
    )
    artifact["requirements"] = []
    initial_merge_stats = merge_requirement_candidates(
        artifact["requirements"],
        initial_review["candidates"],
        source_round=0,
    )
    artifact["initial_requirement_candidate_summary"] = {
        "candidate_count": len(initial_candidates),
        "absorbed_count": initial_merge_stats["added"],
        "merge": initial_merge_stats,
    }
    initial_scope = flow.analyst_agent.run_requirements_analyst(
        "generate_scope",
        rough_idea=artifact["rough_idea"],
        stakeholders=stakeholders,
        artifact=artifact,
    )
    if isinstance(initial_scope, dict):
        initial_scope = dict(initial_scope)
        initial_scope["version"] = 1
        initial_scope["status"] = "initial"
        initial_scope["source"] = "initial_requirement_analysis"
        artifact["scope"] = initial_scope
    req_before = len(artifact["requirements"])

    artifact = flow.meeting.run_hidden_requirement_elicitation_meeting(
        artifact,
        round_num=0,
    )

    req_after = len(artifact["requirements"])
    elicitation_log = artifact.get("elicitation_log", []) or []
    oracle_revealed_ids = {
        str(rid)
        for tr in (oracle_user.oracle_trace or [])
        if isinstance(tr, dict)
        for rid in (tr.get("revealed_ids") or [])
        if rid
    }

    return {
        "name": task.get("name", ""),
        "application_type": task.get("application_type", ""),
        "initial_requirements": task_initial_requirements(task),
        "implicit_total": len(task_implicit_requirements(task)),
        "requirements_before_elicitation": req_before,
        "elicitation_candidates": len(artifact.get("elicitation_candidates", []) or []),
        "requirements_after_elicitation": req_after,
        "elicitation_turns": len(artifact.get("elicitation_log", []) or []),
        "termination_reason": artifact.get("elicitation_termination_reason", ""),
        "coverage": artifact.get("elicitation_coverage", {}),
        "oracle_remaining_implicit": len(oracle_user.remaining_requirements),
        "oracle_revealed_count": len(oracle_revealed_ids),
        "elicitation_plan": artifact.get("elicitation_plan", {}),
        "elicitation_log": elicitation_log,
        "oracle_trace": list(oracle_user.oracle_trace),
    }
