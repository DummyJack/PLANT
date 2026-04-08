from typing import Any, Dict

from utils import Collect, read_max_iterations


def run_init_phase(flow, artifact: Dict[str, Any]) -> Dict[str, Any]:
    rough_idea = artifact["rough_idea"]

    flow.logger.info("利害關係人識別與需求收集")
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
    artifact["requirements"] = analysis["requirements"]
    flow.store.save_artifact(artifact)

    flow.logger.info("Analyst: Conflict 辨識")
    artifact = flow.analyst_agent.run_conflict_detection(artifact)
    flow.store.save_artifact(artifact)

    flow.logger.info("Expert: 領域研究")
    review = flow.expert_agent.run_review_loop(
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

    flow.logger.info("Modeler: 初步建模")
    model_data = flow.modeler_agent.generate_system_model(
        artifact["requirements"],
        artifact["stakeholders"],
        max_iterations=read_max_iterations(flow.config, default=3),
    )
    artifact["system_models"] = model_data
    flow.store.save_artifact(artifact)
    model_count = len(model_data.get("models", []))
    flow.logger.info(f"  ✓ 產生 {model_count} 張 UML 圖")
    flow.store.save_plantuml_files(model_data)

    flow.logger.info("Analyst: scope")
    artifact["scope"] = flow.analyst_agent.run_requirements_analyst(
        "generate_scope", rough_idea=rough_idea, stakeholders=stakeholders,
        artifact=artifact,
    )
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

    flow._touch_artifact_meta(
        artifact,
        updated_by="flow.run_init_phase",
        round_num=0,
    )
    flow.store.save_artifact(artifact)
    return artifact
