# Provides RQ1 Plant experiment utils helpers.
import re
import os
from typing import Any, Dict, List

from storage.artifact import project_payload

# ========
# Defines is likely english function for this experiment module.
# ========
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

# ========
# Defines task initial requirements function for this experiment module.
# ========
def task_initial_requirements(task: Dict) -> str:
    return str(task.get("initial_requirements") or "").strip()

# ========
# Defines task implicit requirements function for this experiment module.
# ========
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

# ========
# Defines ensure artifact function for this experiment module.
# ========
def ensure_artifact(task: Dict[str, Any]) -> Dict[str, Any]:
    initial = task_initial_requirements(task)
    return {
        "rough_idea": initial,
        "scenario": {
            "name": str(task.get("name") or "").strip(),
        },
        "stakeholders": [
            {
                "name": "Oracle User",
                "type": "primary_user",
                "text": [initial] if initial else [],
            }
        ],
        "scope": {"in_scope": [], "out_of_scope": []},
        "URL": [],
        "feedback": {},
        "system_models": [],
        "open_questions": [],
        "decisions": [],
        "discussions": [],
        "elicitation": {
            "plan": {},
            "meeting": {},
            "elicited_reqts": [],
            "elicitation_stop_reason": "",
        },
        "meta": {
            "elicitation_mode": "oracle",
        },
        "elicited_reqts": [],
    }

# ========
# Defines rq1 project payload function for this experiment module.
# ========
def rq1_project_payload(artifact: Dict[str, Any]) -> Dict[str, Any]:
    payload = project_payload(artifact)
    stakeholders = []
    for row in payload.get("stakeholders", []) or []:
        if not isinstance(row, dict):
            continue
        stakeholders.append(
            {
                "name": row.get("name", ""),
                "type": row.get("type", ""),
            }
        )
    payload["stakeholders"] = stakeholders
    return payload

# ========
# Defines safe turn no function for this experiment module.
# ========
def safe_turn_no(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0

# ========
# Defines run one task function for this experiment module.
# ========
def run_one_task(
    flow: Any,
    oracle_user: Any,
    task: Dict[str, Any],
) -> Dict[str, Any]:
    initial_req = task_initial_requirements(task)
    os.environ["PLANT_OUTPUT_LANGUAGE"] = "en" if is_likely_english(initial_req) else "zh-Hant"
    artifact = ensure_artifact(task)
    oracle_user.set_task(task)

    flow.user_agent.stakeholders = artifact["stakeholders"]
    req_before = len(artifact["URL"])

    logger_verbose = getattr(flow.logger, "verbose", None)
    if logger_verbose is not None:
        flow.logger.verbose = False
    try:
        artifact = flow.meeting.run_elicitation(
            artifact,
            round_num=0,
        )
    finally:
        if logger_verbose is not None:
            flow.logger.verbose = logger_verbose
    flow.logger.info("[需求擷取會議結束]")

    req_after = len(artifact["URL"])
    elicitation_trace = artifact.get("elicitation_trace", []) or []
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
        "elicited_reqts": len((artifact.get("elicitation") or {}).get("elicited_reqts", []) or []),
        "requirements_after_elicitation": req_after,
        "elicitation_turns": len(artifact.get("elicitation_trace", []) or []),
        "termination_reason": (artifact.get("elicitation") or {}).get("elicitation_stop_reason", ""),
        "coverage": artifact.get("elicitation_coverage", {}),
        "oracle_remaining_implicit": len(oracle_user.remaining_requirements),
        "oracle_revealed_count": len(oracle_revealed_ids),
        "elicitation_plan": (artifact.get("elicitation") or {}).get("plan", {}),
        "elicitation_meeting": (artifact.get("elicitation") or {}).get("meeting", {}),
        "elicitation": artifact.get("elicitation", {}),
        "project": rq1_project_payload(artifact),
        "elicitation_trace": elicitation_trace,
        "oracle_trace": list(oracle_user.oracle_trace),
    }
