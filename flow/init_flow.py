# Handles init flow logic for project flow orchestration and stage execution.
import re
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
from agents.profile.user.stakeholder import (
    merge_stakeholder_text,
    normalize_stakeholder_text,
    parse_selection,
)
from storage.requirements import (
    attach_initial_source_ids,
    build_initial_requirement_candidates_from_stakeholders,
    build_requirement_candidates_from_requirements,
    ensure_requirement_candidate_ids,
    requirement_dedupe_key,
)
from flow.meeting.conflict_review import save_conflict_report
from server.services.run_checkpoint import record_run_checkpoint

SUPPORTED_REFERENCE_EXTS = {
    ".pdf",
    ".docx",
    ".xlsx",
    ".pptx",
    ".txt",
    ".md",
    ".json",
    ".csv",
}


def _checkpoint_step(
    flow,
    *,
    stage_id: str,
    step_id: str,
    agent: str = "",
    action: str = "",
) -> None:
    run_id = str(getattr(flow, "run_id", "") or "")
    if not run_id:
        return
    record_run_checkpoint(
        flow.store,
        run_id=run_id,
        status="running",
        stage_id=stage_id,
        step_id=step_id,
        agent=agent,
        action=action,
    )


def emit_requirement_deltas(flow, stage_id: str, step_id: str, rows: list[Dict[str, Any]]) -> None:
    for row in rows:
        if not isinstance(row, dict):
            continue
        req_id = str(row.get("id") or "").strip()
        text = str(row.get("text") or row.get("description") or "").strip()
        if not text:
            continue
        flow.logger.step_delta(
            stage_id,
            step_id,
            {
                "id": req_id,
                "title": req_id or "候選需求",
                "text": text,
            },
            delta_type="requirement",
            agent="analyst",
        )


def emit_scope_delta(flow, scope: Dict[str, Any]) -> None:
    if not isinstance(scope, dict):
        return
    for key, title in (("in_scope", "範圍內"), ("out_of_scope", "範圍外")):
        values = scope.get(key) or []
        if not values:
            continue
        flow.logger.step_delta(
            "init",
            "init.generate_scope",
            {
                "title": title,
                "text": "\n".join(f"- {value}" for value in values),
            },
            delta_type="scope",
            agent="analyst",
        )


def emit_model_deltas(flow, rows: list[Dict[str, Any]]) -> None:
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        title = str(row.get("name") or row.get("type") or "系統模型").strip()
        body = str(row.get("description") or row.get("plantuml") or "").strip()
        flow.logger.step_delta(
            "system_model",
            "system_model.generate_models",
            {"title": title, "text": body or title},
            delta_type="model",
            agent="modeler",
        )


def emit_markdown_section_deltas(
    flow,
    stage_id: str,
    step_id: str,
    markdown: str,
    *,
    agent: str,
    max_sections: int = 8,
) -> None:
    text = str(markdown or "").strip()
    if not text:
        return
    matches = list(re.finditer(r"(?m)^(#{1,4})\s+(.+?)\s*$", text))
    if not matches:
        flow.logger.step_delta(
            stage_id,
            step_id,
            {"title": "內容預覽", "text": text[:1200]},
            delta_type="markdown_section",
            agent=agent,
        )
        return
    for index, match in enumerate(matches[:max_sections]):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        heading = match.group(2).strip()
        body = text[start:end].strip()
        flow.logger.step_delta(
            stage_id,
            step_id,
            {"title": heading, "markdown": body[:1600]},
            delta_type="markdown_section",
            agent=agent,
        )


def apply_stakeholder_statement_review(
    stakeholders: list[Dict[str, Any]],
    review: Dict[str, Any],
) -> list[Dict[str, Any]]:
    if not isinstance(review, dict):
        return stakeholders
    action = str(review.get("action") or "").strip()
    if action != "direct_edit":
        return stakeholders

    edited = review.get("stakeholders")
    if isinstance(edited, list) and edited:
        by_name = {
            str(row.get("name") or "").strip(): row
            for row in edited
            if isinstance(row, dict) and str(row.get("name") or "").strip()
        }
        revised = []
        for row in stakeholders:
            name = str(row.get("name") or "").strip()
            source = by_name.get(name)
            if not source:
                revised.append(row)
                continue
            next_row = dict(row)
            next_row["text"] = source.get("text") or []
            revised.append(next_row)
        return normalize_stakeholder_text(revised)

    text = str(review.get("stakeholder_text") or "").strip()
    if not text:
        return stakeholders
    revised = []
    for row in stakeholders:
        next_row = dict(row)
        next_row["text"] = [{"text": line.strip()} for line in text.splitlines() if line.strip()]
        revised.append(next_row)
    return normalize_stakeholder_text(revised)


def requirements_review_feedback(review: Dict[str, Any]) -> str:
    if not isinstance(review, dict):
        return ""
    feedback = str(review.get("human_decision") or "").strip()
    selection_comment = review.get("selection_comment")
    if isinstance(selection_comment, dict):
        selected_text = str(selection_comment.get("selected_text") or "").strip()
        comment = str(selection_comment.get("comment") or "").strip()
        if selected_text or comment:
            feedback = "\n".join(
                part
                for part in [
                    feedback,
                    f"選取內容：{selected_text}" if selected_text else "",
                    f"局部看法：{comment}" if comment else "",
                ]
                if part
            )
    return feedback.strip()


def domain_research_review_feedback(review: Dict[str, Any]) -> str:
    if not isinstance(review, dict):
        return ""
    return str(review.get("human_decision") or "").strip()


def domain_research_review_references(review: Dict[str, Any], project_id: str) -> list[str]:
    if not isinstance(review, dict):
        return []
    rows = review.get("referenced_files")
    if not isinstance(rows, list):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        name = str(row.get("name") or "").strip()
        if not name:
            raw_path = str(row.get("path") or "").strip()
            name = raw_path.rsplit("/", 1)[-1]
        if not name or name in seen:
            continue
        seen.add(name)
        out.append(f"{project_id}/{name}" if project_id else name)
    return out


def requirements_from_analysis(
    flow,
    stakeholders: list[Dict[str, Any]],
    *,
    feedback: str = "",
) -> list[Dict[str, Any]]:
    analysis_stakeholders = stakeholders
    if feedback:
        analysis_stakeholders = [
            {
                **row,
                "text": [
                    {
                        "id": str(item.get("id") or "").strip(),
                        "text": (
                            f"{str(item.get('text') or '').strip()}\n\n"
                            f"使用者對初始需求分析的建議：\n{feedback}"
                        ).strip(),
                    }
                    if isinstance(item, dict)
                    else {
                        "id": "",
                        "text": f"{str(item or '').strip()}\n\n使用者對初始需求分析的建議：\n{feedback}".strip(),
                    }
                    for item in (row.get("text") or [])
                ],
            }
            for row in stakeholders
            if isinstance(row, dict)
        ]
    analysis = flow.analyst_agent.run_requirements_analyst(
        "analyze_requirements", stakeholders=analysis_stakeholders,
    )
    raw_initial_requirements = analysis if isinstance(analysis, list) else []
    initial_candidates = build_requirement_candidates_from_requirements(raw_initial_requirements or [])
    if not initial_candidates:
        flow.logger.warning("Analyst 初步抽取未產生 User Requirements，改用 stakeholder 原始表述建立初始 URL。")
        initial_candidates = build_initial_requirement_candidates_from_stakeholders(stakeholders)
    return attach_initial_source_ids(initial_candidates, stakeholders)


def feedback_covered_url_ids(artifact: Dict[str, Any]) -> set[str]:
    feedback = artifact.get("feedback") if isinstance(artifact.get("feedback"), dict) else {}
    covered: set[str] = set()
    for section in ("findings", "constraints", "risks", "recommendations"):
        for item in feedback.get(section) or []:
            if not isinstance(item, dict):
                continue
            covered.update(
                str(value).strip()
                for value in (item.get("related_requirement_ids") or [])
                if str(value).strip().startswith("URL-")
            )
    return covered


def feedback_covers_current_urls(artifact: Dict[str, Any]) -> bool:
    url_ids = {
        str(row.get("id") or "").strip()
        for row in (artifact.get("URL") or [])
        if isinstance(row, dict)
        and str(row.get("id") or "").strip()
        and str(row.get("status") or "").strip().lower() not in {"removed", "inactive", "rejected"}
    }
    if not url_ids:
        return False
    return url_ids.issubset(feedback_covered_url_ids(artifact))


def merge_elicited_requirements(flow, artifact: Dict[str, Any]) -> bool:
    elicited_reqts = (artifact.get("elicitation") or {}).get("elicited_reqts", []) or []
    if not elicited_reqts:
        return False

    current = [row for row in (artifact.get("URL", []) or []) if isinstance(row, dict)]
    seen = {
        requirement_dedupe_key(str(row.get("text") or ""))
        for row in current
        if str(row.get("text") or "").strip()
    }
    additions = []
    for row in elicited_reqts:
        if not isinstance(row, dict):
            continue
        text = str(row.get("text") or "").strip()
        key = requirement_dedupe_key(text)
        if not text or not key or key in seen:
            continue
        additions.append(row)
        seen.add(key)
    if not additions:
        return False

    artifact["URL"] = ensure_requirement_candidate_ids(current + additions)
    artifact.setdefault("meta", {})["requirements_changed"] = True
    artifact.setdefault("meta", {})["requirements_changed_by"] = "elicitation"
    artifact.setdefault("meta", {})["requirements_changed_reason"] = "elicitation"
    flow.logger.info(
        "需求擷取會議結束 | + 候選需求池 %s 筆（目前候選 %s 筆）",
        len(additions),
        len(artifact.get("URL", []) or []),
    )
    flow.store.save_artifact(artifact)
    return True


def run_init_phase(flow, artifact: Dict[str, Any]) -> Dict[str, Any]:
    run_init = stage_enabled(flow.config, "init")
    if not run_init:
        flow.logger.info("跳過初始化前置")
        require_stage_inputs(flow, artifact, "init")
    else:
        rough_idea = artifact["rough_idea"]

        stakeholders = artifact.get("stakeholders") or []
        if stakeholders:
            flow.logger.step_started(
                "init",
                "init.suggest_stakeholders",
                "讀取利害關係人",
                agent="user",
                message="正在讀取既有利害關係人",
            )
            stakeholders = normalize_stakeholder_text(stakeholders)
            artifact["stakeholders"] = stakeholders
            flow.logger.info(f"✓ 使用 artifact 中預載的 {len(stakeholders)} 位利害關係人")
            flow.logger.step_completed(
                "init",
                "init.suggest_stakeholders",
                "讀取利害關係人",
                agent="user",
                message=f"已讀取 {len(stakeholders)} 位利害關係人",
            )
        else:
            flow.logger.step_started(
                "init",
                "init.suggest_stakeholders",
                "產生利害關係人",
                agent="user",
            )
            proposed = flow.user_agent.suggest_stakeholders(rough_idea)

            max_sh = flow.config.get("max_stakeholders", 5)
            selected = Collect.user_selection(proposed, max_select=max_sh)
            stakeholders = parse_selection(selected)
            stakeholders = normalize_stakeholder_text(stakeholders)
            if not stakeholders:
                raise RuntimeError(
                    "未選出合法 stakeholders；需要 {'name': ..., 'type': ...} 格式"
                )
            artifact["stakeholders"] = stakeholders
            flow.user_agent.stakeholders = stakeholders
            flow.store.save_artifact(artifact)
            flow.logger.info(f"✓ 已選擇 {len(selected)} 位利害關係人")
            flow.logger.step_completed(
                "init",
                "init.suggest_stakeholders",
                "產生利害關係人",
                agent="user",
                message=f"已選擇 {len(selected)} 位利害關係人",
            )

            flow.logger.step_started(
                "init",
                "init.write_stakeholder_text",
                "整理利害關係人需求",
                agent="user",
                message="發言中 ...",
            )
            generated_stakeholders = flow.user_agent.write_stakeholder_text(
                rough_idea,
                [row["name"] for row in stakeholders],
            )
            stakeholders = merge_stakeholder_text(stakeholders, generated_stakeholders)
        while True:
            artifact["stakeholders"] = stakeholders
            flow.user_agent.stakeholders = stakeholders
            flow.store.save_artifact(artifact)

            review = Collect.stakeholder_statement_review(stakeholders)
            action = str((review or {}).get("action") or "approve").strip()
            artifact.setdefault("stakeholder_statement_reviews", []).append(review)
            artifact["stakeholder_statement_review"] = review

            if action == "approve":
                break
            if action == "direct_edit":
                stakeholders = apply_stakeholder_statement_review(stakeholders, review)
                break

            feedback = str((review or {}).get("human_decision") or "").strip()
            selection_comment = (review or {}).get("selection_comment")
            if isinstance(selection_comment, dict):
                selected_text = str(selection_comment.get("selected_text") or "").strip()
                comment = str(selection_comment.get("comment") or "").strip()
                if selected_text or comment:
                    feedback = "\n".join(
                        part
                        for part in [
                            feedback,
                            f"選取內容：{selected_text}" if selected_text else "",
                            f"局部看法：{comment}" if comment else "",
                        ]
                        if part
                    )
            if not feedback:
                break

            flow.logger.step_started(
                "init",
                "init.write_stakeholder_text",
                "根據 Human Decision 修正利害關係人需求",
                agent="user",
                message="已收到回饋，更新中 ...",
            )
            generated_stakeholders = flow.user_agent.write_stakeholder_text(
                f"{rough_idea}\n\nHuman Decision:\n{feedback}",
                [row["name"] for row in stakeholders],
            )
            stakeholders = merge_stakeholder_text(stakeholders, generated_stakeholders)
            break

        artifact["stakeholders"] = stakeholders
        flow.user_agent.stakeholders = stakeholders
        flow.store.save_artifact(artifact)

        flow.logger.info(f"✓ {len(stakeholders)} 位利害關係人提出需求")
        flow.logger.step_completed(
            "init",
            "init.write_stakeholder_text",
            "整理利害關係人需求",
            agent="user",
            message=f"{len(stakeholders)} 位利害關係人提出需求",
        )

        if not any(row.get("text") for row in stakeholders if isinstance(row, dict)):
            raise RuntimeError("stakeholders 缺少 text；無法進行初始需求分析")

        if artifact.get("scenario"):
            pass
        else:
            flow.logger.step_started(
                "init",
                "init.analyze_scenario",
                "分析初始情境",
                agent="analyst",
                message="正在分析系統目標與使用情境",
            )
            scenario = flow.analyst_agent.run_requirements_analyst(
                "analyze_scenario", rough_idea=rough_idea,
            )
            artifact["scenario"] = str(scenario or "").strip()
            flow.store.save_artifact(artifact)
            flow.logger.info("✓ 初步情境分析完成")
            flow.logger.step_completed(
                "init",
                "init.analyze_scenario",
                "分析初始情境",
                agent="analyst",
                message="初步情境分析完成",
            )

        flow.logger.step_started(
            "init",
            "init.analyze_requirements",
            "擷取初始需求",
            agent="analyst",
            message="正在從利害關係人描述中整理候選需求",
        )
        initial_candidates = requirements_from_analysis(flow, stakeholders)
        if not initial_candidates:
            raise RuntimeError("Analyst 需求分析在 agent loop 後仍未產生結構化 requirements")
        artifact["URL"] = list(initial_candidates)
        flow.store.save_artifact(artifact)
        emit_requirement_deltas(flow, "init", "init.analyze_requirements", list(initial_candidates))
        flow.logger.step_completed(
            "init",
            "init.analyze_requirements",
            "初始需求分析",
            agent="analyst",
            output_path="artifact/requirements.json",
        )
        flow.logger.artifact_created(
            "init",
            "init.analyze_requirements",
            "初始需求已產生",
            "artifact/requirements.json",
        )

        review = Collect.requirements_review(list(initial_candidates))
        action = str((review or {}).get("action") or "approve").strip()
        artifact.setdefault("requirements_reviews", []).append(review)
        artifact["requirements_review"] = review
        if action != "approve":
            feedback = requirements_review_feedback(review)
            if feedback:
                flow.logger.step_started(
                    "init",
                    "init.analyze_requirements_review",
                    "根據使用者建議修正初始需求",
                    agent="analyst",
                    message="已收到回饋，更新中 ...",
                )
                revised_candidates = requirements_from_analysis(
                    flow,
                    stakeholders,
                    feedback=feedback,
                )
                if revised_candidates:
                    artifact["URL"] = list(revised_candidates)
                    flow.store.save_artifact(artifact)
                    emit_requirement_deltas(
                        flow,
                        "init",
                        "init.analyze_requirements_review",
                        list(revised_candidates),
                    )
                    flow.logger.step_completed(
                        "init",
                        "init.analyze_requirements_review",
                        "初始需求修正",
                        agent="analyst",
                        output_path="artifact/requirements.json",
                    )
                else:
                    flow.logger.warning("需求分析建議未產生可寫入的 User Requirements，保留原始初始需求。")

        flow.logger.step_started(
            "init",
            "init.generate_scope",
            "產生需求範圍",
            agent="analyst",
            message="正在定義 in-scope 與 out-of-scope",
        )
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
        emit_scope_delta(flow, artifact.get("scope", {}))
        flow.logger.step_completed(
            "init",
            "init.generate_scope",
            "需求範圍",
            agent="analyst",
            output_path="artifact/scope.json",
        )
        flow.logger.artifact_created(
            "init",
            "init.generate_scope",
            "需求範圍已產生",
            "artifact/scope.json",
        )

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
        flow.logger.stage_started("elicitation", "需求擷取會議")
        flow.logger.info("=== 需求擷取會議 ===")
        flow.logger.info("跳過需求擷取會議")
        flow.logger.stage_completed("elicitation", "需求擷取會議", message="需求擷取會議已跳過")
    elif has_elicitation_output:
        flow.logger.stage_started("elicitation", "需求擷取會議")
        flow.logger.info("=== 需求擷取會議 ===")
        require_stage_inputs(flow, artifact, "elicitation")
        merge_elicited_requirements(flow, artifact)
        flow.logger.info("✓ 需求擷取會議已完成，跳過重新執行")
        flow.logger.stage_completed("elicitation", "需求擷取會議", message="需求擷取會議已完成")
    elif meeting_setting(flow.config, "elicitation", True):
        flow.logger.stage_started("elicitation", "需求擷取會議")
        flow.logger.info("=== 需求擷取會議 ===")
        require_stage_inputs(flow, artifact, "elicitation")
        flow.logger.step_started(
            "elicitation",
            "elicitation.run_meeting",
            "執行需求擷取會議",
            agent="mediator",
            message="規劃中 ...",
        )
        artifact = flow.meeting.run_elicitation(
            artifact, round_num=0,
        )
        flow.logger.step_started(
            "elicitation",
            "elicitation.merge_requirements",
            "需求分析",
            agent="analyst",
            message="正在把擷取結果合併到候選需求池",
        )
        merge_elicited_requirements(flow, artifact)
        emit_requirement_deltas(
            flow,
            "elicitation",
            "elicitation.merge_requirements",
            (artifact.get("elicitation") or {}).get("elicited_reqts", []) or [],
        )
        flow.store.save_artifact(artifact)
        flow.logger.step_completed(
            "elicitation",
            "elicitation.merge_requirements",
            "需求分析",
            agent="analyst",
            output_path="artifact/requirements.json",
        )
        flow.logger.stage_completed("elicitation", "需求擷取會議")

    flow.logger.stage_started("conflict_detection", "需求衝突辨識")
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
        flow.logger.step_started(
            "conflict_detection",
            "conflict_detection.detect_pairs",
            "比對需求衝突",
            agent="analyst",
            message="正在檢查兩兩衝突 ...",
        )
        artifact = flow.analyst_agent.detect_pair_conflicts(artifact)
        flow.logger.step_completed(
            "conflict_detection",
            "conflict_detection.detect_pairs",
            "檢查兩兩需求衝突",
            agent="analyst",
            message="檢查兩兩需求衝突完成",
        )
        flow.logger.step_started(
            "conflict_detection",
            "conflict_detection.detect_groups",
            "檢查多需求衝突",
            agent="analyst",
            message="正在檢查多需求衝突",
        )
        artifact = flow.analyst_agent.detect_group_conflicts(artifact)
        flow.logger.step_completed(
            "conflict_detection",
            "conflict_detection.detect_groups",
            "檢查多需求衝突",
            agent="analyst",
        )
        artifact.setdefault("meta", {})["requirements_changed"] = False
        artifact.setdefault("meta", {})["conflict_refresh_by"] = "init_conflict_detection"
        artifact.setdefault("meta", {})["conflict_refresh_round"] = 0
        save_conflict_report(flow.meeting, artifact, round_num=0)
    conflict_state = artifact.get("conflict") if isinstance(artifact.get("conflict"), dict) else {}
    conflict_items = list(conflict_state.get("pairs") or []) + list(conflict_state.get("multiple") or [])
    if (
        conflict_items
        and meeting_setting(flow.config, "conflict_review", True)
        and stage_enabled(flow.config, "conflict_detection")
    ):
        flow.logger.stage_started("conflict_review", "衝突審查")
        flow.logger.step_started(
            "conflict_review",
            "conflict_review.run_review",
            "審查需求衝突",
            agent="mediator",
        )
        artifact = flow.meeting.run_conflict_review(artifact, round_num=0)
        flow.logger.step_completed(
            "conflict_review",
            "conflict_review.run_review",
            "審查需求衝突",
            agent="mediator",
        )
        flow.logger.stage_completed("conflict_review", "衝突審查")
    flow.store.save_artifact(artifact)
    flow.logger.stage_completed("conflict_detection", "需求衝突辨識")

    flow.logger.stage_started("research_domain", "領域研究")
    flow.logger.info("=== Expert: 領域研究 ===")
    ran_research_domain = False
    reused_research_domain = False
    meta = artifact.setdefault("meta", {})
    research_domain_completed = bool(meta.get("research_domain_completed"))
    feedback_covers_urls = feedback_covers_current_urls(artifact)
    if not stage_enabled(flow.config, "research_domain"):
        flow.logger.info("跳過領域研究")
    else:
        references = []
        project_id = str(getattr(flow.store, "project_id", "") or "").strip()
        references_dir = flow.store.base_dir / "doc" / project_id if project_id else None
        if references_dir and references_dir.exists():
            references = [
                {"name": path.name, "size": path.stat().st_size}
                for path in sorted(references_dir.iterdir())
                if path.is_file() and path.suffix.lower() in SUPPORTED_REFERENCE_EXTS
            ]
        _checkpoint_step(
            flow,
            stage_id="research_domain",
            step_id="research_domain.review",
            agent="expert",
            action="review_domain_research_inputs",
        )
        review = Collect.domain_research_review(references)
        artifact.setdefault("domain_research_reviews", []).append(review)
        artifact["domain_research_review"] = review
        feedback = domain_research_review_feedback(review)
        referenced_files = domain_research_review_references(
            review,
            project_id,
        )
        if feedback or referenced_files:
            meta = artifact.get("meta") if isinstance(artifact.get("meta"), dict) else {}
            if feedback:
                meta["domain_research_user_guidance"] = feedback
            if referenced_files:
                meta["attached_references"] = referenced_files
                meta["domain_research_referenced_files"] = referenced_files
            artifact["meta"] = meta
            flow.store.save_artifact(artifact)
        research_domain_completed = bool(meta.get("research_domain_completed"))
        feedback_covers_urls = feedback_covers_current_urls(artifact)
        if (
            not feedback
            and not referenced_files
            and has_feedback_payload(artifact)
            and (research_domain_completed or feedback_covers_urls)
        ):
            if feedback_covers_urls:
                meta["research_domain_completed"] = True
                meta["research_domain_coverage"] = "covered_current_urls"
                artifact["meta"] = meta
                flow.store.save_artifact(artifact)
            flow.logger.info("✓ 領域研究已存在，跳過重新生成")
            reused_research_domain = True
        elif feedback or referenced_files:
            meta.pop("research_domain_completed", None)
            meta.pop("research_domain_coverage", None)
            artifact["meta"] = meta
            flow.store.save_artifact(artifact)
        require_stage_inputs(flow, artifact, "research_domain")
        if not reused_research_domain:
            _checkpoint_step(
                flow,
                stage_id="research_domain",
                step_id="research_domain.research",
                agent="expert",
                action="run_research_loop",
            )
            flow.logger.step_started(
                "research_domain",
                "research_domain.research",
                "執行領域研究",
                agent="expert",
                message="尋找中 ...",
            )
            flow.expert_agent.run_research_loop(
                artifact,
            )
            ran_research_domain = True
            if has_feedback_payload(artifact):
                artifact.setdefault("meta", {})["research_domain_completed"] = True
    flow.store.save_artifact(artifact)
    dr = artifact.get("feedback") if isinstance(artifact.get("feedback"), dict) else {}
    if ran_research_domain and not has_feedback_payload(artifact):
        raise RuntimeError("Expert domain research 在 agent loop 後仍未產生有效 feedback")
    if (ran_research_domain or reused_research_domain) and dr and isinstance(dr, dict) and dr:
        flow.logger.step_completed(
            "research_domain",
            "research_domain.generate_feedback",
            "領域研究",
            agent="expert",
            output_path="artifact/feedback.json",
        )
        flow.logger.artifact_created(
            "research_domain",
            "research_domain.generate_feedback",
            "領域研究結果已產生",
            "artifact/feedback.json",
        )
    flow.logger.stage_completed("research_domain", "領域研究")

    flow.logger.stage_started("system_model", "系統模型")
    flow.logger.info("=== Modeler: 系統模型 ===")
    generated_system_models = False
    if not stage_enabled(flow.config, "system_model"):
        flow.logger.info("跳過系統模型")
        model_data = artifact.get("system_models", [])
    elif has_system_models_payload(artifact) and artifact_path_non_empty(flow, "system_models.json"):
        model_data = artifact.get("system_models", [])
        flow.logger.info("✓ 系統模型已存在，跳過重新生成")
    else:
        require_stage_inputs(flow, artifact, "system_model")
        _checkpoint_step(
            flow,
            stage_id="system_model",
            step_id="system_model.generate_models",
            agent="modeler",
            action="generate_system_models",
        )
        flow.logger.step_started(
            "system_model",
            "system_model.generate_models",
            "產生系統模型",
            agent="modeler",
            message="生成中 ...",
        )
        model_data = flow.modeler_agent.generate_system_models(
            artifact,
        )
        artifact["system_models"] = model_data
        generated_system_models = True
        flow.store.save_artifact(artifact)
        emit_model_deltas(flow, model_data)
    model_names = [
        str(model.get("name") or model.get("type") or "").strip()
        for model in (model_data if isinstance(model_data, list) else [])
        if isinstance(model, dict) and str(model.get("name") or model.get("type") or "").strip()
    ]
    flow.logger.step_completed(
        "system_model",
        "system_model.generate_models",
        "系統模型",
        agent="modeler",
        message="、".join(model_names) if model_names else "系統模型",
        output_path="artifact/system_models.json",
    )
    flow.logger.artifact_created(
        "system_model",
        "system_model.generate_models",
        "系統模型已產生",
        "artifact/system_models.json",
    )
    if generated_system_models:
        flow.store.save_plantuml_files(model_data)
        artifact["system_models"] = model_data
        flow.store.save_artifact(artifact)
    flow.logger.stage_completed("system_model", "系統模型")

    flow.logger.stage_started("draft", "草稿化")
    flow.logger.info("=== Analyst: 草稿化 ===")
    if not stage_enabled(flow.config, "draft"):
        flow.logger.info("跳過草稿化")
    elif has_draft_payload(flow):
        flow.logger.info("✓ 需求草稿已存在，跳過重新生成")
    else:
        require_stage_inputs(flow, artifact, "draft")
        _checkpoint_step(
            flow,
            stage_id="draft",
            step_id="draft.create_draft",
            agent="analyst",
            action="create_draft",
        )
        flow.logger.step_started(
            "draft",
            "draft.create_draft",
            "建立需求草稿",
            agent="analyst",
            message="生成中 ...",
        )
        draft_md = flow.analyst_agent.run_requirements_analyst(
            "create_draft",
            artifact=artifact,
            draft_version=0,
            artifact_dir=getattr(flow.store, "artifact_dir", None),
        )
        flow.store.save_draft(draft_md, version=0)
        emit_markdown_section_deltas(
            flow,
            "draft",
            "draft.create_draft",
            draft_md,
            agent="analyst",
        )
        flow.logger.step_completed(
            "draft",
            "draft.create_draft",
            "Draft v0",
            agent="analyst",
            output_path="artifact/drafts/draft_v0.md",
        )
        flow.logger.artifact_created(
            "draft",
            "draft.create_draft",
            "Draft v0 已產生",
            "artifact/drafts/draft_v0.md",
        )
    flow.logger.stage_completed("draft", "草稿化")

    flow.touch_artifact_meta(artifact, round_num=0)
    flow.store.save_artifact(artifact)
    return artifact
