# Initialization flow: scope, initial requirements, elicitation, conflicts, and domain research.
from typing import Any, Dict

from utils import (
    Collect,
    artifact_path_non_empty,
    has_draft_payload,
    has_feedback_payload,
    has_system_models_payload,
    meeting_setting,
    require_stage_inputs,
    stage_enabled,
)
from agents.profile.user.stakeholder import merge_stakeholder_inputs, selected_stakeholders
from agents.profile.analyst.requirements import (
    attach_initial_source_ids,
    build_initial_requirement_candidates_from_stakeholders,
    build_requirement_candidates_from_requirements,
    ensure_requirement_candidate_ids,
)


def run_init_phase(flow, artifact: Dict[str, Any]) -> Dict[str, Any]:
    run_init = stage_enabled(flow.config, "init")
    if not run_init:
        flow.logger.info("跳過初始化前置")
        require_stage_inputs(flow, artifact, "init")
    else:
        rough_idea = artifact["rough_idea"]

        stakeholders = artifact.get("stakeholders") or []
        if stakeholders:
            flow.logger.info(f"✓ 使用 artifact 中預載的 {len(stakeholders)} 位利害關係人")
        else:
            proposed = flow.user_agent.propose_stakeholders(rough_idea)

            max_sh = flow.config.get("max_stakeholders", 5)
            selected = Collect.user_selection(proposed, max_select=max_sh)
            stakeholders = selected_stakeholders(selected)
            if not stakeholders:
                raise RuntimeError(
                    "未選出合法 stakeholders；需要 {'name': ..., 'type': ...} 格式"
                )
            artifact["stakeholders"] = stakeholders
            flow.user_agent.stakeholders = stakeholders
            flow.store.save_artifact(artifact)
            flow.logger.info(f"✓ 已選擇 {len(selected)} 位利害關係人")

            generated_stakeholders = flow.user_agent.write_stakeholders(
                rough_idea,
                [row["name"] for row in stakeholders],
            )
            stakeholders = merge_stakeholder_inputs(stakeholders, generated_stakeholders)
        artifact["stakeholders"] = stakeholders
        flow.user_agent.stakeholders = stakeholders
        flow.store.save_artifact(artifact)
        flow.logger.info(f"✓ {len(stakeholders)} 位利害關係人提出需求")

        if not any(row.get("text") for row in stakeholders if isinstance(row, dict)):
            raise RuntimeError("stakeholders 缺少 text；無法進行初始需求分析")

        if artifact.get("scenario"):
            pass
        else:
            scenario = flow.analyst_agent.run_requirements_analyst(
                "analyze_scenario", rough_idea=rough_idea,
            )
            artifact["scenario"] = str(scenario or "").strip()
            flow.store.save_artifact(artifact)
            flow.logger.info("✓ 初步情境分析完成")

        analysis = flow.analyst_agent.run_requirements_analyst(
            "analyze_requirements", stakeholders=stakeholders,
        )
        if isinstance(analysis, dict):
            raw_initial_requirements = analysis.get("URL")
        elif isinstance(analysis, list):
            raw_initial_requirements = analysis
        else:
            raw_initial_requirements = []
        initial_candidates = build_requirement_candidates_from_requirements(raw_initial_requirements or [])
        if not initial_candidates:
            flow.logger.warning("Analyst 初步抽取未產生 User Requirements，改用 stakeholder 原始表述建立初始 URL。")
            initial_candidates = build_initial_requirement_candidates_from_stakeholders(stakeholders)
        initial_candidates = attach_initial_source_ids(initial_candidates, stakeholders)
        if not initial_candidates:
            raise RuntimeError("Analyst 需求分析在 agent loop 後仍未產生結構化 requirements")
        artifact["URL"] = list(initial_candidates)
        flow.store.save_artifact(artifact)
        flow.logger.info("✓ 初始需求分析完成")

        initial_scope = flow.analyst_agent.run_requirements_analyst(
            "define_scope",
            artifact=artifact,
        )
        if isinstance(initial_scope, dict):
            artifact["scope"] = {
                "in_scope": initial_scope.get("in_scope", []) or [],
                "out_of_scope": initial_scope.get("out_of_scope", []) or [],
            }
        flow.store.save_artifact(artifact)
        flow.logger.info("✓ 需求範圍生成完成")

    elicitation_payload = artifact.get("elicitation") if isinstance(artifact.get("elicitation"), dict) else {}
    has_elicitation_output = bool(elicitation_payload.get("elicited_reqts")) or any(
        isinstance(row, dict) and str(row.get("source") or "").startswith("elicitation")
        for row in (artifact.get("URL", []) or [])
    )
    conflict_state = artifact.get("conflict") if isinstance(artifact.get("conflict"), dict) else {}
    has_conflict_detection_output = bool(
        conflict_state.get("pairs") or conflict_state.get("multiple")
    )

    if not stage_enabled(flow.config, "elicitation"):
        flow.logger.info("=== 需求擷取會議 ===")
        flow.logger.info("跳過需求擷取會議")
    elif has_elicitation_output:
        flow.logger.info("=== 需求擷取會議 ===")
        require_stage_inputs(flow, artifact, "elicitation")
        flow.logger.info("✓ 需求擷取會議已完成，跳過重新執行")
    elif meeting_setting(flow.config, "elicitation", True):
        flow.logger.info("=== 需求擷取會議 ===")
        require_stage_inputs(flow, artifact, "elicitation")
        artifact = flow.meeting.run_requirement_elicitation_meeting(
            artifact, round_num=0,
        )
        elicited_reqts = (artifact.get("elicitation") or {}).get("elicited_reqts", []) or []
        if elicited_reqts:
            artifact["URL"] = ensure_requirement_candidate_ids(
                list(artifact.get("URL", []) or []) + list(elicited_reqts)
            )
            artifact.setdefault("meta", {})["requirements_changed"] = True
            artifact.setdefault("meta", {})["requirements_changed_by"] = "elicitation"
            artifact.setdefault("meta", {})["requirements_changed_reason"] = "elicitation"
            flow.logger.info(
                "需求擷取會議結束 | + 候選需求池 %s 筆（目前候選 %s 筆）",
                len(elicited_reqts),
                len(artifact.get("URL", []) or []),
            )
            flow.store.save_artifact(artifact)
        flow.store.save_artifact(artifact)

    flow.logger.info("=== 需求衝突辨識 ===")
    meta = artifact.get("meta") if isinstance(artifact.get("meta"), dict) else {}
    requirements_changed = bool(meta.get("requirements_changed"))
    if not stage_enabled(flow.config, "conflict_detection"):
        flow.logger.info("跳過需求衝突辨識")
    elif has_conflict_detection_output and not requirements_changed:
        require_stage_inputs(flow, artifact, "conflict_detection")
        flow.logger.info("✓ 需求衝突辨識已完成，跳過重新執行")
    else:
        require_stage_inputs(flow, artifact, "conflict_detection")
        artifact = flow.analyst_agent.run_pairwise_conflict_detection(artifact)
        artifact = flow.analyst_agent.run_group_conflict_detection(artifact)
        artifact.setdefault("meta", {})["requirements_changed"] = False
        artifact.setdefault("meta", {})["requirements_conflicts_refreshed_by"] = "init_conflict_detection"
        artifact.setdefault("meta", {})["requirements_conflicts_refreshed_round"] = 0
    conflict_state = artifact.get("conflict") if isinstance(artifact.get("conflict"), dict) else {}
    conflict_items = list(conflict_state.get("pairs") or []) + list(conflict_state.get("multiple") or [])
    if (
        conflict_items
        and meeting_setting(flow.config, "conflict_review", True)
        and stage_enabled(flow.config, "conflict_detection")
    ):
        artifact = flow.meeting.run_conflict_review(artifact, round_num=1)
    flow.store.save_artifact(artifact)

    flow.logger.info("=== Expert: 領域研究 ===")
    ran_domain_research = False
    reused_domain_research = False
    if not stage_enabled(flow.config, "domain_research"):
        flow.logger.info("跳過領域研究")
    elif has_feedback_payload(artifact) and artifact_path_non_empty(flow, "feedback.json"):
        flow.logger.info("✓ 領域研究已存在，跳過重新生成")
        reused_domain_research = True
    else:
        require_stage_inputs(flow, artifact, "domain_research")
        flow.expert_agent.run_domain_research_loop(
            artifact,
        )
        ran_domain_research = True
    flow.store.save_artifact(artifact)
    dr = artifact.get("feedback") if isinstance(artifact.get("feedback"), dict) else {}
    if ran_domain_research and not has_feedback_payload(artifact):
        raise RuntimeError("Expert domain research 在 agent loop 後仍未產生有效 feedback")
    if (ran_domain_research or reused_domain_research) and dr and isinstance(dr, dict) and dr:
        flow.logger.info("✓ 領域研究完成")

    flow.logger.info("=== Modeler: 系統模型 ===")
    if not stage_enabled(flow.config, "system_model"):
        flow.logger.info("跳過系統模型")
        model_data = artifact.get("system_models", [])
    elif has_system_models_payload(artifact) and artifact_path_non_empty(flow, "system_models.json"):
        model_data = artifact.get("system_models", [])
        flow.logger.info("✓ 系統模型已存在，跳過重新生成")
    else:
        require_stage_inputs(flow, artifact, "system_model")
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
    if stage_enabled(flow.config, "system_model"):
        flow.store.save_plantuml_files(model_data)
        artifact["system_models"] = model_data
        flow.store.save_artifact(artifact)

    flow.logger.info("=== Analyst: 草稿化 ===")
    if not stage_enabled(flow.config, "draft"):
        flow.logger.info("跳過草稿化")
    elif has_draft_payload(flow):
        flow.logger.info("✓ 需求草稿已存在，跳過重新生成")
    else:
        require_stage_inputs(flow, artifact, "draft")
        conflict_report_md = flow.store.load_markdown("conflict_report.md")
        draft_md = flow.analyst_agent.run_requirements_analyst(
            "create_draft",
            artifact=artifact,
            draft_version=0,
            conflict_report_md=conflict_report_md,
            artifact_dir=getattr(flow.store, "artifact_dir", None),
        )
        flow.store.save_draft(draft_md, version=0)
        flow.logger.info("✓ 需求草稿已經生成完成")

    flow.touch_artifact_meta(artifact, round_num=0)
    flow.store.save_artifact(artifact)
    return artifact
