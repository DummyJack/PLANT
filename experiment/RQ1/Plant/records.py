# Provides RQ1 Plant experiment records helpers.
import json
import re
from typing import Any, Dict, List, Optional

from flow.setup import Flow
from metric import (
    round_to_4,
    round_to_2,
    compute_ora,
    compute_overall_metrics,
    compute_tkqr,
    std_from_variance,
    variance,
)

from .oracle_user import OracleUserAgent
from .utils import task_implicit_requirements, task_initial_requirements


def finish_record_text(tlog: Dict[str, Any]) -> str:
    judged_action = str(tlog.get("judged_action") or "").strip()
    if "我已蒐集足夠資訊" in judged_action:
        return "我已蒐集足夠資訊"
    return "I have gathered enough information"

# ========
# Defines resolve role model name function for this experiment module.
# ========
def resolve_role_model_name(flow_cfg: Dict[str, Any], role: str) -> str:
    agent_models = flow_cfg.get("agent_models", {})
    if not isinstance(agent_models, dict):
        return ""
    role_cfg = agent_models.get(role, {})
    if isinstance(role_cfg, dict):
        model = str(role_cfg.get("model") or "").strip()
        if model:
            return model
    default_cfg = agent_models.get("default", {})
    if isinstance(default_cfg, dict):
        model = str(default_cfg.get("model") or "").strip()
        if model:
            return model
    return ""

# ========
# Defines enabled plant roles function for this experiment module.
# ========
def enabled_plant_roles(flow_cfg: Dict[str, Any]) -> List[str]:
    base_roles = ["analyst", "expert", "modeler"]
    enabled = flow_cfg.get("enable_agents") or {}
    if not isinstance(enabled, dict):
        return base_roles
    out = [r for r in base_roles if bool(enabled.get(r, True))]
    return out or ["analyst"]

# ========
# Defines format plant roles with models function for this experiment module.
# ========
def format_plant_roles_with_models(flow_cfg: Dict[str, Any], roles: List[str]) -> str:
    rows: List[str] = []
    for role in roles:
        role_name = str(role or "").strip()
        if not role_name:
            continue
        model_name = resolve_role_model_name(flow_cfg, role_name)
        if model_name:
            rows.append(f"{role_name}:{model_name}")
        else:
            rows.append(role_name)
    return ", ".join(rows)

# ========
# Defines build plant models function for this experiment module.
# ========
def build_plant_models(flow_cfg: Dict[str, Any]) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for role in enabled_plant_roles(flow_cfg):
        out[role] = resolve_role_model_name(flow_cfg, role)
    return out


def turn_record_rows(tlog: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows = tlog.get("conversation")
    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, dict)]

# ========
# Defines resolve plant model label function for this experiment module.
# ========
def resolve_plant_model_label(flow_cfg: Dict[str, Any], per_task: Dict[str, Any]) -> str:
    participants: List[str] = []
    for tlog in (per_task.get("elicitation_trace", []) or []):
        if not isinstance(tlog, dict):
            continue
        for row in turn_record_rows(tlog):
            agent = str(row.get("agent") or "").strip()
            if agent in ("analyst", "expert", "modeler") and agent not in participants:
                participants.append(agent)

    if not participants:
        plan = per_task.get("elicitation_plan", {})
        if isinstance(plan, dict):
            for role in (plan.get("interviewers") or []):
                role_name = str(role or "").strip()
                if role_name in ("analyst", "expert", "modeler") and role_name not in participants:
                    participants.append(role_name)

    if not participants:
        participants = enabled_plant_roles(flow_cfg)

    return format_plant_roles_with_models(flow_cfg, participants)

# ========
# Defines build cost payload function for this experiment module.
# ========
def build_cost_payload(
    flow: Flow,
    oracle_user: OracleUserAgent,
    task_costs: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    cost_by_agent: Dict[str, Any] = {}
    enabled = flow.config.get("enable_agents") or {}
    for agent_name, m in flow.agent_models.items():
        if isinstance(enabled, dict) and not bool(enabled.get(agent_name, True)):
            continue
        if agent_name == "user":
            continue
        if hasattr(m, "costTracker"):
            cost_by_agent[agent_name] = m.costTracker.export_summary_dict()
    if not isinstance(enabled, dict) or bool(enabled.get("user", True)):
        cost_by_agent["user"] = oracle_user.export_cost_summary()
    totals = {
        "input_tokens": sum(int(v.get("input_tokens", 0) or 0) for v in cost_by_agent.values()),
        "output_tokens": sum(int(v.get("output_tokens", 0) or 0) for v in cost_by_agent.values()),
        "total_tokens": sum(int(v.get("total_tokens", 0) or 0) for v in cost_by_agent.values()),
        "run_time(s)": round(
            sum(float(v.get("run_time(s)", 0.0) or 0.0) for v in cost_by_agent.values()),
            3,
        ),
        "estimated_cost(USD)": round(
            sum(float(v.get("estimated_cost(USD)", 0.0) or 0.0) for v in cost_by_agent.values()),
            8,
        ),
    }
    return {"agents": cost_by_agent, "totals": totals, "tasks": task_costs or []}

# ========
# Defines extract action type effectiveness function for this experiment module.
# ========
def extract_action_type_effectiveness(conversation: List[Dict[str, Any]]) -> Dict[str, Any]:
    stats: Dict[str, Dict[str, float]] = {}
    for turn in conversation:
        action_type = str(turn.get("action_type") or "unknown")
        is_hit = bool(turn.get("is_relevant_to_implicit_requirements", False))
        if action_type not in stats:
            stats[action_type] = {"total": 0, "effective": 0}
        stats[action_type]["total"] += 1
        if is_hit:
            stats[action_type]["effective"] += 1
    out: Dict[str, Any] = {}
    for k, v in stats.items():
        total = int(v["total"])
        eff = int(v["effective"])
        out[k] = {
            "total": total,
            "effective": eff,
            "effectiveness_ratio": (eff / total) if total > 0 else 0.0,
        }
    return out

# ========
# Defines compute aspect type elicitation function for this experiment module.
# ========
def compute_aspect_type_elicitation(
    task: Dict[str, Any],
    revealed_ids: set,
) -> Dict[str, Any]:

    totals: Dict[str, int] = {}
    elicited: Dict[str, int] = {}
    implicit = task_implicit_requirements(task)
    for i, req in enumerate(implicit, start=1):
        aspect = str(req.get("aspect") or "").strip() or "Unknown"
        rid = f"IR-{i:02d}"
        if aspect not in totals:
            totals[aspect] = 0
            elicited[aspect] = 0
        totals[aspect] += 1
        if rid in revealed_ids:
            elicited[aspect] += 1
    out: Dict[str, Any] = {}
    for aspect in totals:
        total = totals[aspect]
        hit = elicited[aspect]
        out[aspect] = {
            "total": total,
            "elicited": hit,
            "elicitation_ratio": (hit / total) if total > 0 else 0.0,
        }
    return out

# ========
# Defines split trailing json object function for this experiment module.
# ========
def split_trailing_json_object(text: str) -> tuple[str, str]:
    value = str(text or "").strip()
    if not value:
        return "", ""
    decoder = json.JSONDecoder()
    for idx, ch in enumerate(value):
        if ch != "{":
            continue
        candidate = value[idx:].strip()
        try:
            parsed, end = decoder.raw_decode(candidate)
        except json.JSONDecodeError:
            continue
        if not isinstance(parsed, dict):
            continue
        if candidate[end:].strip():
            continue
        return value[:idx].strip(), candidate[:end].strip()
    return value, ""

# ========
# Defines strip metadata json objects function for this experiment module.
# ========
def strip_metadata_json_objects(text: str) -> str:
    value = str(text or "")
    if "{" not in value:
        return value.strip()
    decoder = json.JSONDecoder()
    parts: List[str] = []
    pos = 0
    while pos < len(value):
        idx = value.find("{", pos)
        if idx < 0:
            parts.append(value[pos:])
            break
        parts.append(value[pos:idx])
        try:
            parsed, end = decoder.raw_decode(value[idx:])
        except json.JSONDecodeError:
            parts.append(value[idx])
            pos = idx + 1
            continue
        json_text = value[idx:idx + end]
        metadata_type = str(parsed.get("type") or "") if isinstance(parsed, dict) else ""
        if metadata_type == "UserSignal":
            pos = idx + end
            continue
        parts.append(json_text)
        pos = idx + end
    return " ".join("".join(parts).split()).strip()

# ========
# Defines strip post meeting analysis sections function for this experiment module.
# ========
def strip_post_meeting_analysis_sections(text: str) -> str:
    value = str(text or "").strip()
    if not value:
        return ""
    section_markers = (
        "Conclusion:",
        "\n\nConclusion:",
        "\nConclusion:",
        "結論:",
        "\n\n結論:",
        "\n結論:",
        "Basis:",
        "\n\nBasis:",
        "\nBasis:",
        "Evidence:",
        "\n\nEvidence:",
        "\nEvidence:",
        "Risks/Boundaries:",
        "\n\nRisks/Boundaries:",
        "\nRisks/Boundaries:",
        "Boundaries/Risks:",
        "\n\nBoundaries/Risks:",
        "\nBoundaries/Risks:",
        "Risks:",
        "\n\nRisks:",
        "\nRisks:",
        "Risk/Boundary:",
        "\n\nRisk/Boundary:",
        "\nRisk/Boundary:",
        "Recommendation:",
        "\n\nRecommendation:",
        "\nRecommendation:",
        "Recommendation/Next Step:",
        "\n\nRecommendation/Next Step:",
        "\nRecommendation/Next Step:",
        "Recommended Next Step:",
        "\n\nRecommended Next Step:",
        "\nRecommended Next Step:",
        "Next Step:",
        "\n\nNext Step:",
        "\nNext Step:",
        "Next Steps:",
        "\n\nNext Steps:",
        "\nNext Steps:",
    )
    cut_at = len(value)
    for marker in section_markers:
        idx = value.find(marker)
        if idx >= 0:
            cut_at = min(cut_at, idx)
    return value[:cut_at].strip()

# ========
# Defines keep user record text function for this experiment module.
# ========
def keep_user_record_text(text: str) -> str:
    prefix, trailing_json = split_trailing_json_object(str(text or "").strip())
    cleaned = prefix if trailing_json and prefix else str(text or "").strip()
    cleaned = strip_metadata_json_objects(cleaned)
    cleaned = re.sub(r"(?m)^\s*【Oracle User】\s*", "", cleaned)
    return cleaned.strip()

# ========
# Defines keep interviewer record text function for this experiment module.
# ========
def keep_interviewer_record_text(text: str) -> str:
    cleaned = strip_post_meeting_analysis_sections(text)
    cleaned = strip_metadata_json_objects(cleaned)
    return cleaned.strip()

# ========
# Defines safe turn no function for this experiment module.
# ========
def safe_turn_no(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0

# ========
# Defines trace turn no function for this experiment module.
# ========
def trace_turn_no(trace: Dict[str, Any]) -> int:
    turn_no = safe_turn_no(trace.get("mediator_turn"))
    if turn_no <= 0:
        turn_no = safe_turn_no(trace.get("turn"))
    return turn_no

# ========
# Defines format mediator record text function for this experiment module.
# ========
def format_mediator_record_text(tlog: Dict[str, Any]) -> str:
    discussion_mode = str(tlog.get("discussion_mode") or "").strip()
    is_finish = bool(tlog.get("judge_finish", False)) or bool(tlog.get("forced_finish", False))
    if is_finish:
        return finish_record_text(tlog)

    participants = [
        str(role).strip()
        for role in (tlog.get("participants", []) or [])
        if str(role).strip() and str(role).strip() != "user"
    ]
    speaking_order = [
        str(role).strip()
        for role in (tlog.get("speaking_order", []) or [])
        if str(role).strip()
    ]
    parts = []
    if discussion_mode:
        parts.append(f"mode={discussion_mode}")
    if participants:
        parts.append(f"participants=[{', '.join(participants)}]")
    if speaking_order and discussion_mode != "simultaneous" and not is_finish:
        parts.append(f"speaker_order=[{', '.join(speaking_order)}]")
    return " | ".join(parts)

# ========
# Defines build task record function for this experiment module.
# ========
def build_task_record(
    *,
    task_idx: int,
    task: Dict[str, Any],
    per_task: Dict[str, Any],
    plant_model_label: str,
    user_answer_quality: str,
    token_cost: int,
) -> Dict[str, Any]:
    implicit_total = int(per_task.get("implicit_total", 0) or 0)
    turn_logs = per_task.get("elicitation_trace", []) or []

    oracle_revealed_ids = {
        str(rid)
        for tr in (per_task.get("oracle_trace", []) or [])
        if isinstance(tr, dict)
        for rid in (tr.get("revealed_ids") or [])
        if rid
    }
    elicited = len(oracle_revealed_ids)
    elicitation_ratio = (elicited / implicit_total) if implicit_total > 0 else 0.0

    conversation: List[Dict[str, Any]] = []
    revealed_seen: set = set()
    hit_sequence: List[int] = []

    trace_by_turn: Dict[int, Dict[str, Any]] = {}
    for trace in per_task.get("oracle_trace", []) or []:
        if not isinstance(trace, dict):
            continue
        turn_no = trace_turn_no(trace)
        agg = trace_by_turn.setdefault(
            turn_no,
            {
                "user_texts": [],
                "action_types": [],
                "is_hit": False,
                "revealed_ids": set(),
            },
        )
        user_text = str(trace.get("user_response") or "").strip()
        if user_text:
            agg["user_texts"].append(user_text)
        action_type = str((trace.get("judge") or {}).get("action_type") or "").strip()
        if action_type:
            agg["action_types"].append(action_type)
        if bool((trace.get("judge") or {}).get("is_relevant_to_implied_requirements", False)):
            agg["is_hit"] = True
        for rid in (trace.get("revealed_ids") or []):
            if rid:
                agg["revealed_ids"].add(str(rid))

    for tlog in turn_logs:
        if not isinstance(tlog, dict):
            continue
        turn_no = safe_turn_no(tlog.get("turn"))
        record = turn_record_rows(tlog)

        role_parts: Dict[str, List[str]] = {"analyst": [], "expert": [], "modeler": []}
        user_parts: List[str] = []
        for row in record:
            agent = str(row.get("agent") or "").strip()
            stmt = str(row.get("text") or "").strip()
            if not agent or not stmt:
                continue
            if agent == "user":
                user_stmt = keep_user_record_text(stmt)
                if user_stmt:
                    user_parts.append(user_stmt)
            elif agent in role_parts:
                stmt = keep_interviewer_record_text(stmt)
                if stmt:
                    role_parts[agent].append(stmt)
            else:

                pass

        agg = trace_by_turn.get(
            turn_no,
            {"user_texts": [], "action_types": [], "is_hit": False, "revealed_ids": set()},
        )
        hit = bool(agg.get("is_hit", False))
        turn_revealed_ids = sorted(str(rid) for rid in (agg.get("revealed_ids", set()) or []) if rid)
        for rid in turn_revealed_ids:
            revealed_seen.add(str(rid))
        hit_sequence.append(1 if hit else 0)

        action_types = agg.get("action_types", []) or []
        is_finish = bool(tlog.get("forced_finish", False) or tlog.get("judge_finish", False))
        if is_finish:
            action_type = "finish"
            user_text = ""
        else:
            action_type = action_types[0] if action_types else ""
            fallback_user_texts = [
                keep_user_record_text(text)
                for text in (agg.get("user_texts", []) or [])
                if str(text or "").strip()
            ]
            user_text = "\n".join(user_parts) if user_parts else "\n".join(fallback_user_texts)

        turn_entry = {"turn": turn_no}
        mediator_text = format_mediator_record_text(tlog)
        if mediator_text:
            turn_entry["mediator"] = mediator_text
        if not is_finish:
            for role in ("analyst", "expert", "modeler"):
                role_text = "\n\n".join(role_parts[role]).strip()
                if role_text:
                    turn_entry[role] = role_text
        if user_text:
            turn_entry["user"] = user_text
        turn_entry.update(
            {
                "action_type": action_type,
                "is_relevant_to_implicit_requirements": hit,
                "elicited_requirements": turn_revealed_ids,
                "elicitation_ratio": (
                    len(revealed_seen) / implicit_total if implicit_total > 0 else 0.0
                ),
            }
        )
        conversation.append(turn_entry)

    if not conversation:
        for turn_no in sorted(trace_by_turn.keys()):
            agg = trace_by_turn[turn_no]
            turn_revealed_ids = sorted(str(rid) for rid in (agg.get("revealed_ids", set()) or []) if rid)
            for rid in turn_revealed_ids:
                revealed_seen.add(str(rid))
            hit = bool(agg.get("is_hit", False))
            hit_sequence.append(1 if hit else 0)
            action_types = agg.get("action_types", []) or []
            turn_entry = {
                "turn": turn_no,
                "action_type": action_types[0] if action_types else "",
                "is_relevant_to_implicit_requirements": hit,
                "elicited_requirements": turn_revealed_ids,
                "elicitation_ratio": (
                    len(revealed_seen) / implicit_total if implicit_total > 0 else 0.0
                ),
            }
            user_text = "\n".join(
                keep_user_record_text(text)
                for text in (agg.get("user_texts", []) or [])
                if str(text or "").strip()
            )
            if user_text:
                turn_entry["user"] = user_text
            conversation.append(turn_entry)
    turns = len(conversation)
    tkqr = compute_tkqr(hit_sequence, implicit_total)
    ora = compute_ora(turns, implicit_total)

    aspect_type_elicitation = compute_aspect_type_elicitation(task, oracle_revealed_ids)

    app_type = str(
        task.get("application_type")
        or task.get("Application Type")
        or ((task.get("Category") or {}).get("primary_category") if isinstance(task.get("Category"), dict) else "")
        or "Unknown"
    ).strip() or "Unknown"

    return {
        "task_id": f"task_{task_idx}",
        "task_name": task.get("name", ""),
        "application_type": app_type,
        "initial_requirements": task_initial_requirements(task),
        "user_answer_quality": user_answer_quality,
        "plant_model_label": plant_model_label,
        "conversation": conversation,
        "turns": turns,

        "total_requirements": implicit_total,
        "total_elicited": elicited,
        "elicitation_ratio": elicitation_ratio,
        "tkqr": tkqr,
        "ora": ora,
        "optimal_rounds": implicit_total + 1,
        "token_cost": int(token_cost),
        "action_type_effectiveness": extract_action_type_effectiveness(conversation),
        "aspect_type_elicitation": aspect_type_elicitation,
    }

# ========
# Defines build result payload function for this experiment module.
# ========
def build_result_payload(
    *,
    flow_cfg: Dict[str, Any],
    exp_cfg: Dict[str, Any],
    task_results: List[Dict[str, Any]],
) -> Dict[str, Any]:
    summary = compute_overall_metrics(task_results)
    turns_values = [
        int(t.get("turns", 0) or 0)
        for t in task_results
        if isinstance(t, dict)
    ]
    average_turn = (
        sum(turns_values) / len(turns_values)
        if turns_values else 0.0
    )
    variance_turn = variance(turns_values, average_turn) if turns_values else 0.0
    application_type_statistics = {
        app: {
            "num_tasks": int((stats or {}).get("num_tasks", 0) or 0),
            "average_elicitation_ratio": float(
                (stats or {}).get("average_elicitation_ratio", 0.0) or 0.0
            ),
            "average_tkqr": float((stats or {}).get("average_tkqr", 0.0) or 0.0),
        }
        for app, stats in (summary.get("application_type_statistics", {}) or {}).items()
        if isinstance(stats, dict)
    }
    overall = {
        "total_test_samples": int(summary.get("total_tasks", 0) or 0),
        "total_hidden_requirements": int(summary.get("total_requirements_all_tasks", 0) or 0),
        "average_elicitation_ratio": round_to_4(summary.get("elicitation_ratio", 0.0) or 0.0),
        "average_tkqr": round_to_4(summary.get("tkqr", 0.0) or 0.0),
        "average_turn": round_to_2(average_turn),
        "std_elicitation_ratio": round_to_4(summary.get("std_elicitation_ratio", 0.0) or 0.0),
        "std_tkqr": round_to_4(summary.get("std_tkqr", 0.0) or 0.0),
        "std_turn": round_to_2(std_from_variance(variance_turn)),
        "average_token_cost": round_to_2(summary.get("average_token_cost", 0.0) or 0.0),
        "action_type_effectiveness": summary.get("action_type_effectiveness", {}) or {},
        "aspect_type_elicitation": summary.get("aspect_type_elicitation", {}) or {},
        "application_type_statistics": application_type_statistics,
    }

    return {
        "config": {
            "Plant": build_plant_models(flow_cfg),
            "judge_model": str(exp_cfg.get("gym_model") or ""),
            "user_model": str(exp_cfg.get("gym_model") or ""),
            "user_answer_quality": str(exp_cfg.get("user_answer_quality", "high")),
            "max_turns": int(flow_cfg.get("max_turns", flow_cfg.get("elicitation_max_turns", 0)) or 0),
        },
        "overall_evaluation": overall,
        "task_results": [
            {
                "task_id": t["task_id"],
                "total_requirements": t["total_requirements"],
                "total_elicited": t["total_elicited"],
                "elicitation_ratio": round_to_4(t["elicitation_ratio"]),
                "tkqr": round_to_4(t["tkqr"]),
                "turns": t["turns"],
                "optimal_rounds": t["optimal_rounds"],
                "token_cost": t["token_cost"],
                "action_type_effectiveness": t["action_type_effectiveness"],
                "aspect_type_elicitation": t["aspect_type_elicitation"],
            }
            for t in task_results
        ],
    }

# ========
# Defines print final summary function for this experiment module.
# ========
def print_final_summary(result: Dict[str, Any], records: List[Dict[str, Any]]) -> None:
    overall = result.get("overall_evaluation", {}) or {}
    app_stats = overall.get("application_type_statistics", {}) or {}
    action_stats = overall.get("action_type_effectiveness", {}) or {}
    aspect_stats = overall.get("aspect_type_elicitation", {}) or {}

    print("\n" + "=" * 60)
    print("所有任務完成！")
    print("=" * 60)
    print(f"總任務數：{len(records)}")
    avg_turns = (
        sum(int(r.get("turns", 0) or 0) for r in records) / len(records)
        if records
        else 0.0
    )
    print(f"平均 Turns：{avg_turns:.1f}")

    print("\n評估指標總結：")
    print(f"  總測試樣本數：{int(overall.get('total_test_samples', 0) or 0)}")
    print(f"  總隱式需求數：{int(overall.get('total_hidden_requirements', 0) or 0)}")
    print("\n平均指標（基於測試樣本平均）：")
    print(f"  平均取得比例：{float(overall.get('average_elicitation_ratio', 0.0) or 0.0):.2%}")
    print(f"  平均 TKQR：{float(overall.get('average_tkqr', 0.0) or 0.0):.4f}")
    print(f"  平均 Turns：{float(overall.get('average_turn', 0.0) or 0.0):.2f}")
    print("\n標準差：")
    print(f"  取得比例標準差：{float(overall.get('std_elicitation_ratio', 0.0) or 0.0):.4f}")
    print(f"  TKQR 標準差：{float(overall.get('std_tkqr', 0.0) or 0.0):.4f}")
    print(f"  Turns 標準差：{float(overall.get('std_turn', 0.0) or 0.0):.2f}")

    if app_stats:
        print("\n依應用類型統計：")
        print(f"{'Application Type':<40} {'任務數':<10} {'平均取得比例':<15} {'平均TKQR':<12}")
        print("-" * 85)
        for app in sorted(app_stats.keys()):
            s = app_stats[app] or {}
            print(
                f"{app:<40} {int(s.get('num_tasks', 0) or 0):<10} "
                f"{float(s.get('average_elicitation_ratio', 0.0) or 0.0):>13.2%} "
                f"{float(s.get('average_tkqr', 0.0) or 0.0):>10.4f}"
            )

    if action_stats:
        print("\n動作類型有效性：")
        for action_type, s in action_stats.items():
            print(
                f"  {action_type}: {int(s.get('effective', 0) or 0)}/"
                f"{int(s.get('total', 0) or 0)} = "
                f"{float(s.get('effectiveness_ratio', 0.0) or 0.0):.2%}"
            )

    if aspect_stats:
        print("\n面向類型取得比例：")
        for aspect, s in aspect_stats.items():
            s = aspect_stats.get(aspect, {}) or {}
            total = int(s.get("total", 0) or 0)
            if total <= 0:
                continue
            print(
                f"  {aspect}: {int(s.get('elicited', 0) or 0)}/{total} = "
                f"{float(s.get('elicitation_ratio', 0.0) or 0.0):.2%}"
            )
