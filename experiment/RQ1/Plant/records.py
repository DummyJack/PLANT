import json
from typing import Any, Dict, List

from flow.setup import Flow
from metric import compute_ora, compute_overall_metrics, compute_tkqr

from .oracle_user import OracleUserAgent
from .utils import task_implicit_requirements, task_initial_requirements


def extract_first_question(text: str) -> str:
    parts = [p.strip() for p in str(text or "").replace("\n", " ").split("。") if p.strip()]
    for p in parts:
        if "？" in p or "?" in p:
            return p
    return parts[0] if parts else ""


def compact_text(text: str, max_len: int = 160) -> str:
    value = " ".join(str(text or "").split())
    return value


def extract_focus_area(text: str) -> str:
    value = str(text or "").strip()
    if not value:
        return ""
    for sep in ("：", ":"):
        if sep in value:
            head = value.split(sep, 1)[0].strip()
            if 2 <= len(head) <= 20:
                return head
    return compact_text(value, 24)


def extract_reason_excerpt(text: str) -> str:
    value = str(text or "").strip()
    if not value:
        return ""
    parts = [p.strip() for p in value.replace("\n", " ").split("。") if p.strip()]
    if not parts:
        return compact_text(value, 140)
    return compact_text(parts[0], 140)


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


def enabled_interviewer_agents(flow_cfg: Dict[str, Any]) -> List[str]:
    base_roles = ["analyst", "expert", "modeler"]
    enabled = flow_cfg.get("enable_agents") or {}
    if not isinstance(enabled, dict):
        return base_roles
    out = [r for r in base_roles if bool(enabled.get(r, True))]
    return out or ["analyst"]


def format_interviewer_roles_with_models(flow_cfg: Dict[str, Any], roles: List[str]) -> str:
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


def build_plant_interviewer_models(flow_cfg: Dict[str, Any]) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for role in enabled_interviewer_agents(flow_cfg):
        out[role] = resolve_role_model_name(flow_cfg, role)
    return out


def resolve_interviewer_model_label(flow_cfg: Dict[str, Any], per_task: Dict[str, Any]) -> str:
    # 回傳實際參與的 interviewer agents + 對應模型。
    participants: List[str] = []

    # 優先以每輪 contributions 推回實際有發言的 interviewer。
    for tlog in (per_task.get("elicitation_log", []) or []):
        if not isinstance(tlog, dict):
            continue
        for row in (tlog.get("contributions", []) or []):
            if not isinstance(row, dict):
                continue
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
        participants = enabled_interviewer_agents(flow_cfg)

    return format_interviewer_roles_with_models(flow_cfg, participants)


def build_cost_payload(flow: Flow, oracle_user: OracleUserAgent) -> Dict[str, Any]:
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
    return {"agents": cost_by_agent, "totals": totals}


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


def compute_aspect_type_elicitation(
    task: Dict[str, Any],
    revealed_ids: set,
) -> Dict[str, Any]:
    # 與 ReqElicitGym 一樣：以 Implicit Requirements 的 Aspect 作為分母，
    # 命中 requirement id 作為分子。
    totals = {"Interaction": 0, "Content": 0, "Style": 0}
    elicited = {"Interaction": 0, "Content": 0, "Style": 0}
    implicit = task_implicit_requirements(task)
    for i, req in enumerate(implicit, start=1):
        aspect = str(req.get("aspect") or "").strip()
        if aspect not in totals:
            continue
        rid = f"IR-{i:02d}"
        totals[aspect] += 1
        if rid in revealed_ids:
            elicited[aspect] += 1
    out: Dict[str, Any] = {}
    for aspect in ("Interaction", "Content", "Style"):
        total = totals[aspect]
        hit = elicited[aspect]
        out[aspect] = {
            "total": total,
            "elicited": hit,
            "elicitation_ratio": (hit / total) if total > 0 else 0.0,
        }
    return out


def split_trailing_json_object(text: str) -> tuple[str, str]:
    """Return (prefix, trailing_json) when text ends with a JSON object."""
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


def strip_post_meeting_analysis_sections(text: str) -> str:
    """Keep only the interviewer-facing question/suggestion, not later analysis sections."""
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


def keep_user_record_statement(text: str) -> str:
    """User records should keep the natural answer and omit any trailing metadata JSON."""
    prefix, trailing_json = split_trailing_json_object(str(text or "").strip())
    cleaned = prefix if trailing_json and prefix else str(text or "").strip()
    return strip_metadata_json_objects(cleaned)


def keep_interviewer_record_statement(text: str) -> str:
    """Interviewer records should keep only the formal question/suggestion text."""
    cleaned = strip_post_meeting_analysis_sections(text)
    cleaned = strip_metadata_json_objects(cleaned)
    return cleaned.strip()


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


def format_mediator_record_statement(tlog: Dict[str, Any]) -> str:
    discussion_mode = str(tlog.get("discussion_mode") or "").strip()
    is_finish = bool(tlog.get("judge_finish", False)) or bool(tlog.get("forced_finish", False))
    if is_finish:
        finish_agent = str(tlog.get("judged_action_agent") or "").strip()
        if not finish_agent:
            closure_vote = tlog.get("closure_vote") if isinstance(tlog.get("closure_vote"), dict) else {}
            finish_agent = str((closure_vote or {}).get("proposer_role") or "").strip()
        return f"participants={finish_agent}" if finish_agent else ""

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


def build_task_record(
    *,
    task_idx: int,
    task: Dict[str, Any],
    per_task: Dict[str, Any],
    interviewer_model: str,
    user_answer_quality: str,
    token_cost: int,
) -> Dict[str, Any]:
    implicit_total = int(per_task.get("implicit_total", 0) or 0)
    turn_logs = per_task.get("elicitation_log", []) or []
    # 與 run_one_task 的 oracle_revealed_count 同口徑：以 oracle_trace 的 revealed_ids 去重後計算。
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
        contributions = tlog.get("contributions", []) or []

        role_parts: Dict[str, List[str]] = {"analyst": [], "expert": [], "modeler": []}
        role_actions: Dict[str, str] = {"analyst": "", "expert": "", "modeler": ""}
        user_parts: List[str] = []
        for row in contributions:
            if not isinstance(row, dict):
                continue
            agent = str(row.get("agent") or "").strip()
            stmt = str(row.get("statement") or "").strip()
            agent_action = str(row.get("action") or "").strip()
            if not agent or not stmt:
                continue
            if agent == "user":
                user_stmt = keep_user_record_statement(stmt)
                if user_stmt:
                    user_parts.append(user_stmt)
            elif agent in role_parts:
                stmt = keep_interviewer_record_statement(stmt)
                if stmt:
                    role_parts[agent].append(stmt)
                if agent_action and not role_actions.get(agent):
                    role_actions[agent] = agent_action
            else:
                # 其他角色目前不列為 interviewer 三角色欄位。
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
        forced_finish = bool(tlog.get("forced_finish", False) or tlog.get("judge_finish", False))
        if forced_finish:
            action_type = "finish"
            user_text = ""
        else:
            action_type = action_types[0] if action_types else ""
            fallback_user_texts = [
                keep_user_record_statement(text)
                for text in (agg.get("user_texts", []) or [])
                if str(text or "").strip()
            ]
            user_text = "\n".join(user_parts) if user_parts else "\n".join(fallback_user_texts)

        turn_entry = {
            "turn": turn_no,
            "mediator": format_mediator_record_statement(tlog),
            "analyst": "\n\n".join(role_parts["analyst"]),
            "expert": "\n\n".join(role_parts["expert"]),
            "modeler": "\n\n".join(role_parts["modeler"]),
            "user": user_text,
            "action_type": action_type,
            "is_relevant_to_implicit_requirements": hit,
            "elicited_requirements": turn_revealed_ids,
            "elicitation_ratio": (
                len(revealed_seen) / implicit_total if implicit_total > 0 else 0.0
            ),
        }
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
            conversation.append(
                {
                    "turn": turn_no,
                    "mediator": "",
                    "analyst": "",
                    "expert": "",
                    "modeler": "",
                    "user": "\n".join(
                        keep_user_record_statement(text)
                        for text in (agg.get("user_texts", []) or [])
                        if str(text or "").strip()
                    ),
                    "action_type": action_types[0] if action_types else "",
                    "is_relevant_to_implicit_requirements": hit,
                    "elicited_requirements": turn_revealed_ids,
                    "elicitation_ratio": (
                        len(revealed_seen) / implicit_total if implicit_total > 0 else 0.0
                    ),
                }
            )
    num_rounds = len(conversation)
    tkqr = compute_tkqr(hit_sequence, implicit_total)
    ora = compute_ora(num_rounds, implicit_total)
    # 面向統計改與 total_elicited 採同一來源，避免 turn 對齊差異導致口徑不一致。
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
        "interviewer_model": interviewer_model,
        "conversation": conversation,
        "total_turns": num_rounds,
        # 對齊 result.task_results 結構
        "total_requirements": implicit_total,
        "total_elicited": elicited,
        "elicitation_ratio": elicitation_ratio,
        "tkqr": tkqr,
        "ora": ora,
        "num_rounds": num_rounds,
        "optimal_rounds": implicit_total + 1,
        "token_cost": int(token_cost),
        "action_type_effectiveness": extract_action_type_effectiveness(conversation),
        "aspect_type_elicitation": aspect_type_elicitation,
    }


def build_result_payload(
    *,
    flow_cfg: Dict[str, Any],
    exp_cfg: Dict[str, Any],
    task_results: List[Dict[str, Any]],
) -> Dict[str, Any]:
    summary = compute_overall_metrics(task_results)
    overall = {
        "total_test_samples": int(summary.get("total_tasks", 0) or 0),
        "total_hidden_requirements": int(summary.get("total_requirements_all_tasks", 0) or 0),
        "total_elicited": int(summary.get("total_elicited_all_tasks", 0) or 0),
        "average_elicitation_ratio": float(summary.get("elicitation_ratio", 0.0) or 0.0),
        "average_tkqr": float(summary.get("tkqr", 0.0) or 0.0),
        "average_ora": float(summary.get("ora", 0.0) or 0.0),
        "variance_elicitation_ratio": float(summary.get("variance_elicitation_ratio", 0.0) or 0.0),
        "variance_tkqr": float(summary.get("variance_tkqr", 0.0) or 0.0),
        "variance_ora": float(summary.get("variance_ora", 0.0) or 0.0),
        "average_token_cost": float(summary.get("average_token_cost", 0.0) or 0.0),
        "variance_token_cost": float(summary.get("variance_token_cost", 0.0) or 0.0),
        "elicitation_ratio_from_totals": float(summary.get("elicitation_ratio_from_totals", 0.0) or 0.0),
        "action_type_effectiveness": summary.get("action_type_effectiveness", {}) or {},
        "aspect_type_elicitation": summary.get("aspect_type_elicitation", {}) or {},
        "application_type_statistics": summary.get("application_type_statistics", {}) or {},
    }

    return {
        "config": {
            "Plant": build_plant_interviewer_models(flow_cfg),
            "judge_model": str((exp_cfg.get("oracle_judge", {}) or {}).get("model", "")),
            "user_model": str((exp_cfg.get("oracle_user", {}) or {}).get("model", "")),
            "user_answer_quality": str(exp_cfg.get("user_answer_quality", "high")),
            "max_steps": int(flow_cfg.get("elicitation_max_turns", 0) or 0),
        },
        "overall_evaluation": overall,
        "task_results": [
            {
                "task_id": t["task_id"],
                "total_requirements": t["total_requirements"],
                "total_elicited": t["total_elicited"],
                "elicitation_ratio": t["elicitation_ratio"],
                "tkqr": t["tkqr"],
                "ora": t["ora"],
                "num_rounds": t["num_rounds"],
                "optimal_rounds": t["optimal_rounds"],
                "token_cost": t["token_cost"],
                "action_type_effectiveness": t["action_type_effectiveness"],
                "aspect_type_elicitation": t["aspect_type_elicitation"],
            }
            for t in task_results
        ],
    }


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
        sum(int(r.get("total_turns", 0) or 0) for r in records) / len(records)
        if records
        else 0.0
    )
    print(f"平均對話輪數：{avg_turns:.1f}")

    print("\n評估指標總結：")
    print(f"  總測試樣本數：{int(overall.get('total_test_samples', 0) or 0)}")
    print(f"  總隱式需求數：{int(overall.get('total_hidden_requirements', 0) or 0)}")
    print(f"  總取得數：{int(overall.get('total_elicited', 0) or 0)}")
    print("\n平均指標（基於測試樣本平均）：")
    print(f"  平均取得比例：{float(overall.get('average_elicitation_ratio', 0.0) or 0.0):.2%}")
    print(f"  平均 TKQR：{float(overall.get('average_tkqr', 0.0) or 0.0):.4f}")
    print(f"  平均 ORA：{float(overall.get('average_ora', 0.0) or 0.0):.4f}")
    print("\n變異數：")
    print(f"  取得比例變異數：{float(overall.get('variance_elicitation_ratio', 0.0) or 0.0):.6f}")
    print(f"  TKQR 變異數：{float(overall.get('variance_tkqr', 0.0) or 0.0):.6f}")
    print(f"  ORA 變異數：{float(overall.get('variance_ora', 0.0) or 0.0):.6f}")
    print("\n總體比例（基於總計數）：")
    print(f"  總取得比例：{float(overall.get('elicitation_ratio_from_totals', 0.0) or 0.0):.2%}")

    if app_stats:
        print("\n依應用類型統計：")
        print(f"{'Application Type':<40} {'任務數':<10} {'平均取得比例':<15} {'平均TKQR':<12} {'平均ORA':<12}")
        print("-" * 100)
        for app in sorted(app_stats.keys()):
            s = app_stats[app] or {}
            print(
                f"{app:<40} {int(s.get('num_tasks', 0) or 0):<10} "
                f"{float(s.get('average_elicitation_ratio', 0.0) or 0.0):>13.2%} "
                f"{float(s.get('average_tkqr', 0.0) or 0.0):>10.4f} "
                f"{float(s.get('average_ora', 0.0) or 0.0):>10.4f}"
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
        for aspect in ("Interaction", "Content", "Style"):
            s = aspect_stats.get(aspect, {}) or {}
            total = int(s.get("total", 0) or 0)
            if total <= 0:
                continue
            print(
                f"  {aspect}: {int(s.get('elicited', 0) or 0)}/{total} = "
                f"{float(s.get('elicitation_ratio', 0.0) or 0.0):.2%}"
            )
