import json
from typing import Any, Dict, List

from storage.artifact import conflict_payload, load_json_path, save_json_path

from agents.profile.analyst.conflict_store import all_conflict_rows, normalize_conflict_state

from .record import attach_review_records_to_conflicts, build_pair_review_records
from .support import (
    analyst_signoff,
    analyst_changed_label_ids,
    finalize_review_reasons,
    collect_reviews,
    consensus_decisions,
    collect_missing_reviews,
    complete_missing_review_decisions,
    normalize_review_text,
)
# ---------- 衝突再審查主流程 ----------

def save_conflict_report(
    coordinator: Any,
    artifact: Dict[str, Any],
    *,
    round_num: int,
) -> None:
    """根據衝突再審查結果產生結構化 report JSON 與 Markdown 報告。"""
    coordinator.flow.store.save_artifact(artifact)
    if coordinator.flow.config.get("enable_conflict_report", True) is False:
        return
    payload = conflict_payload(artifact, include_report=True)
    conflict_rows = [
        row for row in (payload.get("report", []) or [])
        if isinstance(row, dict) and str(row.get("label") or "").strip() == "Conflict"
    ]
    if not conflict_rows:
        return
    previous_report = (
        coordinator.flow.store.load_markdown("conflict_report.md")
        if round_num > 0 and hasattr(coordinator.flow.store, "load_markdown")
        else ""
    )
    report_artifact = {
        **artifact,
        "conflict": payload,
        "conflict_rows": conflict_rows,
    }
    report_artifact = coordinator.flow.analyst_agent.generate_conflict_resolutions(report_artifact)
    report_payload = (report_artifact.get("conflict", {}) or {}).get("report", []) or []
    report_path = coordinator.flow.store.artifact_dir / "report" / f"conflict_report_v{round_num}.json"
    save_json_path(
        coordinator.flow.store.base_dir,
        report_payload,
        report_path,
    )
    artifact["conflict"] = {
        key: value
        for key, value in (report_artifact.get("conflict", payload) or {}).items()
        if key != "report"
    }
    coordinator.flow.store.save_artifact(artifact)
    report_rows = load_json_path(report_path, [])
    if not isinstance(report_rows, list):
        raise RuntimeError(f"conflict report JSON 格式錯誤: {report_path}")
    scenario = artifact.get("scenario") if isinstance(artifact.get("scenario"), dict) else {}
    conflict_md = coordinator.flow.analyst_agent.generate_conflict_report(
        {
            "scenario": str(scenario.get("name") or "").strip(),
            "conflict_report": report_rows,
        },
        round_num=round_num,
        previous_report=previous_report,
    )
    coordinator.flow.store.save_markdown(conflict_md, "conflict_report.md")
    coordinator.flow.logger.info(
        "需求衝突報告已產生：conflict_report.md",
    )

def run_conflict_review_round(
    coordinator: Any,
    issue: Dict[str, Any],
    artifact: Dict[str, Any],
    participants: List[str],
    discussion_mode: str,
    conflicts_by_id: Dict[str, Dict[str, Any]],
) -> tuple[List[Dict[str, Any]], List[str], List[str]]:
    if discussion_mode == "simultaneous":
        contributions = coordinator.flow.mediator_agent.moderate_simultaneous(
            issue, coordinator.flow.registry, artifact=artifact
        )
    else:
        contributions, _ = coordinator.flow.mediator_agent.moderate_sequential(
            issue, coordinator.flow.registry, artifact=artifact
        )
    contributions = collect_missing_reviews(
        coordinator,
        issue,
        artifact,
        contributions,
        participants,
    )
    contribution_agents = [
        str(c.get("agent") or "").strip()
        for c in contributions
        if isinstance(c, dict)
    ]
    conversation_rows: List[str] = []
    known_pair_ids = list(conflicts_by_id.keys())
    current_labels_by_id = {
        cid: str(conflict.get("label") or "").strip()
        for cid, conflict in conflicts_by_id.items()
        if isinstance(conflict, dict)
    }
    for c in contributions:
        if not isinstance(c, dict):
            continue
        agent_name = str(c.get("agent") or "").strip()
        resp = c.get("response", {}) if isinstance(c.get("response"), dict) else {}
        text = str(resp.get("text") or resp.get("content") or "").strip()
        if not agent_name or not text:
            continue
        if isinstance(resp.get("pair_reviews"), list) and resp.get("pair_reviews"):
            text = json.dumps(
                {
                    "review_summary": text,
                    "pair_reviews": resp.get("pair_reviews"),
                },
                ensure_ascii=False,
            )
        normalized_text = normalize_review_text(
            text,
            known_pair_ids=known_pair_ids,
            current_labels_by_id=current_labels_by_id,
        )
        resp["text"] = normalized_text
        if not isinstance(resp.get("pair_reviews"), list) or not resp.get("pair_reviews"):
            parsed_reviews = collect_reviews(
                [{"agent": agent_name, "response": {"text": normalized_text}}],
                known_pair_ids=known_pair_ids,
                current_labels_by_id=current_labels_by_id,
            )[1]
            if parsed_reviews:
                resp["pair_reviews"] = [
                    {k: v for k, v in row.items() if k != "agent"}
                    for row in parsed_reviews
                ]
        c["response"] = resp
        conversation_rows.append(f"{agent_name}: {normalized_text}")
    return contributions, conversation_rows, contribution_agents

def conflict_review(
    coordinator: Any, artifact: Dict[str, Any], round_num: int
) -> Dict[str, Any]:
    """針對本輪所有 Conflict/Neutral 項目執行一次衝突再審查與逐筆裁定。"""
    normalize_conflict_state(artifact)
    candidates = [
        c
        for c in all_conflict_rows(artifact)
        if isinstance(c, dict) and str(c.get("label") or "").strip() in {"Conflict", "Neutral"}
    ]
    if not candidates:
        coordinator.flow.logger.info("需求衝突再審查：無需處理項目")
        return artifact
    conflicts_by_id: Dict[str, Dict[str, Any]] = {
        str(c.get("id") or "").strip(): c
        for c in candidates
        if str(c.get("id") or "").strip()
    }

    requirement_by_id: Dict[str, Dict[str, Any]] = {
        str(r.get("id") or "").strip(): r
        for r in (artifact.get("requirements") or artifact.get("URL") or [])
        if isinstance(r, dict) and str(r.get("id") or "").strip()
    }

    conflict_summaries = []
    pair_cards = []
    for cid, conflict in conflicts_by_id.items():
        label = str(conflict.get("label") or "").strip()
        req_ids = [str(r) for r in (conflict.get("requirement_ids") or []) if str(r).strip()]
        initial_reason = str(conflict.get("initial_reason") or "").strip()
        is_multiple = len(req_ids) >= 3 or cid.startswith("MULTIPLE-")
        review_focus = (
            "判斷這組 3 條以上 requirements 共同成立時是否產生衝突；不要只挑其中任兩條重複做 pair 判斷。"
            if is_multiple
            else ""
        )
        focus_line = f"  判斷焦點: {review_focus}" if review_focus else ""
        reason_line = f"  初判理由: {initial_reason}" if initial_reason else ""
        conflict_summaries.append(f"- [{cid}] 初判={label}{focus_line}{reason_line}")
        req_rows = [
            {
                "id": rid,
                "text": str((requirement_by_id.get(rid) or {}).get("text") or "").strip(),
            }
            for rid in req_ids
        ]
        pair_cards.append({
            "id": cid,
            "requirements": req_rows,
            "current_label": label,
        })
        if initial_reason:
            pair_cards[-1]["initial_reason"] = initial_reason
        if review_focus:
            pair_cards[-1]["review_focus"] = review_focus
        conflict["requirements"] = req_rows
        if review_focus:
            conflict["review_focus"] = review_focus

    plan = coordinator.flow.mediator_agent.plan_conflict_review(
        candidates[0], artifact=artifact, registry=coordinator.flow.registry
    )
    participants = [
        str(p).strip()
        for p in (plan.get("participants") or [])
        if str(p).strip() and str(p).strip() != "user"
    ]
    if len(participants) < 2:
        raise RuntimeError(
            f"需求衝突再審查 participants 至少需要兩位有效 agent，目前為 {participants}"
        )
    discussion_mode = str(plan.get("discussion_mode") or "").strip().lower()
    if discussion_mode not in {"sequential", "simultaneous"}:
        raise RuntimeError(f"需求衝突再審查 plan discussion_mode 不合法: {discussion_mode}")

    issue = {
        "id": "R1-conflict",
        "title": "需求衝突再審查（R1）",
        "description": coordinator.flow.mediator_agent.conflict_review_description(
            conflict_summaries
        ),
        "category": "conflict_discussion",
        "participants": participants,
        "discussion_mode": discussion_mode,
        "source_ids": list(conflicts_by_id.keys()),
        "pair_cards": pair_cards,
    }
    coordinator.flow.logger.info(
        "需求衝突再審查：mode=%s | participants=%s | speaking_order: %s",
        discussion_mode,
        ", ".join(participants),
        " → ".join(participants),
    )

    contributions, conversation_rows, contribution_agents = run_conflict_review_round(
        coordinator,
        issue,
        artifact,
        participants,
        discussion_mode,
        conflicts_by_id,
    )
    _, first_round_pair_reviews = collect_reviews(
        contributions,
        known_pair_ids=list(conflicts_by_id.keys()),
        current_labels_by_id={
            cid: str(conflict.get("label") or "").strip()
            for cid, conflict in conflicts_by_id.items()
            if isinstance(conflict, dict)
        },
    )
    for review in first_round_pair_reviews:
        if isinstance(review, dict):
            review["review_round"] = 1
    analyst_changed_ids = analyst_changed_label_ids(first_round_pair_reviews, conflicts_by_id)
    second_round_debug: Dict[str, Any] = {
        "triggered": bool(analyst_changed_ids),
        "trigger_ids": analyst_changed_ids,
    }
    if analyst_changed_ids:
        pair_card_by_id = {str(card.get("id") or ""): card for card in pair_cards}
        second_conflicts_by_id = {
            cid: conflicts_by_id[cid]
            for cid in analyst_changed_ids
            if cid in conflicts_by_id
        }
        second_pair_cards = [
            {
                **pair_card_by_id.get(cid, {}),
                "first_round_pair_reviews": [
                    review for review in first_round_pair_reviews
                    if str(review.get("id") or "") == cid
                ],
            }
            for cid in second_conflicts_by_id.keys()
        ]
        second_summaries = [
            f"- [{cid}] 原標籤={conflicts_by_id[cid].get('label')}  Analyst 第一輪改判，需要第二輪 proposed_label 共識"
            for cid in second_conflicts_by_id.keys()
        ]
        second_issue = {
            "id": "R2-conflict",
            "title": "需求衝突再審查（R2）",
            "description": (
                coordinator.flow.mediator_agent.conflict_review_description(second_summaries)
                + "\n\n第二輪目標：只針對 Analyst 第一輪 proposed_label 與原標籤不同的 pair 再審查。"
                + "請各 agent 根據 requirement 原文與第一輪 pair_reviews 重新輸出 proposed_label；"
                + "本輪結束後只看 proposed_label 是否一致。"
            ),
            "category": "conflict_discussion",
            "participants": participants,
            "discussion_mode": discussion_mode,
            "source_ids": list(second_conflicts_by_id.keys()),
            "pair_cards": second_pair_cards,
            "review_round": 2,
        }
        second_contributions, second_conversation_rows, second_agents = run_conflict_review_round(
            coordinator,
            second_issue,
            artifact,
            participants,
            discussion_mode,
            second_conflicts_by_id,
        )
        _, second_round_pair_reviews = collect_reviews(
            second_contributions,
            known_pair_ids=list(second_conflicts_by_id.keys()),
            current_labels_by_id={
                cid: str(conflict.get("label") or "").strip()
                for cid, conflict in second_conflicts_by_id.items()
                if isinstance(conflict, dict)
            },
        )
        for review in second_round_pair_reviews:
            if isinstance(review, dict):
                review["review_round"] = 2
        consensus_rows, unresolved_second_conflicts, consensus_debug = (
            consensus_decisions(
                second_conflicts_by_id,
                second_round_pair_reviews,
            )
        )
        second_round_debug.update({
            "issue_id": second_issue["id"],
            "contribution_agents": second_agents,
            "consensus": consensus_debug,
        })

        remaining_conflicts_by_id = {
            cid: conflict for cid, conflict in conflicts_by_id.items()
            if cid not in second_conflicts_by_id
        }
        remaining_decisions, remaining_debug = analyst_signoff(
            coordinator,
            contributions,
            remaining_conflicts_by_id,
        ) if remaining_conflicts_by_id else ([], {"signoff_status": "skipped_no_remaining_pairs"})
        unresolved_decisions, unresolved_debug = analyst_signoff(
            coordinator,
            second_contributions,
            unresolved_second_conflicts,
        ) if unresolved_second_conflicts else ([], {"signoff_status": "skipped_consensus"})
        decisions = remaining_decisions + consensus_rows + unresolved_decisions
        extracted_pair_reviews = first_round_pair_reviews + second_round_pair_reviews
        final_reason_contributions = contributions + second_contributions
        signoff_debug = {
            "first_round_pair_reviews": first_round_pair_reviews,
            "second_round_pair_reviews": second_round_pair_reviews,
            "second_round": second_round_debug,
            "remaining_signoff": remaining_debug,
            "unresolved_second_round_signoff": unresolved_debug,
        }
        conversation_rows.extend(second_conversation_rows)
        contribution_agents.extend(second_agents)
    else:
        decisions, signoff_debug = analyst_signoff(
            coordinator, contributions, conflicts_by_id
        )
        extracted_pair_reviews = signoff_debug.get("extracted_pair_reviews", [])
        final_reason_contributions = contributions

    missing_decision_debug: Dict[str, Any] = {}
    decisions, missing_decision_debug = complete_missing_review_decisions(
        coordinator,
        decisions,
        conflicts_by_id,
        extracted_pair_reviews if isinstance(extracted_pair_reviews, list) else [],
        final_reason_contributions,
    )
    signoff_debug["missing_decisions"] = missing_decision_debug

    final_reason_debug = finalize_review_reasons(
        coordinator,
        decisions,
        conflicts_by_id,
        final_reason_contributions,
        extracted_pair_reviews if isinstance(extracted_pair_reviews, list) else [],
    )
    signoff_debug["final_reason"] = final_reason_debug

    changed = 0
    for dec in decisions:
        cid = str(dec.get("id") or "").strip()
        conflict = conflicts_by_id.get(cid)
        if not conflict:
            continue
        new_label = str(dec.get("new_label") or "").strip()
        old_label = str(conflict.get("label") or "").strip()
        modify = new_label in {"Conflict", "Neutral"} and new_label != old_label
        if modify:
            conflict["label"] = new_label
            changed += 1
        decided_by = str(dec.get("decided_by") or "").strip()
        review_status = "consensus" if "consensus" in decided_by else "analyst"
        conflict["conflict_review"] = {
            "round": round_num,
            "result": "modify" if modify else "keep",
            "status": review_status,
            "from_label": old_label,
            "to_label": new_label if modify else old_label,
            "reason": str(dec.get("reason") or ""),
        }
        final_type = str(dec.get("final_type") or "").strip()
        if new_label == "Conflict" and final_type:
            conflict["final_type"] = final_type
        elif new_label == "Neutral":
            conflict.pop("final_type", None)

    pair_review_records = build_pair_review_records(
        conflicts_by_id,
        decisions,
        extracted_pair_reviews if isinstance(extracted_pair_reviews, list) else [],
        round_num=round_num,
    )
    attach_review_records_to_conflicts(conflicts_by_id, pair_review_records)

    recheck_log = artifact.setdefault("conflict_review_log", [])
    recheck_log.append(
        {
            "round": round_num,
            "issue_id": issue.get("id"),
            "discussion_mode": discussion_mode,
            "participants": participants,
            "contribution_agents": contribution_agents,
            "candidates_count": len(decisions),
            "changed_count": changed,
            "conversation": conversation_rows,
            "decisions": decisions,
            "signoff_debug": signoff_debug,
        }
    )

    coordinator.flow.logger.info("需求衝突再審查完成：%s 筆，改判 %s 筆", len(conflicts_by_id), changed)
    save_conflict_report(coordinator, artifact, round_num=round_num)
    return artifact
