# Initialization flow: scope, initial requirements, elicitation, conflicts, and domain research.
from typing import Any, Dict, List

from utils import Collect, meeting_setting
from agents.profile.analyst.requirements import (
    build_requirement_candidates_from_requirements,
    ensure_requirement_candidate_ids,
)


STAKEHOLDER_CATEGORIES = {
    "Primary Users",
    "System Owners & Management",
    "External Parties",
}


def selected_stakeholders(selected: List[Any]) -> List[Dict[str, Any]]:
    records: List[Dict[str, Any]] = []
    for item in selected or []:
        if isinstance(item, dict):
            name = str(item.get("name") or "").strip()
            stakeholder_type = str(item.get("type") or "").strip()
        else:
            name = str(item or "").strip()
            stakeholder_type = ""
        if not name:
            continue
        if stakeholder_type not in STAKEHOLDER_CATEGORIES:
            stakeholder_type = "Primary Users"
        records.append({"name": name, "type": stakeholder_type, "text": []})
    return records


def merge_stakeholder_inputs(
    selected_records: List[Dict[str, Any]],
    generated_rows: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    generated_by_name = {
        str(row.get("name") or "").strip(): row
        for row in generated_rows or []
        if isinstance(row, dict) and str(row.get("name") or "").strip()
    }
    merged: List[Dict[str, Any]] = []
    for base in selected_records:
        row = dict(base)
        generated = generated_by_name.get(row["name"], {})
        text = generated.get("text") if isinstance(generated, dict) else []
        if isinstance(text, str):
            text = [line.strip() for line in text.splitlines() if line.strip()]
        elif isinstance(text, list):
            text = [str(line).strip() for line in text if str(line).strip()]
        else:
            text = []
        row["text"] = text
        merged.append(row)
    return merged


def run_init_phase(flow, artifact: Dict[str, Any]) -> Dict[str, Any]:
    rough_idea = artifact["rough_idea"]

    stakeholders = artifact.get("stakeholders") or []
    if stakeholders:
        flow.logger.info(f"✓ 使用 artifact 中預載的 {len(stakeholders)} 位利害關係人")
    else:
        scenario = flow.analyst_agent.run_requirements_analyst(
            "analyze_scenario", rough_idea=rough_idea,
        )
        artifact["scenario"] = {
            "name": str((scenario or {}).get("name") or "").strip(),
            "application_type": "",
            "Category": {
                "primary_category": "",
                "subcategories": [],
            },
        }
        flow.store.save_artifact(artifact)
        flow.logger.info("✓ 初步情境分析完成")

        scenario_idea = artifact["scenario"]
        proposed = flow.user_agent.propose_stakeholders(scenario_idea)

        max_sh = flow.config.get("max_stakeholders", 5)
        selected_indices = Collect.user_selection(proposed, max_select=max_sh)
        selected = [proposed[i] for i in selected_indices]
        stakeholders = selected_stakeholders(selected)
        artifact["stakeholders"] = stakeholders
        flow.user_agent.stakeholders = stakeholders
        flow.store.save_artifact(artifact)
        flow.logger.info(f"✓ 已選擇 {len(selected)} 位利害關係人")

        generated_stakeholders = flow.user_agent.generate_stakeholder_text(
            scenario_idea,
            [row["name"] for row in stakeholders],
        )
        stakeholders = merge_stakeholder_inputs(stakeholders, generated_stakeholders)
    artifact["stakeholders"] = stakeholders
    flow.user_agent.stakeholders = stakeholders
    flow.store.save_artifact(artifact)
    flow.logger.info(f"✓ {len(stakeholders)} 位利害關係人提出需求")

    analysis = flow.analyst_agent.run_requirements_analyst(
        "analyze_requirements", stakeholders=stakeholders,
    )
    analyzed_requirements = [
        row for row in (analysis.get("requirements", []) if isinstance(analysis, dict) else [])
        if isinstance(row, dict) and str(row.get("text") or "").strip()
    ]
    if not analyzed_requirements:
        raise RuntimeError("Analyst 需求分析在 agent loop 後仍未產生結構化 requirements")
    initial_candidates = build_requirement_candidates_from_requirements(
        analyzed_requirements,
    )
    artifact["URL"] = list(initial_candidates)
    artifact["requirements"] = []
    flow.store.save_artifact(artifact)
    flow.logger.info("✓ 初始需求分析完成")

    initial_scope = flow.analyst_agent.run_requirements_analyst(
        "generate_scope",
        artifact=artifact,
    )
    if isinstance(initial_scope, dict):
        artifact["scope"] = {
            "in_scope": initial_scope.get("in_scope", []) or [],
            "out_of_scope": initial_scope.get("out_of_scope", []) or [],
        }
    flow.store.save_artifact(artifact)
    flow.logger.info("✓ 需求範圍生成完成")

    if meeting_setting(flow.config, "elicitation", True):
        flow.logger.info("=== 需求擷取會議 ===")
        artifact = flow.meeting.run_requirement_elicitation_meeting(
            artifact, round_num=0,
        )
        elicited_reqts = (artifact.get("elicitation") or {}).get("elicited_reqts", []) or []
        if elicited_reqts:
            artifact["URL"] = ensure_requirement_candidate_ids(
                list(artifact.get("URL", []) or []) + list(elicited_reqts)
            )
            flow.logger.info(
                "需求擷取會議結束 | + 候選需求池 %s 筆（目前候選 %s 筆）",
                len(elicited_reqts),
                len(artifact.get("URL", []) or []),
            )
            flow.store.save_artifact(artifact)

    flow.logger.info("=== 需求衝突辨識 ===")
    artifact = flow.analyst_agent.run_pairwise_conflict_detection(artifact)
    artifact = flow.analyst_agent.execute_group_conflict_detection(artifact)
    conflict_state = artifact.get("conflict") if isinstance(artifact.get("conflict"), dict) else {}
    conflict_items = list(conflict_state.get("pairs") or []) + list(conflict_state.get("multiple") or [])
    if conflict_items and meeting_setting(flow.config, "conflict_review", True):
        artifact = flow.meeting.run_conflict_review(artifact, round_num=1)
    flow.store.save_artifact(artifact)

    flow.logger.info("=== Expert: 領域研究 ===")
    review = flow.expert_agent.run_domain_research_loop(
        artifact,
    )
    flow.store.save_artifact(artifact)
    dr = artifact.get("feedback") if isinstance(artifact.get("feedback"), dict) else {}
    if dr and isinstance(dr, dict) and dr:
        flow.logger.info("✓ 領域研究完成")

    flow.logger.info("=== Modeler: 系統模型 ===")
    model_data = flow.modeler_agent.generate_system_models(
        artifact,
    )
    artifact["system_models"] = model_data
    flow.store.save_artifact(artifact)
    model_names = [
        str(model.get("name") or model.get("type") or "").strip()
        for model in (model_data if isinstance(model_data, list) else [])
        if isinstance(model, dict) and str(model.get("name") or model.get("type") or "").strip()
    ]
    flow.logger.info("✓ 系統模型產生完成：%s", "、".join(model_names) if model_names else "無")
    flow.store.save_plantuml_files(model_data)

    flow.logger.info("=== Analyst: 草稿化 ===")
    conflict_report_md = flow.store.load_markdown("conflict_report.md")
    draft_md = flow.analyst_agent.run_requirements_analyst(
        "create_draft",
        artifact=artifact,
        draft_version=0,
        conflict_report_md=conflict_report_md,
        meeting_record_md="",
    )
    flow.store.save_draft(draft_md, version=0)
    flow.logger.info("✓ 需求草稿已經生成完成")

    flow.touch_artifact_meta(
        artifact,
        updated_by="flow.run_init_phase",
        round_num=0,
    )
    flow.store.save_artifact(artifact)
    return artifact
