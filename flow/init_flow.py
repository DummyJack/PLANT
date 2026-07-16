# Handles init flow logic for project flow orchestration and stage execution.
import hashlib
import json
import re
from typing import Any, Dict, List, Optional

from utils import (
    artifact_path_non_empty,
    force_regenerate_output,
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
from agents.profile.analyst.validation import scope_payload
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

TARGET_MENTION_RE = re.compile(
    r"(?<!\S)@((?:URL|REQ|SM|CR|ST)-[A-Za-z0-9_.:-]+|R\d+-M\d+)",
    re.IGNORECASE,
)

INIT_RESUME_STAGE_ORDER = [
    "init",
    "elicitation",
    "conflict_detection",
    "research_domain",
    "system_model",
    "draft",
]


def upstream_requirements_signature(artifact: Dict[str, Any]) -> str:
    """Return a stable signature for inputs consumed by downstream stages."""
    payload = {
        "rough_idea": artifact.get("rough_idea") or "",
        "scenario": artifact.get("scenario") or "",
        "stakeholders": artifact.get("stakeholders") or [],
        "URL": artifact.get("URL") or [],
        "requirements": artifact.get("requirements") or [],
        "scope": artifact.get("scope") or {"in_scope": [], "out_of_scope": []},
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def merge_reference_paths(*groups: List[str]) -> List[str]:
    rows: List[str] = []
    seen: set[str] = set()
    for group in groups:
        for value in group or []:
            text = str(value or "").strip()
            if not text or text in seen:
                continue
            rows.append(text)
            seen.add(text)
    return rows


def resolve_domain_research_review(
    review: Dict[str, Any],
    run_referenced_files: List[str],
    project_id: str,
) -> tuple[str, List[str]]:
    action = str((review or {}).get("action") or "approve").strip()
    if action == "approve":
        return "", merge_reference_paths(run_referenced_files)
    return (
        domain_research_review_feedback(review),
        merge_reference_paths(
            run_referenced_files,
            domain_research_review_references(review, project_id),
        ),
    )


def init_resume_stage(artifact: Dict[str, Any]) -> str:
    meta = artifact.get("meta") if isinstance(artifact.get("meta"), dict) else {}
    checkpoint = (
        meta.get("last_resume_checkpoint")
        if isinstance(meta.get("last_resume_checkpoint"), dict)
        else {}
    )
    stage_id = str(checkpoint.get("stage_id") or "").strip()
    return stage_id if stage_id in INIT_RESUME_STAGE_ORDER else ""


def skip_before_resume_stage(artifact: Dict[str, Any], stage_id: str) -> bool:
    resume_stage = init_resume_stage(artifact)
    if not resume_stage:
        return False
    try:
        return INIT_RESUME_STAGE_ORDER.index(stage_id) < INIT_RESUME_STAGE_ORDER.index(resume_stage)
    except ValueError:
        return False


def has_domain_research_completion_marker(artifact: Dict[str, Any]) -> bool:
    feedback = artifact.get("feedback") if isinstance(artifact.get("feedback"), dict) else {}
    return str(feedback.get("status") or "").strip() == "no_applicable_feedback"


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


def emit_scope_delta(
    flow,
    scope: Dict[str, Any],
    *,
    stage_id: str = "init",
    step_id: str = "init.generate_scope",
) -> None:
    if not isinstance(scope, dict):
        return
    for key, title in (("in_scope", "範圍內"), ("out_of_scope", "範圍外")):
        values = scope.get(key) or []
        if not values:
            continue
        flow.logger.step_delta(
            stage_id,
            step_id,
            {
                "title": title,
                "text": "\n".join(f"- {value}" for value in values),
            },
            delta_type="scope",
            agent="analyst",
        )


def review_target_ids(text: str) -> list[str]:
    ids = [match.group(1).strip().upper() for match in TARGET_MENTION_RE.finditer(str(text or ""))]
    return list(dict.fromkeys(value for value in ids if value))


def strip_review_target_mentions(text: str) -> str:
    stripped = TARGET_MENTION_RE.sub(" ", str(text or ""))
    return re.sub(r"\s{2,}", " ", stripped).strip()


def clean_review_references(value: Any) -> list[Dict[str, str]]:
    rows: list[Dict[str, str]] = []
    seen: set[str] = set()
    if not isinstance(value, list):
        return rows
    for row in value:
        if not isinstance(row, dict):
            continue
        name = str(row.get("name") or "").strip()
        if not name:
            raw_path = str(row.get("path") or "").strip()
            name = raw_path.rsplit("/", 1)[-1]
        if not name or name in seen:
            continue
        seen.add(name)
        rows.append({"name": name})
    return rows


def normalize_review_considerations(
    review: Dict[str, Any],
    *,
    stage: str,
) -> list[Dict[str, Any]]:
    if not isinstance(review, dict):
        return []
    rows: list[Dict[str, Any]] = []
    suggestions = review.get("suggestions")
    if isinstance(suggestions, list):
        for item in suggestions:
            if not isinstance(item, dict):
                continue
            raw_text = str(item.get("text") or "").strip()
            explicit_targets = item.get("target_ids")
            target_ids = [
                str(value or "").strip().upper()
                for value in (explicit_targets if isinstance(explicit_targets, list) else [])
                if str(value or "").strip()
            ]
            target_ids.extend(review_target_ids(raw_text))
            text = strip_review_target_mentions(raw_text)
            references = clean_review_references(item.get("references"))
            if not text and not references and not target_ids:
                continue
            rows.append(
                {
                    "stage": stage,
                    "text": text or raw_text,
                    "target_ids": list(dict.fromkeys(target_ids)),
                    "references": references,
                }
            )
    if rows:
        return rows
    return rows


def append_review_considerations(
    artifact: Dict[str, Any],
    rows: list[Dict[str, Any]],
) -> None:
    if not rows:
        return
    artifact.setdefault("review_considerations", []).extend(rows)


def render_considerations_text(rows: list[Dict[str, Any]]) -> str:
    chunks: list[str] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        text = str(row.get("text") or "").strip()
        if not text:
            continue
        targets = [
            str(value or "").strip()
            for value in (row.get("target_ids") or [])
            if str(value or "").strip()
        ]
        target_label = f"targets: {', '.join(targets)}\n" if targets else ""
        chunks.append(f"{target_label}{text}".strip())
    return "\n\n".join(chunks)


def scope_from_review(review: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(review, dict):
        return {"in_scope": [], "out_of_scope": []}
    return scope_payload(review.get("scope", {}))


def emit_model_deltas(flow, rows: list[Dict[str, Any]]) -> None:
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        title = str(row.get("name") or row.get("type") or "系統模型").strip()
        body = str(row.get("description") or row.get("plantuml") or "").strip()
        flow.logger.step_delta(
            "system_model",
            "system_model.modeling",
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


def apply_requirements_review_direct_edit(
    requirements: list[Dict[str, Any]],
    review: Dict[str, Any],
) -> list[Dict[str, Any]]:
    if not isinstance(review, dict):
        return requirements
    action = str(review.get("action") or "").strip()
    if action != "direct_edit":
        return requirements

    edited = review.get("requirements")
    if not isinstance(edited, list) or not edited:
        return requirements

    existing_by_id = {
        str(row.get("id") or "").strip(): row
        for row in requirements or []
        if isinstance(row, dict) and str(row.get("id") or "").strip()
    }
    revised: list[Dict[str, Any]] = []
    for item in edited:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or "").strip()
        if not text:
            continue
        req_id = str(item.get("id") or "").strip()
        base = dict(existing_by_id.get(req_id, {}))
        base.update({key: value for key, value in item.items() if key != "text"})
        base["text"] = text
        revised.append(base)

    return ensure_requirement_candidate_ids(revised) if revised else requirements


def domain_research_review_feedback(review: Dict[str, Any]) -> str:
    if not isinstance(review, dict):
        return ""
    suggestions = review.get("suggestions")
    if not isinstance(suggestions, list):
        return ""
    rows: list[str] = []
    for index, item in enumerate(suggestions, start=1):
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or "").strip()
        references = item.get("references")
        ref_names: list[str] = []
        if isinstance(references, list):
            for ref in references:
                if not isinstance(ref, dict):
                    continue
                name = str(ref.get("name") or "").strip()
                if name:
                    ref_names.append(f"@{name}")
        target_ids = [
            str(value or "").strip().upper()
            for value in (item.get("target_ids") or [])
            if str(value or "").strip()
        ]
        target_ids.extend(review_target_ids(text))
        target_label = f"[targets: {', '.join(list(dict.fromkeys(target_ids)))}]" if target_ids else ""
        clean_text = strip_review_target_mentions(text)
        body = " ".join(part for part in [target_label, " ".join(ref_names), clean_text] if part).strip()
        if body:
            rows.append(f"建議 {index}：{body}")
    return "\n\n".join(rows)


def domain_research_review_references(review: Dict[str, Any], project_id: str) -> list[str]:
    if not isinstance(review, dict):
        return []
    attachment_paths = {
        str(item.get("name") or "").strip(): str(item.get("path") or "").strip()
        for item in (review.get("human_input_attachments") or [])
        if isinstance(item, dict)
        and str(item.get("name") or "").strip()
        and str(item.get("path") or "").strip()
    }
    rows: list[Dict[str, Any]] = []
    suggestions = review.get("suggestions")
    if isinstance(suggestions, list):
        for item in suggestions:
            if not isinstance(item, dict):
                continue
            references = item.get("references")
            if isinstance(references, list):
                rows.extend(ref for ref in references if isinstance(ref, dict))
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
        out.append(attachment_paths.get(name) or (f"{project_id}/{name}" if project_id else name))
    return out


def requirements_from_analysis(
    flow,
    stakeholders: list[Dict[str, Any]],
    *,
    considerations: Optional[List[Dict[str, Any]]] = None,
) -> list[Dict[str, Any]]:
    analysis = flow.analyst_agent.run_requirements_analyst(
        "analyze_requirements",
        stakeholders=stakeholders,
        review_considerations=considerations or [],
    )
    raw_initial_requirements = analysis if isinstance(analysis, list) else []
    initial_candidates = build_requirement_candidates_from_requirements(raw_initial_requirements or [])
    if not initial_candidates:
        flow.logger.warning("Analyst 初步抽取未產生 User Requirements，改用 stakeholder 原始表述建立初始 URL。")
        initial_candidates = build_initial_requirement_candidates_from_stakeholders(stakeholders)
    return attach_initial_source_ids(initial_candidates, stakeholders)


def review_considerations(
    artifact: Dict[str, Any],
    *,
    stage: str = "",
) -> list[Dict[str, Any]]:
    rows: list[Dict[str, Any]] = []
    for row in artifact.get("review_considerations") or []:
        if not isinstance(row, dict):
            continue
        if stage and str(row.get("stage") or "").strip() != stage:
            continue
        rows.append(row)
    return rows


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
    resume_stage = init_resume_stage(artifact)
    if resume_stage:
        flow.logger.info("依 checkpoint 從 %s 繼續初始化流程", resume_stage)
    if skip_before_resume_stage(artifact, "init"):
        flow.logger.info("依 checkpoint 略過初始化前置")
        require_stage_inputs(flow, artifact, "init")
    elif not run_init:
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
            selected = flow.collect.user_selection(proposed, max_select=max_sh)
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
            artifact["stakeholders"] = stakeholders
            flow.user_agent.stakeholders = stakeholders
            flow.store.save_artifact(artifact)
            flow.logger.step_completed(
                "init",
                "init.write_stakeholder_text",
                "整理利害關係人需求",
                agent="user",
                message=f"{len(stakeholders)} 位利害關係人提出需求",
                output_path="artifact/project.json",
            )
        stakeholder_review_output_title = ""
        while True:
            artifact["stakeholders"] = stakeholders
            flow.user_agent.stakeholders = stakeholders
            flow.store.save_artifact(artifact)

            review = flow.collect.stakeholder_statement_review(stakeholders)
            action = str((review or {}).get("action") or "approve").strip()
            artifact.setdefault("stakeholder_statement_reviews", []).append(review)
            artifact["stakeholder_statement_review"] = review

            if action == "approve":
                break
            if action == "direct_edit":
                flow.logger.step_started(
                    "init",
                    "init.write_stakeholder_text_review",
                    "利害關係人發言修正",
                    agent="user",
                    message="已收到回饋，更新中 ...",
                )
                stakeholders = apply_stakeholder_statement_review(stakeholders, review)
                stakeholder_review_output_title = "利害關係人發言修正"
                break

            consideration_rows = normalize_review_considerations(
                review or {},
                stage="stakeholder_statement_review",
            )
            if not consideration_rows:
                break

            flow.logger.step_started(
                "init",
                "init.write_stakeholder_text_review",
                "利害關係人發言修正",
                agent="user",
                message="已收到回饋，更新中 ...",
            )
            stakeholders = flow.user_agent.revise_stakeholder_text(
                rough_idea,
                stakeholders,
                consideration_rows,
            )
            stakeholder_review_output_title = "利害關係人發言修正"
            break

        artifact["stakeholders"] = stakeholders
        flow.user_agent.stakeholders = stakeholders
        flow.store.save_artifact(artifact)
        if stakeholder_review_output_title:
            flow.logger.step_completed(
                "init",
                "init.write_stakeholder_text_review",
                stakeholder_review_output_title,
                agent="user",
                output_path="artifact/project.json",
            )

        flow.logger.info(f"✓ {len(stakeholders)} 位利害關係人提出需求")

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
        stakeholder_considerations: list[Dict[str, Any]] = []
        initial_candidates = requirements_from_analysis(
            flow,
            stakeholders,
            considerations=stakeholder_considerations,
        )
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

        review = flow.collect.requirements_review(list(initial_candidates))
        action = str((review or {}).get("action") or "approve").strip()
        artifact.setdefault("requirements_reviews", []).append(review)
        artifact["requirements_review"] = review
        if action == "direct_edit":
            edited_candidates = apply_requirements_review_direct_edit(initial_candidates, review or {})
            artifact["URL"] = list(edited_candidates)
            flow.store.save_artifact(artifact)
            emit_requirement_deltas(
                flow,
                "init",
                "init.analyze_requirements_review",
                list(edited_candidates),
            )
            flow.logger.step_completed(
                "init",
                "init.analyze_requirements_review",
                "初始需求直接修正",
                agent="analyst",
                output_path="artifact/requirements.json",
            )
            initial_candidates = edited_candidates
        elif action != "approve":
            consideration_rows = normalize_review_considerations(
                review or {},
                stage="requirements_review",
            )
            if consideration_rows:
                append_review_considerations(
                    artifact,
                    consideration_rows,
                )
                flow.store.save_artifact(artifact)
                combined_considerations = (
                    stakeholder_considerations
                    + consideration_rows
                )
                flow.logger.step_started(
                    "init",
                    "init.analyze_requirements_review",
                    "考量使用者建議檢查初始需求",
                    agent="analyst",
                    message="已收到回饋，更新中 ...",
                )
                revised_candidates = requirements_from_analysis(
                    flow,
                    stakeholders,
                    considerations=combined_considerations,
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

        review = flow.collect.scope_review(artifact.get("scope", {}))
        action = str((review or {}).get("action") or "approve").strip()
        artifact.setdefault("scope_reviews", []).append(review)
        artifact["scope_review"] = review
        flow.store.save_artifact(artifact)
        if action == "direct_edit":
            edited_scope = scope_from_review(review)
            artifact["scope"] = edited_scope
            consideration_rows = normalize_review_considerations(
                review or {},
                stage="scope_review",
            )
            append_review_considerations(artifact, consideration_rows)
            flow.store.save_artifact(artifact)
            emit_scope_delta(
                flow,
                edited_scope,
                step_id="init.generate_scope_review",
            )
            flow.logger.step_completed(
                "init",
                "init.generate_scope_review",
                "需求範圍修正",
                agent="analyst",
                output_path="artifact/scope.json",
            )
            flow.logger.artifact_created(
                "init",
                "init.generate_scope_review",
                "需求範圍已更新",
                "artifact/scope.json",
            )
        elif action != "approve":
            consideration_rows = normalize_review_considerations(
                review or {},
                stage="scope_review",
            )
            if consideration_rows:
                append_review_considerations(
                    artifact,
                    consideration_rows,
                )
                flow.store.save_artifact(artifact)
                flow.logger.step_started(
                    "init",
                    "init.generate_scope_review",
                    "考量使用者建議檢查需求範圍",
                    agent="analyst",
                    message="已收到回饋，更新中 ...",
                )
                artifact["scope_review_feedback"] = render_considerations_text(consideration_rows)
                revised_scope = flow.analyst_agent.run_requirements_analyst(
                    "generate_scope",
                    artifact=artifact,
                )
                artifact.pop("scope_review_feedback", None)
                if isinstance(revised_scope, dict):
                    artifact["scope"] = {
                        "in_scope": revised_scope.get("in_scope", []) or [],
                        "out_of_scope": revised_scope.get("out_of_scope", []) or [],
                    }
                    flow.store.save_artifact(artifact)
                    emit_scope_delta(
                        flow,
                        artifact.get("scope", {}),
                        step_id="init.generate_scope_review",
                    )
                    flow.logger.step_completed(
                        "init",
                        "init.generate_scope_review",
                        "需求範圍修正",
                        agent="analyst",
                        output_path="artifact/scope.json",
                    )
                    flow.logger.artifact_created(
                        "init",
                        "init.generate_scope_review",
                        "需求範圍已更新",
                        "artifact/scope.json",
                    )
                else:
                    flow.store.save_artifact(artifact)

    elicitation_payload = artifact.get("elicitation") if isinstance(artifact.get("elicitation"), dict) else {}
    has_elicitation_output = bool(elicitation_payload.get("elicited_reqts")) or any(
        isinstance(row, dict) and str(row.get("source") or "").startswith("elicitation")
        for row in (artifact.get("URL", []) or [])
    )
    conflict_state = artifact.get("conflict") if isinstance(artifact.get("conflict"), dict) else {}
    has_conflict_detection_output = bool(
        conflict_state.get("pairs") or conflict_state.get("multiple")
    )
    force_elicitation = force_regenerate_output(flow.config, "elicitation")
    force_conflict_detection = force_regenerate_output(flow.config, "conflict_detection")
    force_system_model = force_regenerate_output(flow.config, "system_model")
    force_draft = force_regenerate_output(flow.config, "draft")

    if skip_before_resume_stage(artifact, "elicitation"):
        flow.logger.stage_started("elicitation", "需求擷取會議")
        flow.logger.info("=== 需求擷取會議 ===")
        flow.logger.info("依 checkpoint 略過需求擷取會議")
        require_stage_inputs(flow, artifact, "elicitation")
        flow.logger.stage_completed("elicitation", "需求擷取會議", message="依 checkpoint 略過需求擷取會議")
    elif not stage_enabled(flow.config, "elicitation"):
        flow.logger.stage_started("elicitation", "需求擷取會議")
        flow.logger.info("=== 需求擷取會議 ===")
        flow.logger.info("跳過需求擷取會議")
        flow.logger.stage_completed("elicitation", "需求擷取會議", message="需求擷取會議已跳過")
    elif has_elicitation_output and not force_elicitation:
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
    continue_signature_before = str(
        getattr(flow, "_continue_upstream_signature", "") or ""
    )
    continue_signature_after = upstream_requirements_signature(artifact)
    continue_upstream_changed = bool(
        continue_signature_before
        and continue_signature_before != continue_signature_after
    )
    if continue_upstream_changed:
        meta["requirements_changed"] = True
        meta["requirements_changed_by"] = "continue_init"
        meta["requirements_changed_reason"] = "continue_upstream_inputs_changed"
        meta["models_stale"] = True
        meta["models_stale_by"] = "continue_init"
        meta["models_stale_reason"] = "requirements_changed"
        meta["draft_stale"] = True
        meta["draft_stale_by"] = "continue_init"
        meta["draft_stale_reason"] = "requirements_changed"
        meta["specification_stale"] = True
        meta["export_stale"] = True
        meta["continue_upstream_changed_this_run"] = True
        flow.logger.info(
            "Continue 初始化內容已變更；將重新產生衝突、系統模型、草稿與規格輸出"
        )
    meta["upstream_requirements_signature"] = continue_signature_after
    requirements_changed = bool(meta.get("requirements_changed"))
    conflict_detection_ran = False
    if skip_before_resume_stage(artifact, "conflict_detection"):
        flow.logger.info("依 checkpoint 略過需求衝突辨識")
        require_stage_inputs(flow, artifact, "conflict_detection")
    elif not stage_enabled(flow.config, "conflict_detection"):
        flow.logger.info("跳過需求衝突辨識")
    elif has_conflict_detection_output and not requirements_changed and not force_conflict_detection:
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
        conflict_detection_ran = True
    conflict_state = artifact.get("conflict") if isinstance(artifact.get("conflict"), dict) else {}
    conflict_items = list(conflict_state.get("pairs") or []) + list(conflict_state.get("multiple") or [])
    should_run_conflict_review = (
        not skip_before_resume_stage(artifact, "conflict_detection")
        and
        bool(conflict_items)
        and meeting_setting(flow.config, "conflict_review", True)
        and stage_enabled(flow.config, "conflict_detection")
    )
    if should_run_conflict_review:
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
    elif conflict_detection_ran:
        save_conflict_report(flow.meeting, artifact, round_num=0)
    flow.store.save_artifact(artifact, commit_conflict_version=True)
    flow.logger.stage_completed("conflict_detection", "需求衝突辨識")

    flow.logger.stage_started("research_domain", "領域研究")
    flow.logger.info("=== Expert: 領域研究 ===")
    ran_research_domain = False
    reused_research_domain = False
    meta = artifact.setdefault("meta", {})
    if skip_before_resume_stage(artifact, "research_domain"):
        flow.logger.info("依 checkpoint 略過領域研究")
        require_stage_inputs(flow, artifact, "research_domain")
    elif not stage_enabled(flow.config, "research_domain"):
        flow.logger.info("跳過領域研究")
    else:
        references = []
        project_id = str(getattr(flow.store, "project_id", "") or "").strip()
        references_dir = flow.store.doc_dir / project_id if project_id else None
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
        meta = artifact.get("meta") if isinstance(artifact.get("meta"), dict) else {}
        run_referenced_files = merge_reference_paths(
            meta.get("domain_research_referenced_files") or []
        )
        review = flow.collect.domain_research_review(references)
        artifact.setdefault("domain_research_reviews", []).append(review)
        artifact["domain_research_review"] = review
        feedback, referenced_files = resolve_domain_research_review(
            review,
            run_referenced_files,
            project_id,
        )
        meta["domain_research_referenced_files"] = referenced_files
        if feedback:
            meta["domain_research_user_guidance"] = feedback
            append_review_considerations(
                artifact,
                normalize_review_considerations(
                    review,
                    stage="domain_research_review",
                ),
            )
        else:
            meta.pop("domain_research_user_guidance", None)
        if referenced_files:
            meta["attached_references"] = merge_reference_paths(
                meta.get("attached_references") or [],
                referenced_files,
            )
        if feedback or referenced_files:
            meta.pop("research_domain_completed", None)
            meta.pop("research_domain_coverage", None)
        artifact["meta"] = meta
        flow.store.save_artifact(artifact)
        require_stage_inputs(flow, artifact, "research_domain")
        if not reused_research_domain:
            flow.logger.step_started(
                "research_domain",
                "research_domain.workflow",
                "執行領域研究",
                agent="expert",
                message="尋找中 ...",
            )
            flow.expert_agent.run_research_loop(
                artifact,
            )
            ran_research_domain = True
            if has_feedback_payload(artifact) or has_domain_research_completion_marker(artifact):
                artifact.setdefault("meta", {})["research_domain_completed"] = True
            else:
                raise RuntimeError(
                    "領域研究流程已結束，但沒有產生 feedback 或合法的無適用結果標記"
                )
    flow.store.save_artifact(artifact)
    dr = artifact.get("feedback") if isinstance(artifact.get("feedback"), dict) else {}
    if ran_research_domain and not has_feedback_payload(artifact):
        if has_domain_research_completion_marker(artifact):
            flow.logger.info("Expert domain research：無新增有效 feedback，已記錄為完成狀態")
            artifact.setdefault("meta", {})["research_domain_completed"] = True
            flow.store.save_artifact(artifact)
        else:
            raise RuntimeError(
                "領域研究沒有有效 feedback，且 Expert 未提供合法的無適用結果標記"
            )
    if (ran_research_domain or reused_research_domain) and dr and isinstance(dr, dict) and dr:
        flow.logger.step_completed(
            "research_domain",
            "research_domain.update_feedback",
            "領域研究",
            agent="expert",
            output_path="artifact/feedback.json",
        )
        flow.logger.artifact_created(
            "research_domain",
            "research_domain.update_feedback",
            "領域研究結果已產生",
            "artifact/feedback.json",
        )
    flow.logger.stage_completed("research_domain", "領域研究")

    flow.logger.stage_started("system_model", "系統模型")
    flow.logger.info("=== Modeler: 系統模型 ===")
    generated_system_models = False
    reused_system_models = False
    if skip_before_resume_stage(artifact, "system_model"):
        flow.logger.info("依 checkpoint 略過系統模型")
        require_stage_inputs(flow, artifact, "system_model")
        model_data = artifact.get("system_models", [])
        reused_system_models = True
    elif not stage_enabled(flow.config, "system_model"):
        flow.logger.info("跳過系統模型")
        model_data = artifact.get("system_models", [])
    elif (
        has_system_models_payload(artifact)
        and artifact_path_non_empty(flow, "system_models.json")
        and not force_system_model
        and not bool(artifact.setdefault("meta", {}).get("models_stale"))
    ):
        model_data = artifact.get("system_models", [])
        reused_system_models = True
        flow.logger.info("✓ 系統模型已存在，跳過重新生成")
    else:
        require_stage_inputs(flow, artifact, "system_model")
        flow.logger.step_started(
            "system_model",
            "system_model.modeling",
            "產生系統模型",
            agent="modeler",
            message="生成中 ...",
        )
        model_data = flow.modeler_agent.generate_system_models(
            artifact,
        )
        artifact["system_models"] = model_data
        generated_system_models = True
        model_meta = artifact.setdefault("meta", {})
        model_meta.pop("models_stale", None)
        model_meta.pop("models_stale_by", None)
        model_meta.pop("models_stale_reason", None)
        flow.store.save_artifact(artifact)
        emit_model_deltas(flow, model_data)
    model_names = [
        str(model.get("name") or model.get("type") or "").strip()
        for model in (model_data if isinstance(model_data, list) else [])
        if isinstance(model, dict) and str(model.get("name") or model.get("type") or "").strip()
    ]
    flow.logger.step_completed(
        "system_model",
        "system_model.modeling",
        "系統模型",
        agent="modeler",
        message=(
            "沿用既有系統模型：" + "、".join(model_names)
            if reused_system_models and model_names
            else "沿用既有系統模型"
            if reused_system_models
            else "、".join(model_names)
            if model_names
            else "系統模型"
        ),
        output_path="artifact/system_models.json" if generated_system_models else None,
    )
    if generated_system_models:
        flow.logger.artifact_created(
            "system_model",
            "system_model.modeling",
            "系統模型已產生",
            "artifact/system_models.json",
        )
        flow.store.save_plantuml_files(model_data)
        artifact["system_models"] = model_data
        flow.store.save_artifact(artifact)
    flow.logger.stage_completed("system_model", "系統模型")

    flow.logger.stage_started("draft", "草稿化")
    flow.logger.info("=== Analyst: 草稿化 ===")
    if skip_before_resume_stage(artifact, "draft"):
        flow.logger.info("依 checkpoint 略過草稿化")
        require_stage_inputs(flow, artifact, "draft")
    elif not stage_enabled(flow.config, "draft"):
        flow.logger.info("跳過草稿化")
    elif (
        has_draft_payload(flow)
        and not force_draft
        and not bool(artifact.setdefault("meta", {}).get("draft_stale"))
    ):
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
        draft_meta = artifact.setdefault("meta", {})
        draft_stale = bool(draft_meta.get("draft_stale"))
        draft_version = (
            max(0, flow.store.get_draft_version() + 1)
            if draft_stale
            else 0
        )
        draft_md = flow.analyst_agent.run_requirements_analyst(
            "create_draft",
            artifact=artifact,
            draft_version=draft_version,
            artifact_dir=getattr(flow.store, "artifact_dir", None),
        )
        flow.store.save_draft(draft_md, version=draft_version)
        draft_meta.pop("draft_stale", None)
        draft_meta.pop("draft_stale_by", None)
        draft_meta.pop("draft_stale_reason", None)
        draft_meta["continue_regenerated_draft_version"] = draft_version
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
            f"Draft v{draft_version}",
            agent="analyst",
            output_path=f"artifact/drafts/draft_v{draft_version}.md",
        )
        flow.logger.artifact_created(
            "draft",
            "draft.create_draft",
            f"Draft v{draft_version} 已產生",
            f"artifact/drafts/draft_v{draft_version}.md",
        )
    flow.logger.stage_completed("draft", "草稿化")

    flow.touch_artifact_meta(artifact, round_num=0)
    flow.store.save_artifact(artifact)
    return artifact
