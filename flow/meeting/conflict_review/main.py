# Handles main logic for project flow orchestration and stage execution.
import json
from typing import Any, Dict, List

from storage.artifact import (
    conflict_payload,
    load_json_path,
    reindex_conflict_report_rows,
    save_json_path,
    unresolved_conflict_report_rows,
)

from agents.profile.analyst.conflicts import all_conflict_rows, normalize_conflict_state

from .conversation import attach_review_conversation_to_conflicts, build_pair_review_conversation
from .support import (
    analyst_signoff,
    analyst_changed_label_ids,
    conflict_current_label,
    finalize_review_reasons,
    collect_reviews,
    consensus_decisions,
    collect_missing_reviews,
    complete_missing_review_decisions,
    normalize_review_text,
)

CONFLICT_REVIEW_BATCH_SIZE = 20


def conflict_review_pair_cards_block(pair_cards: List[Dict[str, Any]]) -> str:
    return (
        "\n\nPair Cards JSON（逐筆審查必須以 requirements 原文為準，不可只依初判標籤或摘要）：\n"
        + json.dumps(pair_cards, ensure_ascii=False, indent=2)
        + "\n\n再審查校準：\n"
        "- current_label 只是初步辨識結果，不是答案；每筆都必須重新判斷。\n"
        "- 若 current_label=Neutral，仍須主動檢查是否為同一需求槽位的範圍、門檻、輸出、規範強度、允許集合或驗收邊界差異。\n"
        "- 不要只因兩項需求可同時實作、可做成選項、可合併、可澄清，或其中一項較具體，就判 Neutral。\n"
        "- 明確 display/output 形式、standard/non-standard、named subset/all、shall/must、量化/未量化，若落在同一槽位，通常是 Conflict。\n"
        "- 同一既有流程的 mimic/preserve 與 make practical/improve/change 是流程保留程度差異，判 Conflict。\n"
        "- 同一 capability 的 personalized 與 semi-personalized 是支援程度差異，判 Conflict；但具體模板能力 vs 廣義最小客製政策仍判 Neutral。\n"
        "- 同一品質或效率目標的 general improvement 與 quantified threshold 是驗收門檻差異，判 Conflict。\n"
        "- 若原文清楚是不同情境、不同階段、互補條件分支、限定試辦範圍、或方法與必要配件/前置條件，才判 Neutral。\n"
        "- including / such as / for example 通常只是舉例，不等於限定集合；不要與 named subset/all 規則混用。\n"
        "- 不要推定 pilot/trial/exception/special case 與一般規則必然重疊；沒有明確同條件時判 Neutral，即使方法不同或一般規則使用 only。\n"
        "- only if/enough/unique/success 條件與 if not/not enough/not unique/failure 條件是互補 guard condition，判 Neutral。\n"
        "- hierarchy/subclass/tree depth 與 membership/credential/device/PIN/reader 通常不是同一槽位，判 Neutral。\n"
        "- 具體客製化能力與廣義最小化客製政策可並存；除非原文明確禁止該能力，判 Neutral。\n"
        "- user class 是否可替代 security keys，與 user class 可定義在 hospital-wide/service scope，是用途限制與組織範圍，判 Neutral。\n"
        "- 一般 allow/support 能力與該能力的強化版本可並存；除非兩者明確定義互斥門檻，判 Neutral。\n"
        "- 同一敏感資料顯示事件中 authorized users 與 only if not authorized users 是相反 guard，判 Conflict。"
    )


# ========
# Defines save conflict report function for this module workflow.
# ========
def save_conflict_report(
    coordinator: Any,
    artifact: Dict[str, Any],
    *,
    round_num: int,
) -> bool:
    coordinator.flow.store.save_artifact(artifact)
    if coordinator.flow.config.get("enable_conflict_report", True) is False:
        return False
    payload = conflict_payload(artifact, include_report=True)
    conflict_rows = [
        row for row in (payload.get("report", []) or [])
        if isinstance(row, dict) and str(row.get("final_label") or "").strip() == "Conflict"
    ]
    conflict_rows = unresolved_conflict_report_rows(conflict_rows)
    if not conflict_rows:
        return False
    report_artifact = {
        **artifact,
        "conflict": {
            **payload,
            "report": conflict_rows,
        },
        "conflict_rows": conflict_rows,
    }
    report_artifact = coordinator.flow.analyst_agent.resolve_conflicts(report_artifact)
    report_payload = [
        row for row in ((report_artifact.get("conflict", {}) or {}).get("report", []) or [])
        if isinstance(row, dict) and str(row.get("final_label") or "").strip() == "Conflict"
    ]
    report_payload = unresolved_conflict_report_rows(report_payload)
    report_payload = reindex_conflict_report_rows(report_payload)
    if not report_payload:
        return False
    coordinator.flow.logger.step_started(
        "conflict_detection",
        "conflict_detection.write_report",
        "產生衝突報告",
        agent="analyst",
        message="衝突報告產生中 ...",
    )
    artifact["conflict_report"] = report_payload
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
    report_rows = load_json_path(report_path, [])
    if not isinstance(report_rows, list):
        raise RuntimeError(f"conflict report JSON 格式錯誤: {report_path}")
    coordinator.flow.store.save_artifact(artifact)
    conflict_md = coordinator.flow.analyst_agent.generate_conflict_report(
        {
            "conflict_report": report_rows,
        },
        round_num=round_num,
    )
    coordinator.flow.store.save_markdown(conflict_md, f"conflict_report_v{round_num}.md")
    coordinator.flow.logger.step_completed(
        "conflict_detection",
        "conflict_detection.write_report",
        "產生衝突報告",
        agent="analyst",
        output_path=f"artifact/report/conflict_report_v{round_num}.md",
    )
    return True

# ========
# Defines run conflict review round function for this module workflow.
# ========
def run_conflict_review_round(
    coordinator: Any,
    issue: Dict[str, Any],
    artifact: Dict[str, Any],
    participants: List[str],
    discussion_mode: str,
    conflicts_by_id: Dict[str, Dict[str, Any]],
) -> tuple[List[Dict[str, Any]], List[str], List[str]]:
    if discussion_mode == "simultaneous":
        conversation = coordinator.flow.mediator_agent.moderate_simultaneous(
            issue, coordinator.flow.registry, artifact=artifact
        )
    else:
        conversation, _ = coordinator.flow.mediator_agent.moderate_sequential(
            issue, coordinator.flow.registry, artifact=artifact
        )
    conversation = collect_missing_reviews(
        coordinator,
        issue,
        artifact,
        conversation,
        participants,
    )
    conversation_agents = [
        str(c.get("agent") or "").strip()
        for c in conversation
        if isinstance(c, dict)
    ]
    conversation_rows: List[str] = []
    known_pair_ids = list(conflicts_by_id.keys())
    current_labels_by_id = {
        cid: conflict_current_label(conflict)
        for cid, conflict in conflicts_by_id.items()
        if isinstance(conflict, dict)
    }
    for c in conversation:
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
    return conversation, conversation_rows, conversation_agents

# ========
# Defines conflict review function for this module workflow.
# ========
def conflict_review(
    coordinator: Any, artifact: Dict[str, Any], round_num: int
) -> Dict[str, Any]:
    normalize_conflict_state(artifact)
    candidates = [
        c
        for c in all_conflict_rows(artifact)
        if isinstance(c, dict) and conflict_current_label(c) in {"Conflict", "Neutral"}
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
        for r in (artifact.get("URL") or [])
        if isinstance(r, dict) and str(r.get("id") or "").strip()
    }

    conflict_summaries = []
    summary_by_id: Dict[str, str] = {}
    pair_cards = []
    pair_card_by_id: Dict[str, Dict[str, Any]] = {}
    for cid, conflict in conflicts_by_id.items():
        label = conflict_current_label(conflict)
        req_ids = [str(r) for r in (conflict.get("requirement_ids") or []) if str(r).strip()]
        initial_reason = str(conflict.get("initial_reason") or "").strip()
        is_multiple = cid.startswith("MULTIPLE-")
        review_focus = (
            "判斷這組 requirements 是否圍繞同一決策、規則、流程、資料或 scope 問題形成集合型衝突。"
            if is_multiple
            else ""
        )
        focus_line = f"  判斷焦點: {review_focus}" if review_focus else ""
        reason_line = f"  初判理由: {initial_reason}" if initial_reason else ""
        summary = f"- [{cid}] 初判={label}{focus_line}{reason_line}"
        conflict_summaries.append(summary)
        summary_by_id[cid] = summary
        req_rows = [
            {
                "id": rid,
                "text": str((requirement_by_id.get(rid) or {}).get("text") or "").strip(),
            }
            for rid in req_ids
        ]
        pair_card = {
            "id": cid,
            "requirements": req_rows,
            "current_label": label,
        }
        pair_cards.append(pair_card)
        pair_card_by_id[cid] = pair_card
        if initial_reason:
            pair_card["initial_reason"] = initial_reason
        if review_focus:
            pair_card["review_focus"] = review_focus
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
    registered = set(coordinator.flow.registry.get_names())
    preferred_participants = [
        agent for agent in ("analyst", "expert", "modeler")
        if agent in registered
    ]
    if len(preferred_participants) >= 2:
        participants = preferred_participants
    if len(participants) < 2:
        raise RuntimeError(
            f"需求衝突再審查 participants 至少需要兩位有效 agent，目前為 {participants}"
        )
    discussion_mode = str(plan.get("discussion_mode") or "").strip().lower()
    if discussion_mode not in {"sequential", "simultaneous"}:
        raise RuntimeError(f"需求衝突再審查 plan discussion_mode 不合法: {discussion_mode}")

    coordinator.flow.logger.step_completed(
        "conflict_review",
        "conflict_review.plan",
        "Plan",
        agent="mediator",
        message=(
            f"需求衝突再審查：mode={discussion_mode} | "
            f"participants={', '.join(participants)} | "
            f"participants_order: {' → '.join(participants)}"
        ),
    )

    decisions: List[Dict[str, Any]] = []
    extracted_pair_reviews: List[Dict[str, Any]] = []
    final_reason_conversation: List[Dict[str, Any]] = []
    conversation_rows: List[str] = []
    conversation_agents: List[str] = []
    conflict_items = list(conflicts_by_id.items())
    total_batches = max(1, (len(conflict_items) + CONFLICT_REVIEW_BATCH_SIZE - 1) // CONFLICT_REVIEW_BATCH_SIZE)

    for batch_index, start in enumerate(range(0, len(conflict_items), CONFLICT_REVIEW_BATCH_SIZE), start=1):
        batch_items = conflict_items[start : start + CONFLICT_REVIEW_BATCH_SIZE]
        batch_conflicts_by_id = {cid: conflict for cid, conflict in batch_items}
        batch_ids = list(batch_conflicts_by_id.keys())
        batch_pair_cards = [pair_card_by_id[cid] for cid in batch_ids if cid in pair_card_by_id]
        batch_summaries = [summary_by_id[cid] for cid in batch_ids if cid in summary_by_id]
        batch_label = f"{batch_index}/{total_batches}"

        coordinator.flow.logger.info(
            "需求衝突再審查：批次 %s，pairs=%s",
            batch_label,
            ", ".join(batch_ids[:3]) + ("..." if len(batch_ids) > 3 else ""),
        )
        issue = {
            "id": f"R1-conflict-b{batch_index}",
            "title": f"需求衝突再審查（R1 批次 {batch_label}）",
            "description": (
                coordinator.flow.mediator_agent.conflict_review_description(batch_summaries)
                + f"\n\n本批次審查 {len(batch_ids)} 筆 pair。"
                + conflict_review_pair_cards_block(batch_pair_cards)
            ),
            "category": "resolve_conflict",
            "participants": participants,
            "discussion_mode": discussion_mode,
            "trace": {"artifact_ids": batch_ids, "proposal_ids": []},
            "pair_cards": batch_pair_cards,
            "conflict_review_contract": {
                "type": "pair_reviews",
                "known_pair_ids": batch_ids,
                "current_labels_by_id": {
                    cid: conflict_current_label(conflict)
                    for cid, conflict in batch_conflicts_by_id.items()
                    if isinstance(conflict, dict)
                },
            },
        }
        conversation, batch_conversation_rows, batch_conversation_agents = run_conflict_review_round(
            coordinator,
            issue,
            artifact,
            participants,
            discussion_mode,
            batch_conflicts_by_id,
        )
        _, first_round_pair_reviews = collect_reviews(
            conversation,
            known_pair_ids=batch_ids,
            current_labels_by_id={
                cid: conflict_current_label(conflict)
                for cid, conflict in batch_conflicts_by_id.items()
                if isinstance(conflict, dict)
            },
        )
        for review in first_round_pair_reviews:
            if isinstance(review, dict):
                review["review_round"] = 1
        analyst_changed_ids = analyst_changed_label_ids(first_round_pair_reviews, batch_conflicts_by_id)
        if analyst_changed_ids:
            second_conflicts_by_id = {
                cid: batch_conflicts_by_id[cid]
                for cid in analyst_changed_ids
                if cid in batch_conflicts_by_id
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
                    f"- [{cid}] 原標籤={batch_conflicts_by_id[cid].get('final_label')}  Analyst 第一輪改判，需要第二輪 proposed_label 共識"
                for cid in second_conflicts_by_id.keys()
            ]
            second_issue = {
                "id": f"R2-conflict-b{batch_index}",
                "title": f"需求衝突再審查（R2 批次 {batch_label}）",
                "description": (
                    coordinator.flow.mediator_agent.conflict_review_description(second_summaries)
                    + "\n\n第二輪目標：針對 Analyst 第一輪 proposed_label 與原標籤不同的 pair 再審查。"
                    + "請各 agent 根據 requirement 原文與第一輪 pair_reviews 重新輸出 proposed_label；"
                    + "本輪以 proposed_label 是否一致作為收斂依據。"
                    + conflict_review_pair_cards_block(second_pair_cards)
                ),
                "category": "resolve_conflict",
                "participants": participants,
                "discussion_mode": discussion_mode,
                "trace": {"artifact_ids": list(second_conflicts_by_id.keys()), "proposal_ids": []},
                "pair_cards": second_pair_cards,
                "review_round": 2,
                "conflict_review_contract": {
                    "type": "pair_reviews",
                    "known_pair_ids": list(second_conflicts_by_id.keys()),
                    "current_labels_by_id": {
                        cid: conflict_current_label(conflict)
                        for cid, conflict in second_conflicts_by_id.items()
                        if isinstance(conflict, dict)
                    },
                },
            }
            second_conversation, second_conversation_rows, second_agents = run_conflict_review_round(
                coordinator,
                second_issue,
                artifact,
                participants,
                discussion_mode,
                second_conflicts_by_id,
            )
            _, second_round_pair_reviews = collect_reviews(
                second_conversation,
                known_pair_ids=list(second_conflicts_by_id.keys()),
                current_labels_by_id={
                    cid: conflict_current_label(conflict)
                    for cid, conflict in second_conflicts_by_id.items()
                    if isinstance(conflict, dict)
                },
            )
            for review in second_round_pair_reviews:
                if isinstance(review, dict):
                    review["review_round"] = 2
            consensus_rows, unresolved_second_conflicts, _ = (
                consensus_decisions(
                    second_conflicts_by_id,
                    second_round_pair_reviews,
                    expected_agents=set(participants),
                )
            )
            remaining_conflicts_by_id = {
                cid: conflict for cid, conflict in batch_conflicts_by_id.items()
                if cid not in second_conflicts_by_id
            }
            remaining_decisions, _ = analyst_signoff(
                coordinator,
                conversation,
                remaining_conflicts_by_id,
                expected_agents=set(participants),
            ) if remaining_conflicts_by_id else ([], {"signoff_status": "skipped_no_remaining_pairs"})
            unresolved_decisions, _ = analyst_signoff(
                coordinator,
                second_conversation,
                unresolved_second_conflicts,
                expected_agents=set(participants),
            ) if unresolved_second_conflicts else ([], {"signoff_status": "skipped_consensus"})
            batch_decisions = remaining_decisions + consensus_rows + unresolved_decisions
            batch_reviews = first_round_pair_reviews + second_round_pair_reviews
            batch_final_conversation = conversation + second_conversation
            batch_conversation_rows.extend(second_conversation_rows)
            batch_conversation_agents.extend(second_agents)
        else:
            batch_decisions, signoff_info = analyst_signoff(
                coordinator,
                conversation,
                batch_conflicts_by_id,
                expected_agents=set(participants),
            )
            batch_reviews = signoff_info.get("extracted_pair_reviews", [])
            batch_final_conversation = conversation

        decisions.extend(batch_decisions)
        extracted_pair_reviews.extend(batch_reviews if isinstance(batch_reviews, list) else [])
        final_reason_conversation.extend(batch_final_conversation)
        conversation_rows.extend(batch_conversation_rows)
        conversation_agents.extend(batch_conversation_agents)

    decisions, _ = complete_missing_review_decisions(
        coordinator,
        decisions,
        conflicts_by_id,
        extracted_pair_reviews if isinstance(extracted_pair_reviews, list) else [],
        final_reason_conversation,
    )

    finalize_review_reasons(
        coordinator,
        decisions,
        conflicts_by_id,
        final_reason_conversation,
        extracted_pair_reviews if isinstance(extracted_pair_reviews, list) else [],
    )

    changed = 0
    for dec in decisions:
        cid = str(dec.get("id") or "").strip()
        conflict = conflicts_by_id.get(cid)
        if not conflict:
            continue
        final_label = str(dec.get("final_label") or "").strip()
        old_label = conflict_current_label(conflict)
        modify = final_label in {"Conflict", "Neutral"} and final_label != old_label
        if modify:
            changed += 1
        decided_by = str(dec.get("decided_by") or "").strip()
        review_status = "consensus" if "consensus" in decided_by else "analyst"
        conflict["initial_label"] = old_label
        conflict["final_label"] = final_label if final_label in {"Conflict", "Neutral"} else old_label
        conflict["status"] = review_status
        conflict["description"] = str(dec.get("reason") or "")
        conflict.pop("conflict_review", None)
        final_type = str(
            dec.get("final_type")
            or conflict.get("final_type")
            or ""
        ).strip()
        if final_label == "Conflict" and not final_type:
            final_type = "other"
        if final_label == "Conflict" and final_type:
            conflict["final_type"] = final_type
        elif final_label == "Neutral":
            conflict.pop("final_type", None)

    pair_review_conversation = build_pair_review_conversation(
        conflicts_by_id,
        decisions,
        extracted_pair_reviews if isinstance(extracted_pair_reviews, list) else [],
        round_num=round_num,
    )
    attach_review_conversation_to_conflicts(conflicts_by_id, pair_review_conversation)

    coordinator.flow.logger.step_completed(
        "conflict_review",
        "conflict_review.resolve_conflicts",
        "衝突審查裁定",
        agent="analyst",
        message=f"檢查 {len(conflicts_by_id)} 筆，改判 {changed} 筆",
        output_path="artifact/result.json",
    )
    save_conflict_report(coordinator, artifact, round_num=round_num)
    return artifact
