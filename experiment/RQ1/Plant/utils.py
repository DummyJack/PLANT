import re
import os
from pathlib import Path
from typing import Any, Dict, List

from storage.artifact import project_payload


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
    initial = task_initial_requirements(task)
    return {
        "rough_idea": initial,
        "scenario": {
            "name": str(task.get("name") or "").strip(),
        },
        "stakeholders": [
            {
                "name": "Oracle User",
                "type": "Primary Users",
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


def print_rq1_oracle_elicitation_trace(
    logger: Any,
    *,
    artifact: Dict[str, Any],
    oracle_user: Any,
    task: Dict[str, Any],
) -> None:
    implicit_total = len(task_implicit_requirements(task))
    trace_by_turn: Dict[int, Dict[str, Any]] = {}
    for trace in getattr(oracle_user, "oracle_trace", []) or []:
        if not isinstance(trace, dict):
            continue
        turn_no = trace_turn_no(trace)
        if turn_no <= 0:
            continue
        row = trace_by_turn.setdefault(
            turn_no,
            {
                "action_types": [],
                "is_relevant": False,
                "revealed_ids": set(),
                "user_texts": [],
            },
        )
        judge = trace.get("judge") if isinstance(trace.get("judge"), dict) else {}
        action_type = str(judge.get("action_type") or "").strip()
        if action_type:
            row["action_types"].append(action_type)
        if bool(judge.get("is_relevant_to_implied_requirements", False)):
            row["is_relevant"] = True
        user_text = str(trace.get("user_response") or "").strip()
        if user_text:
            row["user_texts"].append(user_text)
        for rid in trace.get("revealed_ids", []) or []:
            rid_s = str(rid).strip()
            if rid_s:
                row["revealed_ids"].add(rid_s)

    revealed_seen: set[str] = set()
    for turn_log in artifact.get("elicitation_trace", []) or []:
        if not isinstance(turn_log, dict):
            continue
        turn_no = safe_turn_no(turn_log.get("turn"))
        if turn_no <= 0:
            continue
        forced_finish = bool(turn_log.get("forced_finish", False) or turn_log.get("judge_finish", False))
        trace_row = trace_by_turn.get(
            turn_no,
            {"action_types": [], "is_relevant": False, "revealed_ids": set(), "user_texts": []},
        )
        turn_revealed_ids = sorted(str(rid) for rid in trace_row.get("revealed_ids", set()) if rid)
        for rid in turn_revealed_ids:
            revealed_seen.add(rid)
        remaining_total = max(0, implicit_total - len(revealed_seen))
        ratio = (len(revealed_seen) / implicit_total) if implicit_total > 0 else 0.0

        logger.info("[輪次 %s]", turn_no)
        action_types = trace_row.get("action_types", []) or []
        action_type = "finish" if forced_finish else (action_types[-1] if action_types else "unknown")
        logger.info("  動作類型：%s", action_type)
        logger.info("  與隱式需求相關：%s", bool(trace_row.get("is_relevant", False)))
        logger.info("  已取得的需求：%s", turn_revealed_ids)

        if forced_finish:
            participants = str(turn_log.get("judged_action_agent") or "mediator").strip() or "mediator"
            text = str(turn_log.get("judged_action") or "").strip()
            logger.info("  Plant: participants=%s | %s", participants, text or "(no text)")
            logger.info("  停止：達到最後一輪，直接進入 finish 收尾（不再執行 user 對話）")
        else:
            mode = str(turn_log.get("discussion_mode") or "").strip()
            participants = [
                str(role).strip()
                for role in turn_log.get("participants", []) or []
                if str(role).strip() and str(role).strip() != "user"
            ]
            parts = []
            if mode:
                parts.append(f"mode={mode}")
            parts.append("participants=%s" % (",".join(participants) or "-"))
            speaking_order = [
                str(role).strip()
                for role in turn_log.get("speaking_order", []) or []
                if str(role).strip()
            ]
            if mode != "simultaneous" and speaking_order:
                parts.append("speaker_order=%s" % ",".join(speaking_order))
            text = str(turn_log.get("judged_action") or "").strip()
            logger.info("  Plant: %s | %s", " | ".join(parts), text or "(no text)")
            user_texts = [
                str(text).strip()
                for text in trace_row.get("user_texts", []) or []
                if str(text).strip()
            ]
            if user_texts:
                logger.info("  User: %s", "\n".join(user_texts))

        logger.info(
            "  觀察：總需求=%s，剩餘=%s，取得比例=%.2f%%",
            implicit_total,
            remaining_total,
            ratio * 100.0,
        )

    logger.info("[需求擷取會議結束]")


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
        artifact = flow.meeting.run_requirement_elicitation_meeting(
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
