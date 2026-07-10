# Handles module workflow behavior.
import hashlib
import json
import re
from typing import Optional

from agents.skills.base import get_skill
from storage import parse_first_json
from storage.trace_req.schema import append_trace_req_row, trace_req_public_signature

from .actions.feedback import update_feedback
from .actions.read_reference import read_docs
from .actions.research import research_issue
from .plan import ExpertResearchPlan, compact_research_query
from .repair import repair_action_output
from .skill import domain_skill_subset

from .validation import clean_feedback, clean_research_result, has_research_content, requires_url_sources, source_records, source_title_from_url, source_urls


# ========
# Defines empty feedback marker function for this module workflow.
# ========
def empty_feedback_marker(reason: str) -> dict:
    return {
        "findings": [],
        "sources": [],
        "constraints": [],
        "risks": [],
        "recommendations": [],
        "status": "no_applicable_feedback",
        "reason": reason,
    }


# ========
# Defines research requirement candidates function for this module workflow.
# ========
def research_requirement_candidates(artifact):
    rows = []
    for req in artifact.get("URL") or []:
        if not isinstance(req, dict) or not str(req.get("text") or "").strip():
            continue
        row = {
            "id": req.get("id"),
            "text": req.get("text"),
            "priority": req.get("priority"),
            "source": req.get("source", ""),
        }
        rows.append(row)
    return rows


# ========
# Defines research stakeholders function for this module workflow.
# ========
def research_stakeholders(artifact):
    rows = []
    for stakeholder in artifact.get("stakeholders") or []:
        if not isinstance(stakeholder, dict):
            continue
        name = str(stakeholder.get("name") or "").strip()
        if not name:
            continue
        row = {"name": name}
        stakeholder_type = str(stakeholder.get("type") or "").strip()
        if stakeholder_type:
            row["type"] = stakeholder_type
        rows.append(row)
    return rows


# ========
# Defines research open questions function for this module workflow.
# ========
def research_open_questions(artifact):
    rows = []
    for question in artifact.get("open_questions") or []:
        if not isinstance(question, dict):
            continue
        text = str(question.get("question") or "").strip()
        if not text:
            continue
        rows.append(
            {
                "question": text,
                "status": question.get("status"),
                "type": question.get("type"),
            }
        )
    return rows


# ========
# Defines research context query function for this module workflow.
# ========
def research_target_context(artifact: dict, target_type: str = "", target_ids: Optional[list[str]] = None) -> dict:
    target_type = str(target_type or "").strip()
    target_ids = [
        str(value).strip()
        for value in (target_ids or [])
        if str(value).strip()
    ]
    url_rows = research_requirement_candidates(artifact)
    req_rows = artifact.get("REQ", []) if isinstance(artifact.get("REQ"), list) else []
    if target_type == "URL" and target_ids:
        url_rows = [
            row for row in url_rows
            if str(row.get("id") or "").strip() in target_ids
        ]
        req_rows = [
            row for row in req_rows
            if isinstance(row, dict)
            and (
                str(row.get("source_id") or "").strip() in target_ids
                or str(row.get("id") or "").strip() in target_ids
            )
        ]
    return {
        "target": {
            "target_type": target_type or "issue",
            "target_ids": target_ids,
        },
        "URL": url_rows,
        "REQ": req_rows,
    }


def research_context_query(query: str, artifact: dict, target_type: str = "", target_ids: Optional[list[str]] = None) -> str:
    """Build a narrow web-search query from the planned question plus target context."""
    scenario = str(artifact.get("scenario") or artifact.get("rough_idea") or "").strip()
    issue = artifact.get("current_issue") if isinstance(artifact.get("current_issue"), dict) else {}
    issue_text = " ".join(
        str(issue.get(key) or "").strip()
        for key in ("title", "description", "discussion_context")
        if str(issue.get(key) or "").strip()
    )
    target_context = research_target_context(artifact, target_type, target_ids)
    target_url_rows = target_context.get("URL") or []
    query_keywords = feedback_keywords(" ".join([query, issue_text])) or feedback_keywords(scenario)
    scored_requirements: list[tuple[int, str]] = []
    for req in target_url_rows or research_requirement_candidates(artifact):
        req_id = str(req.get("id") or "").strip()
        req_text = str(req.get("text") or "").strip()
        if not req_id or not req_text:
            continue
        overlap = query_keywords & feedback_keywords(req_text)
        score = len(overlap)
        if score:
            scored_requirements.append((score, f"{req_id}: {req_text}"))
    scored_requirements.sort(key=lambda row: (-row[0], row[1]))
    target_requirement = scored_requirements[0][1] if scored_requirements else ""
    if not target_requirement and target_url_rows:
        first_target = target_url_rows[0]
        req_id = str(first_target.get("id") or "").strip()
        req_text = str(first_target.get("text") or "").strip()
        if req_id and req_text:
            target_requirement = f"{req_id}: {req_text}"

    parts = []
    if scenario:
        parts.append(f"scenario: {scenario}")
    if target_type or target_ids:
        parts.append(f"target: {target_type or 'issue'} {', '.join(target_ids or [])}".strip())
    if target_requirement:
        parts.append(f"target requirement: {target_requirement}")
    elif issue_text:
        parts.append(f"issue: {issue_text}")
    parts.append("intent: context-specific applicable regulation authority standard compliance official guidance")
    parts.append(f"research question: {query}")
    return compact_research_query(" | ".join(parts), max_chars=360)


# ========
# Defines feedback keywords function for this module workflow.
# ========
def feedback_keywords(text: str) -> set[str]:
    normalized = str(text or "").lower()
    keywords = set(re.findall(r"[A-Za-z0-9_]+", normalized))
    compact = re.sub(r"[\s　,，。；;:：、/\\|()（）【】「」『』［］\\[\\]{}<>《》\"'`~!！?？.-]+", "", normalized)
    if len(compact) < 2:
        return keywords
    for size in (2, 3, 4):
        if len(compact) < size:
            continue
        for index in range(0, len(compact) - size + 1):
            token = compact[index:index + size]
            if len(set(token)) <= 1:
                continue
            keywords.add(token)
    return keywords


alignment_stopwords = {
    "使用",
    "需要",
    "能夠",
    "可以",
    "系統",
    "需求",
    "資料",
    "資訊",
    "服務",
    "流程",
    "使用者",
    "相關",
    "提供",
    "進行",
    "必須",
    "應該",
    "the",
    "and",
    "for",
    "with",
    "from",
    "that",
    "this",
    "system",
    "user",
    "data",
}


# ========
# Defines alignment keywords function for this module workflow.
# ========
def alignment_keywords(text: str) -> set[str]:
    return {
        token
        for token in feedback_keywords(text)
        if len(token) >= 2 and token not in alignment_stopwords
    }


# ========
# Defines requirement text index function for this module workflow.
# ========
def requirement_text_index(artifact: dict) -> dict[str, str]:
    rows: dict[str, str] = {}
    for req in research_requirement_candidates(artifact):
        req_id = str(req.get("id") or "").strip()
        req_text = str(req.get("text") or "").strip()
        if req_id and req_text:
            rows[req_id] = req_text
    for req in artifact.get("REQ") or []:
        if not isinstance(req, dict):
            continue
        req_id = str(req.get("source_id") or req.get("id") or "").strip()
        req_text = " ".join(
            str(req.get(key) or "").strip()
            for key in ("title", "description", "rationale")
            if str(req.get(key) or "").strip()
        )
        if req_id and req_text:
            rows.setdefault(req_id, req_text)
    return rows


# ========
# Defines feedback row context aligned function for this module workflow.
# ========
def feedback_row_context_aligned(row: dict, requirement_texts: dict[str, str]) -> bool:
    related_ids = [
        str(value).strip()
        for value in (row.get("related_requirement_ids") or [])
        if str(value).strip()
    ]
    if not related_ids:
        return False
    evidence_type = str(row.get("evidence_type") or row.get("source_type") or "").strip().lower()
    if evidence_type == "project_document" and any(req_id in requirement_texts for req_id in related_ids):
        return True
    row_text = str(row.get("text") or "").strip()
    row_terms = alignment_keywords(row_text)
    if not row_terms:
        return False
    for req_id in related_ids:
        req_terms = alignment_keywords(requirement_texts.get(req_id, ""))
        if len(row_terms & req_terms) >= 2:
            return True
    return False


# ========
# Defines filter feedback context alignment function for this module workflow.
# ========
def filter_feedback_context_alignment(feedback: dict, artifact: dict) -> dict:
    if not isinstance(feedback, dict):
        return feedback
    requirement_texts = requirement_text_index(artifact)
    if not requirement_texts:
        return feedback
    trace_gaps = [
        dict(row) for row in (feedback.get("trace_gaps") or [])
        if isinstance(row, dict)
    ]
    for section in ("findings", "constraints", "risks", "recommendations"):
        rows = feedback.get(section)
        if not isinstance(rows, list):
            continue
        kept = []
        for index, row in enumerate(rows, 1):
            if not isinstance(row, dict):
                continue
            if feedback_row_context_aligned(row, requirement_texts):
                kept.append(row)
                continue
            trace_gaps.append({
                "artifact": "feedback",
                "section": section,
                "item_index": index,
                "reason": "context_alignment_failed",
                "candidate_ids": [
                    str(value).strip()
                    for value in (row.get("related_requirement_ids") or [])
                    if str(value).strip()
                ],
                "source": row.get("source", ""),
                "status": "needs_review",
            })
        if kept:
            feedback[section] = kept
        else:
            feedback.pop(section, None)
    if trace_gaps:
        feedback["trace_gaps"] = trace_gaps
    has_rows = any(
        isinstance(feedback.get(section), list) and feedback.get(section)
        for section in ("findings", "constraints", "risks", "recommendations")
    )
    if not has_rows:
        feedback.pop("sources", None)
    return feedback


# ========
# Defines research result URL sources function for this module workflow.
# ========
def research_result_url_sources(research_results) -> list[str]:
    urls: list[str] = []
    seen = set()
    for result in research_results or []:
        if not isinstance(result, dict):
            continue
        candidates = []
        web_query = str(result.get("web_search_query") or "").strip()
        if web_query:
            candidates.append(web_query)
        evidence = result.get("research_evidence")
        if isinstance(evidence, dict):
            candidates.extend(evidence.get("sources") or [])
        extracted_urls = source_urls(candidates)
        extracted_urls.extend(
            str(source.get("url") or "").strip()
            for source in source_records(candidates)
            if str(source.get("url") or "").strip()
        )
        for url in extracted_urls:
            if url in seen:
                continue
            urls.append(url)
            seen.add(url)
    return urls


# ========
# Defines infer feedback requirement refs function for this module workflow.
# ========
def infer_feedback_requirement_refs(text: str, artifact: dict) -> list[str]:
    item_keywords = feedback_keywords(text)
    if not item_keywords:
        return []
    matches: list[tuple[int, str]] = []
    for req in research_requirement_candidates(artifact):
        req_id = str(req.get("id") or "").strip()
        req_text = str(req.get("text") or "").strip()
        if not req_id or not req_text:
            continue
        overlap = item_keywords & feedback_keywords(req_text)
        score = len(overlap)
        if score:
            matches.append((score, req_id))
    matches.sort(key=lambda row: (-row[0], row[1]))
    return [req_id for _, req_id in matches[:5]]


# ========
# Defines normalize feedback links function for this module workflow.
# ========
def normalize_feedback_links(feedback: dict, artifact: dict) -> dict:
    if not isinstance(feedback, dict):
        return feedback
    valid_url_ids = {
        str(row.get("id") or "").strip()
        for row in (artifact.get("URL") or [])
        if isinstance(row, dict) and str(row.get("id") or "").strip()
    }
    issue = artifact.get("current_issue") if isinstance(artifact.get("current_issue"), dict) else {}
    issue_source_ids = [
        str(value).strip()
        for value in (issue.get("meeting_id"), issue.get("id"))
        if str(value or "").strip()
    ]
    trace = issue.get("trace") if isinstance(issue.get("trace"), dict) else {}
    issue_url_ids = {
        str(value).strip()
        for value in (trace.get("artifact_ids") or [])
        if str(value).strip().startswith("URL-")
    }
    allowed_url_ids = issue_url_ids or valid_url_ids
    target_url_ids = {
        str(value).strip()
        for result in (artifact.get("research_results") or [])
        if isinstance(result, dict) and str(result.get("target_type") or "").strip() == "URL"
        for value in (result.get("target_ids") or [])
        if str(value).strip() in valid_url_ids
    }
    if target_url_ids:
        allowed_url_ids = allowed_url_ids & target_url_ids if allowed_url_ids else target_url_ids
    trace_gaps = [
        dict(row) for row in (feedback.get("trace_gaps") or [])
        if isinstance(row, dict)
    ]
    for section in ("findings", "constraints", "risks", "recommendations"):
        rows = feedback.get(section)
        if not isinstance(rows, list):
            continue
        for index, row in enumerate(rows, 1):
            if not isinstance(row, dict):
                continue
            row.pop("sources", None)
            source_ids = [
                str(value).strip()
                for value in (row.get("source_ids") or [])
                if str(value).strip()
            ]
            source = str(row.get("source") or "").strip()
            if source:
                source_ids.append(source)
            source_ids.extend(issue_source_ids)
            if source_ids:
                row["source_ids"] = list(dict.fromkeys(source_ids))
            supplied_refs = [
                str(value).strip()
                for value in (row.get("related_requirement_ids") or [])
                if str(value).strip()
            ]
            refs = [
                ref for ref in supplied_refs
                if ref in valid_url_ids and ref in allowed_url_ids
            ]
            rejected_refs = [
                ref for ref in supplied_refs
                if ref not in refs
            ]
            row["related_requirement_ids"] = list(dict.fromkeys(refs))
            row["trace_confidence"] = "explicit" if refs else "missing"
            if not str(row.get("trace_reason") or "").strip():
                if refs:
                    row["trace_reason"] = "Expert supplied related URL ids and runtime validated them against the current artifact context."
                else:
                    row["trace_reason"] = "Expert did not provide a runtime-valid related URL id."
            if not refs:
                trace_gaps.append({
                    "artifact": "feedback",
                    "section": section,
                    "item_index": index,
                    "reason": "missing_related_requirement_ids" if not supplied_refs else "invalid_related_requirement_ids",
                    "candidate_ids": list(dict.fromkeys(supplied_refs or infer_feedback_requirement_refs(str(row.get("text") or ""), artifact))),
                    "source": row.get("source", ""),
                    "status": "needs_review",
                })
            elif rejected_refs:
                trace_gaps.append({
                    "artifact": "feedback",
                    "section": section,
                    "item_index": index,
                    "reason": "rejected_related_requirement_ids",
                    "candidate_ids": list(dict.fromkeys(rejected_refs)),
                    "accepted_ids": list(dict.fromkeys(refs)),
                    "source": row.get("source", ""),
                    "status": "recorded",
                })
    if trace_gaps:
        feedback["trace_gaps"] = trace_gaps
    return feedback


# ========
# Defines research source function for this module workflow.
# ========
def research_source(artifact):
    issue = artifact.get("current_issue") if isinstance(artifact.get("current_issue"), dict) else {}
    meeting_id = str(issue.get("meeting_id") or "").strip()
    if meeting_id:
        return meeting_id
    issue_id = str(issue.get("id") or "").strip()
    if issue_id:
        return issue_id
    return "initial"


def feedback_item_count(artifact: dict) -> int:
    feedback = artifact.get("feedback") if isinstance(artifact.get("feedback"), dict) else {}
    count = 0
    for section in ("findings", "constraints", "risks", "recommendations"):
        count += len([item for item in (feedback.get(section) or []) if isinstance(item, dict)])
    return count


def feedback_delta_item_count(feedback_delta: dict) -> int:
    count = 0
    for section in ("findings", "constraints", "risks", "recommendations"):
        count += len([item for item in (feedback_delta.get(section) or []) if isinstance(item, dict)])
    return count


def document_evidence_feedback_delta(
    artifact: dict,
    document_evidence: list,
    *,
    source_ref: str,
) -> dict:
    if not isinstance(artifact, dict):
        artifact = {}
    valid_url_ids = {
        str(row.get("id") or "").strip()
        for row in (artifact.get("URL") or [])
        if isinstance(row, dict) and str(row.get("id") or "").strip()
    }
    coverage_target_ids = [
        str(row.get("target_id") or "").strip()
        for row in (artifact.get("document_coverage") or [])
        if isinstance(row, dict)
        and str(row.get("target_id") or "").strip() in valid_url_ids
        and str(row.get("status") or "").strip() != "not_found_in_documents"
    ]
    findings = []
    seen = set()
    for item in document_evidence or []:
        if not isinstance(item, dict):
            continue
        summary = str(item.get("summary") or "").strip()
        source = str(item.get("source") or "").strip()
        if not summary or not source:
            continue
        related_ids = [
            str(value).strip()
            for value in (item.get("related_requirement_ids") or [])
            if str(value).strip() in valid_url_ids
        ]
        if not related_ids:
            related_ids = list(dict.fromkeys(coverage_target_ids))
        key = json.dumps([summary, related_ids, source], ensure_ascii=False)
        if key in seen:
            continue
        seen.add(key)
        trace_reason = "Referenced project document evidence was read from the uploaded/reference file."
        section = str(item.get("section") or "").strip()
        if section:
            trace_reason += f" Section: {section}."
        findings.append({
            "text": summary,
            "related_requirement_ids": related_ids,
            "source": source_ref,
            "source_ids": [source_ref],
            "trace_reason": trace_reason,
            "evidence_type": "project_document",
        })
    if not findings:
        return {}
    sources = [
        {
            "title": str(item.get("source") or "").strip().rstrip("/").split("/")[-1],
            "url": str(item.get("source") or "").strip(),
            "type": "file",
        }
        for item in document_evidence or []
        if isinstance(item, dict) and str(item.get("source") or "").strip()
    ]
    return {
        "findings": findings,
        "sources": source_records(sources),
    }


def append_feedback_trace_req(artifact: dict, feedback_delta: dict, *, source_ref: str) -> None:
    if not isinstance(feedback_delta, dict):
        return
    events = artifact.setdefault("trace_req", [])
    if not isinstance(events, list):
        artifact["trace_req"] = events = []
    seen = {
        trace_req_public_signature(row)
        for row in events
        if isinstance(row, dict)
        and str(row.get("trace_id") or "").strip()
        and str(row.get("target_requirement_id") or "").strip()
        and str(row.get("from") or "").strip()
        and str(row.get("to") or "").strip()
    }
    req_to_srs = {
        str(req.get("id") or "").strip(): str(req.get("srs_id") or "").strip()
        for req in (artifact.get("REQ") or [])
        if isinstance(req, dict)
        and str(req.get("id") or "").strip()
        and str(req.get("srs_id") or "").strip()
    }
    delta_count = feedback_delta_item_count(feedback_delta)
    next_feedback_index = max(1, feedback_item_count(artifact) - delta_count + 1)
    for section in ("findings", "constraints", "risks", "recommendations"):
        for index, item in enumerate(feedback_delta.get(section) or [], 1):
            if not isinstance(item, dict):
                continue
            related_ids = [
                str(value).strip()
                for value in (item.get("related_requirement_ids") or [])
                if str(value).strip()
            ]
            confidence = str(item.get("trace_confidence") or ("explicit" if related_ids else "missing")).strip()
            reason = str(item.get("trace_reason") or "").strip()
            target_requirement_id = next(
                (
                    req_to_srs[req_id]
                    for req_id in related_ids
                    if req_id in req_to_srs
                ),
                "",
            )
            feedback_id = f"FB-{next_feedback_index}"
            append_trace_req_row(
                events,
                seen,
                target_requirement_id=target_requirement_id,
                from_id=related_ids[0] if related_ids else "",
                to_id=feedback_id,
                role="supporting",
                edge_label="依據",
                style="dashed",
                stage="domain_research",
                agent="expert",
                confidence=confidence,
                reason=reason,
                trace_reason=reason or source_ref,
            )
            next_feedback_index += 1

# ========
# Defines ExpertDomainResearch class for this module workflow.
# ========
class ExpertDomainResearch(ExpertResearchPlan):
    # Defines obs research function for this module workflow.
    def obs_research(self, **kwargs):
        return self.obs_research_state(
            kwargs["artifact"],
            kwargs.get("research_results", []),
            kwargs.get("iteration", 0),
            kwargs["max_iterations"],
            kwargs.get("actions_taken", []),
        )

    # Defines decide research function for this module workflow.
    def decide_research(self, *, observation, last_result=None, **kwargs):
        return self.plan_research(observation, last_result)

    # Defines run research step function for this module workflow.
    def run_research_step(self, *, decision, **kwargs):
        return self.run_research_action(
            decision.get("action", "done"),
            decision.get("params") or {},
            kwargs["artifact"],
            kwargs.get("research_results", []),
        )

    # Defines run research loop function for this module workflow.
    def run_research_loop(self, artifact):
        existing_research_results = (
            artifact.get("research_results")
            if isinstance(artifact.get("research_results"), list)
            else []
        )
        result = self.run_action_loop(
            name="research_domain",
            context={
                "artifact": artifact,
                "research_results": list(existing_research_results),
            },
            obs_fn=self.obs_research,
            decide_action=self.decide_research,
            execute_action=self.run_research_step,
        )
        return result

    # Defines obs research state function for this module workflow.
    def obs_research_state(
        self, artifact,
        research_results, iteration, max_iterations, actions_taken=None,
    ):
        url_requirements = research_requirement_candidates(artifact)
        existing = artifact.get("feedback") if isinstance(artifact.get("feedback"), dict) else {}
        existing_has_content = has_research_content(existing)
        scenario_source = artifact.get("scenario") or artifact.get("rough_idea")
        meta = artifact.get("meta") if isinstance(artifact.get("meta"), dict) else {}
        coverage_rows = artifact.get("document_coverage", []) or []
        coverage_statuses = {
            str(row.get("status") or "").strip()
            for row in coverage_rows
            if isinstance(row, dict) and str(row.get("status") or "").strip()
        }
        baseline_research_needed = (
            not existing_has_content
            and not research_results
            and "web_search" in self.tools
            and bool(url_requirements or artifact.get("REQ") or artifact.get("open_questions") or scenario_source)
        )
        resume_checkpoint = (
            meta.get("last_resume_checkpoint")
            if isinstance(meta.get("last_resume_checkpoint"), dict)
            else {}
        )
        return {
            "issue": artifact.get("current_issue") if isinstance(artifact.get("current_issue"), dict) else {},
            "scenario": str(scenario_source or "").strip(),
            "scope": artifact.get("scope", {}),
            "URL": url_requirements,
            "REQ": artifact.get("REQ", []) if isinstance(artifact.get("REQ"), list) else [],
            "stakeholders": research_stakeholders(artifact),
            "open_questions": research_open_questions(artifact),
            "has_existing_research": existing_has_content,
            "research_results_count": len(research_results),
            "document_evidence_count": len(artifact.get("document_evidence", []) or []),
            "document_coverage": coverage_rows,
            "not_found_in_documents": "not_found_in_documents" in coverage_statuses,
            "document_conflict": "document_conflict" in coverage_statuses,
            "needs_external_validation": "needs_external_validation" in coverage_statuses,
            "baseline_research_needed": baseline_research_needed,
            "resume_checkpoint": resume_checkpoint,
            "has_read_file": "read_file" in self.tools,
            "has_web_search": "web_search" in self.tools,
            "user_guidance": str(meta.get("domain_research_user_guidance") or "").strip(),
            "referenced_files": meta.get("domain_research_referenced_files") or [],
            "actions_taken": actions_taken or [],
            "iteration": iteration + 1,
            "max_iterations": max_iterations,
        }

    # Defines run research action function for this module workflow.
    def run_research_action(
        self, action, params, artifact, research_results,
    ):
        obs: dict = {"action": action, "result": None, "error": None, "summary": ""}
        query_for_step = str(params.get("query") or params.get("topic") or "").strip()
        step_suffix = action
        if query_for_step:
            query_digest = hashlib.sha1(query_for_step.encode("utf-8")).hexdigest()[:10]
            step_suffix = f"{action}.{query_digest}"
        self.record_runtime_checkpoint(
            stage_id="research_domain",
            step_id=f"research_domain.{step_suffix}",
            action=action,
        )

        if action == "read_reference_docs":
            if "read_file" not in self.tools:
                obs["summary"] = "read_file 工具不可用，略過文件讀取"
                obs["result"] = {"document_evidence": [], "gaps": ["read_file 工具不可用"]}
                return obs
            query = str(params.get("query") or params.get("topic") or "").strip()
            if not query:
                obs["error"] = "query 參數為空"
                obs["summary"] = "文件讀取失敗：未提供查詢問題"
                return obs
            scenario_source = artifact.get("scenario") or artifact.get("rough_idea")
            meta = artifact.get("meta") if isinstance(artifact.get("meta"), dict) else {}
            attached_references = [
                str(path).strip()
                for path in (meta.get("attached_references") or [])
                if str(path).strip()
            ]
            referenced_files = [
                str(path).strip()
                for path in (meta.get("domain_research_referenced_files") or [])
                if str(path).strip()
            ]
            if not referenced_files:
                obs["summary"] = "未指定本輪引用文件，略過文件讀取"
                obs["result"] = {
                    "document_evidence": [],
                    "gaps": ["未指定本輪引用文件"],
                }
                return obs
            context = {
                "issue": artifact.get("current_issue") if isinstance(artifact.get("current_issue"), dict) else {},
                "scenario": str(scenario_source or "").strip(),
                "scope": artifact.get("scope", {}),
                "URL": research_requirement_candidates(artifact),
                "REQ": artifact.get("REQ", []) if isinstance(artifact.get("REQ"), list) else [],
                "stakeholders": research_stakeholders(artifact),
                "open_questions": research_open_questions(artifact),
                "existing_document_evidence": artifact.get("document_evidence", []) or [],
                "attached_references": attached_references,
                "referenced_files": referenced_files,
            }
            task = read_docs(query=query, attached_references=referenced_files)
            try:
                skill = domain_skill_subset(get_skill("domain-research"), "read_docs")
                raw = self.chat_with_tools(
                    self.build_skill_messages(skill, "domain-research", task, context=context),
                    active_skill="domain-research",
                )
                data = self.parse_research_json(
                    raw,
                    action=action,
                    source_ref=research_source(artifact),
                )
                evidence = self.clean_document_evidence(data.get("document_evidence"))
                coverage = self.clean_document_coverage(data.get("coverage"))
                gaps = [
                    str(item).strip()
                    for item in (data.get("gaps") or [])
                    if str(item).strip()
                ]
                artifact["document_evidence"] = self.merge_document_evidence(
                    artifact.get("document_evidence", []),
                    evidence,
                )
                artifact["document_coverage"] = self.merge_document_coverage(
                    artifact.get("document_coverage", []),
                    coverage,
                )
                store = getattr(self, "runtime_store", None)
                if store:
                    store.save_artifact(artifact)
                obs["result"] = {"document_evidence": evidence, "coverage": coverage, "gaps": gaps}
                obs["context_updates"] = {"artifact": artifact}
                obs["summary"] = f"文件證據 {len(evidence)} 筆，coverage {len(coverage)} 筆，缺口 {len(gaps)} 筆"
            except Exception as e:
                obs["error"] = str(e)
                obs["summary"] = f"文件讀取失敗: {e}"
            return obs

        if action == "research_issue":
            query = params.get("query", "")
            if not query:
                obs["error"] = "query 參數為空"
                obs["summary"] = "研究失敗：未提供研究問題"
                return obs
            value_reason = str(params.get("value_reason") or "").strip()
            target_type = str(params.get("target_type") or "").strip()
            target_ids = [
                str(value).strip()
                for value in (params.get("target_ids") or [])
                if str(value).strip()
            ]
            scenario_source = artifact.get("scenario") or artifact.get("rough_idea")
            target_context = research_target_context(artifact, target_type, target_ids)
            context = {
                "issue": artifact.get("current_issue") if isinstance(artifact.get("current_issue"), dict) else {},
                "scenario": str(scenario_source or "").strip(),
                "scope": artifact.get("scope", {}),
                "target": target_context["target"],
                "URL": target_context["URL"],
                "REQ": target_context["REQ"],
                "stakeholders": research_stakeholders(artifact),
                "open_questions": research_open_questions(artifact),
                "document_evidence": artifact.get("document_evidence", []) or [],
                "document_coverage": artifact.get("document_coverage", []) or [],
            }
            web_search_evidence = ""
            web_urls = []
            if "web_search" in self.tools:
                search_tool = self.tools["web_search"]
                if callable(getattr(search_tool, "reset_session", None)):
                    search_tool.reset_session()
                web_query = research_context_query(query, artifact, target_type, target_ids)
                web_search_evidence = search_tool.execute(
                    query=web_query,
                    max_results=10,
                    user_question=web_query,
                )
                web_urls = source_urls(web_search_evidence)
                context["web_search_evidence"] = web_search_evidence
                context["web_search_urls"] = web_urls
                context["web_search_query"] = web_query
            source_ref = research_source(artifact)
            task = research_issue(
                query=query,
                source_ref=source_ref,
                value_reason=value_reason,
            )
            skill = domain_skill_subset(get_skill("domain-research"), "research")
            messages = self.build_skill_messages(skill, "domain-research", task, context=context)
            try:
                raw = (
                    self.chat_with_tools(
                        messages,
                        active_skill="domain-research",
                    )
                    if self.tools
                    else self.model.chat(messages)
                )
                result = self.clean_research_json(
                    raw,
                    action=action,
                    source_ref=source_ref,
                    cleaner=clean_research_result,
                    url_sources=web_urls,
                    file_sources=self.feedback_file_sources(artifact, []),
                )
                if result:
                    research_results.append(
                        {
                            "target_type": target_type,
                            "target_ids": target_ids,
                            "query": query,
                            "web_search_query": context.get("web_search_query", query),
                            "value_reason": value_reason,
                            "research_evidence": result,
                        }
                    )
                    artifact.setdefault("research_results", []).append(
                        {
                            "target_type": target_type,
                            "target_ids": target_ids,
                            "query": query,
                            "web_search_query": context.get("web_search_query", query),
                            "value_reason": value_reason,
                            "research_evidence": result,
                        }
                    )
                    store = getattr(self, "runtime_store", None)
                    if store:
                        store.save_artifact(artifact)
                obs["result"] = {"research_evidence": result} if result else {"research_evidence": {}}
                if result:
                    obs["summary"] = (
                        f"研究 '{query}': "
                        f"{len(result.get('findings', []))} 項發現"
                    )
                else:
                    obs["summary"] = f"研究 '{query}': 未取得可寫入 feedback 的 URL 證據"
            except Exception as e:
                obs["error"] = str(e)
                obs["summary"] = f"研究失敗: {e}"
            return obs

        if action == "update_feedback":
            document_evidence = artifact.get("document_evidence", []) or []
            if not research_results and not document_evidence:
                artifact["feedback"] = empty_feedback_marker("domain research completed without URL-backed findings")
                obs["result"] = {"feedback": artifact["feedback"]}
                obs["summary"] = "無研究結果或文件證據可更新，已標記領域研究完成"
                return obs
            existing = artifact.get("feedback") if isinstance(artifact.get("feedback"), dict) else {}
            context = {
                "research_results": research_results,
                "existing_research": existing,
                "document_evidence": document_evidence,
                "document_coverage": artifact.get("document_coverage", []) or [],
            }
            source_ref = research_source(artifact)
            task = update_feedback(source_ref=source_ref)
            try:
                skill = domain_skill_subset(get_skill("domain-research"), "feedback")
                messages = self.build_skill_messages(skill, "domain-research", task, context=context)
                raw = self.run_skill_messages("domain-research", messages)
                dr = self.clean_research_json(
                    raw,
                    action=action,
                    source_ref=source_ref,
                    cleaner=clean_feedback,
                    url_sources=research_result_url_sources(research_results),
                    file_sources=self.feedback_file_sources(artifact, document_evidence),
                )
                if dr:
                    dr = normalize_feedback_links(dr, artifact)
                    dr = filter_feedback_context_alignment(dr, artifact)
                    if not feedback_delta_item_count(dr) and document_evidence:
                        dr = document_evidence_feedback_delta(
                            artifact,
                            document_evidence,
                            source_ref=source_ref,
                        )
                        dr = normalize_feedback_links(dr, artifact)
                        dr = filter_feedback_context_alignment(dr, artifact)
                elif document_evidence:
                    dr = document_evidence_feedback_delta(
                        artifact,
                        document_evidence,
                        source_ref=source_ref,
                    )
                    dr = normalize_feedback_links(dr, artifact)
                    dr = filter_feedback_context_alignment(dr, artifact)
                if dr:
                    merged = self.merge_feedback(existing, dr)
                    artifact["feedback"] = merged
                    append_feedback_trace_req(artifact, dr, source_ref=source_ref)
                    store = getattr(self, "runtime_store", None)
                    if store:
                        store.save_artifact(artifact)
                    obs["result"] = {"feedback": dr, "merged_feedback": merged}
                    obs["summary"] = "已更新領域研究資料"
                else:
                    artifact["feedback"] = existing or empty_feedback_marker("domain research produced no valid feedback rows")
                    obs["result"] = {"feedback": {}, "merged_feedback": artifact["feedback"]}
                    obs["summary"] = "無新增有效 feedback rows"
            except Exception as e:
                obs["error"] = str(e)
                obs["summary"] = f"更新失敗: {e}"
                artifact["feedback"] = existing or empty_feedback_marker(
                    f"domain research feedback update failed: {e}"
                )
                obs["result"] = {"feedback": {}, "merged_feedback": artifact["feedback"]}
            return obs

        obs["error"] = f"未知動作: {action}"
        return obs

    # Defines parse research json function for this module workflow.
    def parse_research_json(self, raw, *, action: str, source_ref: str):
        try:
            return parse_first_json(raw)
        except Exception as e:
            repair_task = repair_action_output(
                action=action,
                raw=raw,
                error=str(e),
                source_ref=source_ref,
            )
            repaired = self.model.chat(self.build_direct_messages(repair_task))
            return parse_first_json(repaired)

    # Defines clean research json function for this module workflow.
    def clean_research_json(
        self,
        raw,
        *,
        action: str,
        source_ref: str,
        cleaner,
        url_sources=None,
        file_sources=None,
    ):
        data = self.parse_research_json(raw, action=action, source_ref=source_ref)
        cleaned = cleaner(data, context_source=source_ref)
        cleaned = self.attach_url_sources(cleaned, url_sources)
        cleaned = self.attach_file_sources(cleaned, file_sources)
        if cleaned and not self.missing_url_sources(cleaned, file_sources=file_sources):
            return cleaned
        error = "輸出缺少有效 findings / constraints / risks / recommendations"
        if cleaned:
            error = "輸出包含需要外部證據支持的主張，但缺少完整 URL 或專案引用文件證據"
        repair_task = repair_action_output(
            action=action,
            raw=data,
            error=error,
            source_ref=source_ref,
        )
        repaired = self.model.chat(self.build_direct_messages(repair_task))
        repaired_cleaned = cleaner(parse_first_json(repaired), context_source=source_ref)
        repaired_cleaned = self.attach_url_sources(repaired_cleaned, url_sources)
        repaired_cleaned = self.attach_file_sources(repaired_cleaned, file_sources)
        if self.missing_url_sources(repaired_cleaned, file_sources=file_sources):
            if action == "update_feedback":
                return {}
            raise ValueError("Expert feedback with external claims must include URL sources or referenced project files")
        return repaired_cleaned

    @staticmethod
    # Defines attach URL sources function for this module workflow.
    def attach_url_sources(payload, urls):
        if not isinstance(payload, dict):
            return payload
        url_payloads = [
            {
                "title": source_title_from_url(str(url).strip()),
                "url": str(url).strip(),
            }
            for url in (urls or [])
            if str(url or "").strip()
        ]
        merged = []
        seen = set()
        for source in source_records(list(payload.get("sources") or []) + url_payloads):
            url = str(source.get("url") or "").strip()
            source_type = str(source.get("type") or "web").strip() or "web"
            key = f"{source_type}:{url}"
            if url and key not in seen:
                merged.append(source)
                seen.add(key)
        payload["sources"] = merged
        return payload

    @staticmethod
    # Defines attach file sources function for this module workflow.
    def attach_file_sources(payload, file_sources):
        if not isinstance(payload, dict):
            return payload
        source_payloads = []
        for source in file_sources or []:
            source_text = str(source or "").strip()
            if not source_text:
                continue
            source_payloads.append({
                "title": source_text.rstrip("/").split("/")[-1],
                "url": source_text,
                "type": "file",
            })
        merged = []
        seen = set()
        for source in source_records(list(payload.get("sources") or []) + source_payloads):
            url = str(source.get("url") or "").strip()
            source_type = str(source.get("type") or "web").strip() or "web"
            key = f"{source_type}:{url}"
            if url and key not in seen:
                merged.append(source)
                seen.add(key)
        payload["sources"] = merged
        return payload

    @staticmethod
    # Defines merge feedback function for this module workflow.
    def merge_feedback(existing, delta):
        def row_key(row):
            if not isinstance(row, dict):
                return ""
            text = " ".join(str(row.get("text") or "").split()).lower()
            related = tuple(
                sorted(
                    str(value).strip()
                    for value in (row.get("related_requirement_ids") or [])
                    if str(value).strip()
                )
            )
            source = str(row.get("source") or "").strip()
            return json.dumps([text, related, source], ensure_ascii=False)

        merged = {"findings": [], "constraints": [], "risks": [], "recommendations": [], "sources": [], "trace_gaps": []}
        for section in ("findings", "constraints", "risks", "recommendations"):
            seen = set()
            for payload in (existing, delta):
                rows = payload.get(section) if isinstance(payload, dict) else []
                for row in rows or []:
                    if not isinstance(row, dict):
                        continue
                    key = row_key(row)
                    if not key or key in seen:
                        continue
                    merged[section].append(dict(row))
                    seen.add(key)

        seen_sources = set()
        for payload in (existing, delta):
            for source in source_records((payload.get("sources") if isinstance(payload, dict) else []) or []):
                url = str(source.get("url") or "").strip()
                source_type = str(source.get("type") or "web").strip() or "web"
                key = f"{source_type}:{url}"
                if not url or key in seen_sources:
                    continue
                merged["sources"].append(source)
                seen_sources.add(key)

        seen_gaps = set()
        for payload in (existing, delta):
            for gap in (payload.get("trace_gaps") if isinstance(payload, dict) else []) or []:
                if not isinstance(gap, dict):
                    continue
                key = json.dumps(gap, ensure_ascii=False, sort_keys=True)
                if key in seen_gaps:
                    continue
                merged["trace_gaps"].append(dict(gap))
                seen_gaps.add(key)

        return {
            key: value
            for key, value in merged.items()
            if value
        }

    @staticmethod
    # Defines missing URL sources function for this module workflow.
    def missing_url_sources(payload, *, file_sources=None):
        return (
            bool(payload)
            and requires_url_sources(payload)
            and not payload.get("sources")
            and not file_sources
        )

    @classmethod
    # Defines feedback file sources function for this module workflow.
    def feedback_file_sources(cls, artifact, document_evidence):
        meta = artifact.get("meta") if isinstance(artifact, dict) and isinstance(artifact.get("meta"), dict) else {}
        rows = []
        seen = set()
        for item in cls.clean_document_evidence(document_evidence):
            source = str(item.get("source") or "").strip()
            if source and source not in seen:
                rows.append(source)
                seen.add(source)
        for source in (meta.get("domain_research_referenced_files") or []):
            source_text = str(source or "").strip()
            if source_text and source_text not in seen:
                rows.append(source_text)
                seen.add(source_text)
        return rows

    @staticmethod
    # Defines clean document evidence function for this module workflow.
    def clean_document_evidence(raw):
        rows = []
        seen = set()
        for item in raw or []:
            if not isinstance(item, dict):
                continue
            source = str(item.get("source") or "").strip()
            summary = str(item.get("summary") or "").strip()
            if not source or not summary:
                continue
            row = {
                "source": source,
                "summary": summary,
                "related_requirement_ids": [
                    str(value).strip()
                    for value in (item.get("related_requirement_ids") or [])
                    if str(value).strip()
                ],
            }
            section = str(item.get("section") or "").strip()
            if section:
                row["section"] = section
            key = json.dumps(row, ensure_ascii=False, sort_keys=True)
            if key in seen:
                continue
            seen.add(key)
            rows.append(row)
        return rows

    @classmethod
    # Defines merge document evidence function for this module workflow.
    def merge_document_evidence(cls, existing, new_rows):
        rows = cls.clean_document_evidence(existing)
        seen = {
            json.dumps(row, ensure_ascii=False, sort_keys=True)
            for row in rows
        }
        for row in cls.clean_document_evidence(new_rows):
            key = json.dumps(row, ensure_ascii=False, sort_keys=True)
            if key in seen:
                continue
            rows.append(row)
            seen.add(key)
        return rows

    @staticmethod
    # Defines clean document coverage function for this module workflow.
    def clean_document_coverage(raw):
        valid_status = {
            "document_supported",
            "not_found_in_documents",
            "document_conflict",
            "needs_external_validation",
        }
        rows = []
        seen = set()
        for item in raw or []:
            if not isinstance(item, dict):
                continue
            target_id = str(item.get("target_id") or "").strip()
            status = str(item.get("status") or "").strip()
            reason = str(item.get("reason") or "").strip()
            if not target_id or status not in valid_status:
                continue
            row = {
                "target_id": target_id,
                "status": status,
                "reason": reason,
            }
            key = json.dumps(row, ensure_ascii=False, sort_keys=True)
            if key in seen:
                continue
            seen.add(key)
            rows.append(row)
        return rows

    @classmethod
    # Defines merge document coverage function for this module workflow.
    def merge_document_coverage(cls, existing, new_rows):
        rows = cls.clean_document_coverage(existing)
        seen = {
            json.dumps(row, ensure_ascii=False, sort_keys=True)
            for row in rows
        }
        for row in cls.clean_document_coverage(new_rows):
            key = json.dumps(row, ensure_ascii=False, sort_keys=True)
            if key in seen:
                continue
            rows.append(row)
            seen.add(key)
        return rows
