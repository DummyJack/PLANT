# Initialization flow: scope, initial requirements, elicitation, conflicts, and domain research.
from itertools import combinations
from typing import Any, Dict, List, Optional, Tuple

from utils import Collect, read_max_iterations, human_setting
from agents.profile.analyst.requirements import (
    build_requirement_candidates_from_requirements,
    merge_requirement_candidates,
    normalize_requirement_statuses,
    review_requirement_candidates_before_merge,
)


def build_fallback_requirements_from_stakeholders(stakeholders: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Analyst JSON 解析失敗或回空時，用 stakeholder 原始發言建立最小需求基礎。"""
    requirements: List[Dict[str, Any]] = []
    seen_texts = set()
    counter = 1
    for stakeholder in stakeholders or []:
        if not isinstance(stakeholder, dict):
            continue
        name = str(stakeholder.get("name") or "stakeholder").strip() or "stakeholder"
        texts = stakeholder.get("text") or []
        if isinstance(texts, str):
            texts = [line.strip() for line in texts.splitlines() if line.strip()]
        if not isinstance(texts, list):
            continue
        for text in texts:
            req_text = str(text or "").strip()
            if not req_text or req_text in seen_texts:
                continue
            seen_texts.add(req_text)
            requirements.append(
                {
                    "id": f"REQ-{counter:03d}",
                    "text": req_text,
                    "type": "FR",
                    "priority": "should",
                    "source_stakeholders": [name],
                    "source": "stakeholder_interview",
                    "rationale": f"由利害關係人「{name}」初始訪談提出。",
                    "verification_method": "review",
                    "acceptance_criteria": "需求內容經相關利害關係人確認，且可在 SRS 中追溯來源。",
                    "status": "unverified",
                }
            )
            counter += 1
    return requirements


def requirement_pair_key(req_ids: List[Any]) -> Optional[Tuple[str, str]]:
    ids = [str(rid or "").strip() for rid in (req_ids or []) if str(rid or "").strip()]
    if len(ids) != 2:
        return None
    a, b = sorted(ids)
    return (a, b)


def covered_conflict_pairs(conflicts: List[Dict[str, Any]]) -> set[Tuple[str, str]]:
    covered: set[Tuple[str, str]] = set()
    for row in conflicts or []:
        if not isinstance(row, dict):
            continue
        key = requirement_pair_key(row.get("requirement_ids") or row.get("related_requirements") or [])
        if key:
            covered.add(key)
    return covered


def requirement_pair_priority(req_a: Dict[str, Any], req_b: Dict[str, Any]) -> int:
    score = 0
    if str(req_a.get("type") or "").strip() and str(req_a.get("type") or "").strip() == str(req_b.get("type") or "").strip():
        score += 3
    src_a = {
        str(x).strip()
        for x in (req_a.get("source_stakeholders") or [])
        if str(x).strip()
    }
    src_b = {
        str(x).strip()
        for x in (req_b.get("source_stakeholders") or [])
        if str(x).strip()
    }
    if src_a and src_b and src_a.intersection(src_b):
        score += 2
    text_a = set(str(req_a.get("text") or "").lower().split())
    text_b = set(str(req_b.get("text") or "").lower().split())
    if text_a and text_b:
        overlap = len(text_a.intersection(text_b))
        score += min(3, overlap)
    return score


def next_supplement_conflict_id(conflicts: List[Dict[str, Any]], label: str) -> str:
    prefix = "CF-SUP" if label == "Conflict" else "NF-SUP"
    max_num = 0
    for row in conflicts or []:
        if not isinstance(row, dict):
            continue
        cid = str(row.get("id") or "").strip()
        if not cid.startswith(prefix + "-"):
            continue
        try:
            max_num = max(max_num, int(cid.rsplit("-", 1)[-1]))
        except ValueError:
            continue
    return f"{prefix}-{max_num + 1:03d}"


def supplement_uncovered_conflict_pairs(flow, artifact: Dict[str, Any]) -> Dict[str, Any]:
    requirements = [
        req for req in (artifact.get("requirements", []) or [])
        if isinstance(req, dict)
        and str(req.get("id") or "").strip()
        and str(req.get("text") or "").strip()
    ]
    if len(requirements) < 2:
        return artifact

    try:
        max_pairs = int(flow.config.get("conflict_supplement_max_pairs", 10) or 10)
    except (TypeError, ValueError):
        max_pairs = 10
    max_pairs = max(0, max_pairs)
    if max_pairs <= 0:
        return artifact

    existing_conflicts = artifact.setdefault("conflicts", [])
    covered = covered_conflict_pairs(existing_conflicts)
    candidates: List[Tuple[int, Dict[str, Any], Dict[str, Any]]] = []
    for req_a, req_b in combinations(requirements, 2):
        key = requirement_pair_key([req_a.get("id"), req_b.get("id")])
        if not key or key in covered:
            continue
        candidates.append((requirement_pair_priority(req_a, req_b), req_a, req_b))
    candidates.sort(key=lambda item: item[0], reverse=True)
    selected = candidates[:max_pairs]

    added = 0
    unresolved: List[Dict[str, str]] = []
    for _, req_a, req_b in selected:
        original_ids = [str(req_a.get("id") or "").strip(), str(req_b.get("id") or "").strip()]
        mini_artifact = {
            "requirements": [
                {"id": "SUP-P0-a", "text": str(req_a.get("text") or "").strip()},
                {"id": "SUP-P0-b", "text": str(req_b.get("text") or "").strip()},
            ],
            "conflicts": [],
            "meta": {
                "pairwise_only": True,
                "pair_count": 1,
                "pair_id_prefix": "SUP",
                "enable_all_conflict_check": False,
            },
        }
        try:
            out = flow.analyst_agent.run_conflict_detection(mini_artifact)
            rows = out.get("conflicts", []) if isinstance(out, dict) else []
            row = rows[0] if rows and isinstance(rows[0], dict) else {}
            label = str(row.get("label") or "").strip()
            if label not in {"Conflict", "Neutral"}:
                unresolved.append({"requirement_ids": ",".join(original_ids), "reason": "missing_label"})
                continue
            entry = {
                "id": next_supplement_conflict_id(existing_conflicts, label),
                "label": label,
                "description": str(row.get("description") or "補判：初始衝突辨識未覆蓋此需求 pair。").strip(),
                "requirement_ids": original_ids,
                "supplemented": True,
                "supplement_reason": "uncovered_requirement_pair",
            }
            if label == "Conflict":
                entry["conflict_type"] = str(row.get("conflict_type") or "").strip()
            existing_conflicts.append(entry)
            covered.add(requirement_pair_key(original_ids))
            added += 1
        except Exception as e:
            unresolved.append({"requirement_ids": ",".join(original_ids), "reason": str(e)})

    artifact["conflict_supplement_summary"] = {
        "enabled": True,
        "total_requirements": len(requirements),
        "covered_before": len(covered) - added,
        "uncovered_before": len(candidates),
        "selected_for_supplement": len(selected),
        "added": added,
        "unresolved_count": len(unresolved),
        "unresolved_pairs": unresolved,
    }
    flow.logger.info(
        "Conflict 補判：uncovered=%s selected=%s added=%s unresolved=%s",
        len(candidates),
        len(selected),
        added,
        len(unresolved),
    )
    return artifact


def run_init_phase(flow, artifact: Dict[str, Any]) -> Dict[str, Any]:
    rough_idea = artifact["rough_idea"]

    flow.logger.info("利害關係人識別與需求收集")
    stakeholders = artifact.get("stakeholders") or []
    if stakeholders:
        flow.logger.info(f"✓ 使用 artifact 中預載的 {len(stakeholders)} 位利害關係人")
    else:
        proposed = flow.user_agent.propose_stakeholders(rough_idea)

        max_sh = flow.config.get("max_stakeholders", 5)
        selected_indices = Collect.user_selection(proposed, max_select=max_sh)
        selected = [proposed[i]["name"] for i in selected_indices]
        flow.logger.info(f"✓ 已選擇 {len(selected)} 位利害關係人")

        stakeholders = flow.user_agent.generate_stakeholder_requirements(
            rough_idea, selected
        )
    artifact["stakeholders"] = stakeholders
    flow.user_agent.stakeholders = stakeholders
    flow.store.save_artifact(artifact)
    flow.logger.info(f"✓ {len(stakeholders)} 位利害關係人需求")

    flow.logger.info("Analyst: 需求分析")
    analysis = flow.analyst_agent.run_requirements_analyst(
        "analyze_requirements", stakeholders=stakeholders,
    )
    analyzed_requirements = [
        row for row in (analysis.get("requirements", []) if isinstance(analysis, dict) else [])
        if isinstance(row, dict) and str(row.get("text") or "").strip()
    ]
    if not analyzed_requirements:
        analyzed_requirements = build_fallback_requirements_from_stakeholders(stakeholders)
        flow.logger.warning(
            "Analyst 需求分析未產生結構化需求，已由 stakeholder 發言建立 %s 筆 unverified requirements",
            len(analyzed_requirements),
        )
    normalize_requirement_statuses(analyzed_requirements)
    initial_candidates = build_requirement_candidates_from_requirements(
        analyzed_requirements,
        candidate_source="initial_requirement_analysis",
    )
    artifact["initial_requirement_candidates"] = initial_candidates
    artifact["requirements"] = []
    initial_review = review_requirement_candidates_before_merge(
        artifact,
        initial_candidates,
        stage="initial_requirement_analysis",
        round_num=0,
        candidate_source="initial_requirement_analysis",
    )
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
    flow.store.save_artifact(artifact)

    flow.logger.info("Analyst: initial scope")
    initial_scope = flow.analyst_agent.run_requirements_analyst(
        "generate_scope", rough_idea=rough_idea, stakeholders=stakeholders,
        artifact=artifact,
    )
    if isinstance(initial_scope, dict):
        initial_scope = dict(initial_scope)
        initial_scope["version"] = 1
        initial_scope["status"] = "initial"
        initial_scope["source"] = "initial_requirement_analysis"
        artifact["scope"] = initial_scope
        flow.store.save_artifact(artifact)

    if human_setting(flow.config, "enable_elicitation", True):
        flow.logger.info("=== 隱性需求挖掘會議 ===")
        artifact = flow.meeting.run_hidden_requirement_elicitation_meeting(
            artifact, round_num=0,
        )
        if artifact.get("elicitation_candidates"):
            elicitation_review = review_requirement_candidates_before_merge(
                artifact,
                artifact.get("elicitation_candidates", []) or [],
                stage="initial_hidden_elicitation",
                round_num=0,
                candidate_source="elicitation",
            )
            merge_stats = merge_requirement_candidates(
                artifact["requirements"],
                elicitation_review["candidates"],
                source_round=0,
            )
            artifact["init_elicitation_summary"] = {
                "round": 0,
                "candidate_count": len(artifact.get("elicitation_candidates", []) or []),
                "absorbed_count": merge_stats["added"],
                "merge": merge_stats,
                "termination_reason": artifact.get("elicitation_termination_reason", ""),
            }
            flow.logger.info(
                "✓ 挖掘完成，併入 %s 筆 unverified requirements（目前需求 %s 筆）",
                merge_stats["added"],
                len(artifact["requirements"]),
            )
            flow.store.save_artifact(artifact)

    flow.logger.info("Analyst: Conflict 辨識")
    artifact = flow.analyst_agent.run_conflict_detection(artifact)
    artifact = supplement_uncovered_conflict_pairs(flow, artifact)
    flow.store.save_artifact(artifact)

    flow.logger.info("Expert: 領域研究")
    review = flow.expert_agent.run_domain_research_loop(
        artifact,
        max_iterations=read_max_iterations(flow.config, default=3),
    )
    flow.store.save_artifact(artifact)
    review_actions = review.get("actions_taken", [])
    review_issues = review.get("pending_issues", [])
    dr = artifact.get("feedback", {}).get("domain_research") or {}
    if dr and isinstance(dr, dict) and dr:
        flow.logger.info(f"✓ 領域研究完成（{len(review_actions)} 步驟）")
    else:
        flow.logger.info("領域研究完成，無結果寫入")
    if review_issues:
        for issue in review_issues:
            artifact.setdefault("open_questions", []).append(
                {
                    "from_agent": "expert",
                    "question": issue.get("description", ""),
                    "status": "pending",
                    "type": issue.get("type", "compliance_risk"),
                }
            )
        flow.logger.info(f"  Expert 標記 {len(review_issues)} 個合規風險")

    flow.logger.info("Modeler: generate System Model")
    model_data = flow.modeler_agent.generate_requirement_models(
        artifact,
        max_iterations=read_max_iterations(flow.config, default=3),
    )
    artifact["system_models"] = model_data
    flow.store.save_artifact(artifact)
    model_count = len(model_data.get("models", []))
    flow.logger.info(f"  ✓ 產生 {model_count} 張需求工程模型")
    flow.store.save_plantuml_files(model_data)

    flow.logger.info("Analyst: refine scope")
    refined_scope = flow.analyst_agent.run_requirements_analyst(
        "generate_scope", rough_idea=rough_idea, stakeholders=stakeholders,
        artifact=artifact,
    )
    if isinstance(refined_scope, dict):
        previous_scope = artifact.get("scope") if isinstance(artifact.get("scope"), dict) else {}
        refined_scope = dict(refined_scope)
        refined_scope["version"] = int((previous_scope or {}).get("version", 1) or 1) + 1
        refined_scope["status"] = "refined"
        refined_scope["source"] = "post_elicitation_scope_refinement"
        artifact["scope"] = refined_scope
    flow.store.save_artifact(artifact)

    flow.logger.info("Analyst: 草稿化")
    draft_md = flow.analyst_agent.run_requirements_analyst(
        "create_draft",
        artifact=artifact,
        draft_version=0,
        recent_decisions_limit=flow.config.get("agenda_items", 5),
    )
    flow.store.save_draft(draft_md, version=0)
    flow.logger.info(
        f"✓ Draft v0: {len(artifact['requirements'])} 條需求，{len(artifact.get('conflicts', []))} 個 Conflict"
    )

    flow.touch_artifact_meta(
        artifact,
        updated_by="flow.run_init_phase",
        round_num=0,
    )
    flow.store.save_artifact(artifact)
    return artifact
