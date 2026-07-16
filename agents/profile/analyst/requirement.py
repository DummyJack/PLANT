# Handles formal requirement updates and refinement.
import copy
import re
from typing import Any, Dict, List, Optional

from storage.requirements import (
    ensure_requirement_candidate_ids,
    requirement_dedupe_key,
    renumber_system_requirement_ids,
    replace_system_requirement_refs,
)

from .actions.reqt.refine import refine_requirement
from .actions.reqt.update import update_requirement, update_requirement_coverage
from .repair import requirement_repair_prompt


REQUIREMENT_UPDATE_LIMIT = 2
REQUIREMENT_REFINE_LIMIT = 2
REQUIREMENT_COVERAGE_BATCH_SIZE = 5
REQUIREMENT_COVERAGE_BATCH_LIMIT = 8


class AnalystRequirementFlow:
    @staticmethod
    def requirement_match_terms(value: Any) -> set[str]:
        text = str(value or "").lower()
        terms = set(re.findall(r"[a-z0-9_]{2,}", text))
        for chunk in re.findall(r"[\u4e00-\u9fff]{2,}", text):
            terms.update(chunk[index:index + 2] for index in range(len(chunk) - 1))
        return terms

    @staticmethod
    def requirement_context_refs(value: Any) -> set[str]:
        refs: set[str] = set()
        if isinstance(value, dict):
            for item in value.values():
                refs.update(AnalystRequirementFlow.requirement_context_refs(item))
        elif isinstance(value, list):
            for item in value:
                refs.update(AnalystRequirementFlow.requirement_context_refs(item))
        else:
            refs.update(
                re.findall(
                    r"\b(?:(?:URL|REQ|SM|CR|FB)-\d+|R\d+-M\d+)\b",
                    str(value or ""),
                )
            )
        return refs

    @classmethod
    def relevant_feedback_context(
        cls,
        feedback: Dict[str, List[Dict[str, Any]]],
        urls: List[Dict[str, Any]],
        requirements: List[Dict[str, Any]],
        issue: Dict[str, Any],
        *,
        per_section_limit: int = 5,
    ) -> Dict[str, List[Dict[str, Any]]]:
        target_refs = cls.requirement_context_refs(urls)
        target_refs.update(cls.requirement_context_refs(requirements))
        target_refs.update(cls.requirement_context_refs(issue.get("trace", {})))
        target_terms = cls.requirement_match_terms(
            " ".join(
                str(row.get(key) or "")
                for row in urls + requirements
                if isinstance(row, dict)
                for key in ("text", "title", "description", "rationale")
            )
        )
        out: Dict[str, List[Dict[str, Any]]] = {}
        for section, rows in feedback.items():
            ranked = []
            for index, row in enumerate(rows or []):
                if not isinstance(row, dict):
                    continue
                direct = bool(cls.requirement_context_refs(row) & target_refs)
                score = len(
                    target_terms
                    & cls.requirement_match_terms(
                        " ".join(str(row.get(key) or "") for key in ("text", "status"))
                    )
                )
                if direct or score >= 2:
                    ranked.append((int(direct), score, index, row))
            ranked.sort(key=lambda item: (-item[0], -item[1], item[2]))
            selected = [item[3] for item in ranked[:per_section_limit]]
            if selected:
                out[section] = selected
        return out

    @classmethod
    def relevant_system_model_context(
        cls,
        models: List[Dict[str, Any]],
        urls: List[Dict[str, Any]],
        requirements: List[Dict[str, Any]],
        issue: Dict[str, Any],
        *,
        limit: int = 5,
    ) -> List[Dict[str, Any]]:
        target_refs = cls.requirement_context_refs(urls)
        target_refs.update(cls.requirement_context_refs(requirements))
        target_refs.update(cls.requirement_context_refs(issue.get("trace", {})))
        target_terms = cls.requirement_match_terms(
            " ".join(
                str(row.get(key) or "")
                for row in urls + requirements
                if isinstance(row, dict)
                for key in ("text", "title", "description")
            )
        )
        ranked = []
        for index, row in enumerate(models or []):
            if not isinstance(row, dict):
                continue
            direct = bool(cls.requirement_context_refs(row) & target_refs)
            score = len(
                target_terms
                & cls.requirement_match_terms(
                    " ".join(
                        str(row.get(key) or "")
                        for key in ("name", "type", "description")
                    )
                )
            )
            if direct or score >= 2:
                ranked.append((int(direct), score, index, row))
        ranked.sort(key=lambda item: (-item[0], -item[1], item[2]))
        return [item[3] for item in ranked[:limit]]

    @classmethod
    def relevant_requirement_context(
        cls,
        requirements: List[Dict[str, Any]],
        urls: List[Dict[str, Any]],
        issue: Dict[str, Any],
        *,
        candidate_limit: int = 5,
    ) -> List[Dict[str, Any]]:
        """Select the existing REQs most relevant to the active URL batch."""
        trace = issue.get("trace") if isinstance(issue.get("trace"), dict) else {}
        traced_req_ids = {
            str(item).strip()
            for item in (trace.get("artifact_ids") or [])
            if str(item).strip().startswith("REQ-")
        }
        if not urls:
            if not traced_req_ids:
                return requirements
            return [
                row
                for row in requirements
                if isinstance(row, dict)
                and str(row.get("id") or "").strip() in traced_req_ids
            ]
        url_ids = {
            str(row.get("id") or "").strip()
            for row in urls
            if isinstance(row, dict) and str(row.get("id") or "").strip()
        }
        url_terms = set()
        for row in urls:
            if isinstance(row, dict):
                url_terms.update(cls.requirement_match_terms(row.get("text")))
        selected: List[Dict[str, Any]] = []
        selected_ids = set()
        candidates = []
        for index, row in enumerate(requirements):
            if not isinstance(row, dict):
                continue
            req_id = str(row.get("id") or "").strip()
            sources = {
                str(item).strip()
                for item in (row.get("source") or [])
                if str(item).strip()
            }
            if sources & url_ids or req_id in traced_req_ids:
                selected.append(row)
                selected_ids.add(req_id or f"index:{index}")
                continue
            req_terms = cls.requirement_match_terms(
                " ".join(
                    str(row.get(key) or "")
                    for key in ("title", "description", "rationale")
                )
            )
            score = len(url_terms & req_terms)
            if score >= 2:
                candidates.append((score, index, row, req_id))

        candidates.sort(key=lambda item: (-item[0], item[1]))
        for _, index, row, req_id in candidates[:candidate_limit]:
            marker = req_id or f"index:{index}"
            if marker not in selected_ids:
                selected.append(row)
                selected_ids.add(marker)
        return selected

    def execute_update_requirement(
        self,
        *,
        artifact: Dict[str, Any],
        issue: Dict[str, Any],
        previous_responses: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        return self.update_requirement(
            artifact=artifact,
            issue=issue,
            previous_responses=previous_responses,
        )

    def execute_refine_requirement(
        self,
        *,
        artifact: Dict[str, Any],
        issue: Dict[str, Any],
        previous_responses: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        return self.refine_requirement(
            artifact=artifact,
            issue=issue,
            previous_responses=previous_responses,
        )

    def requirement_action_context(
        self,
        *,
        artifact: Dict[str, Any],
        issue: Dict[str, Any],
        previous_responses: Optional[List[Dict[str, Any]]] = None,
        current_URL: Optional[List[Dict[str, Any]]] = None,
        current_REQ: Optional[List[Dict[str, Any]]] = None,
        coverage_gaps: Optional[List[Dict[str, Any]]] = None,
        cleanup_issues: Optional[List[str]] = None,
        requirement_mode: str = "",
    ) -> Dict[str, Any]:
        req_rows = current_REQ if current_REQ is not None else self.requirement_context(artifact)
        url_rows = current_URL if current_URL is not None else self.scope_requirement_context(artifact)
        return {
            "issue": {
                "id": issue.get("id"),
                "meeting_id": issue.get("meeting_id"),
                "title": issue.get("title"),
                "category": issue.get("category"),
                "trace": issue.get("trace", {}),
            },
            "current_URL": url_rows,
            "current_REQ": req_rows,
            "scope": artifact.get("scope") if isinstance(artifact.get("scope"), dict) else {},
            "feedback": self.feedback_context(artifact.get("feedback")),
            "system_models": self.system_model_context(artifact),
            "discussion": self.scope_discussion_context(previous_responses),
            "req_source_index": self.requirement_source_index(req_rows),
            "current_req_count": len(req_rows),
            "mode": requirement_mode,
            "coverage_gaps": coverage_gaps or [],
            "cleanup_issues": cleanup_issues or [],
        }

    def apply_requirement_action_output(
        self,
        *,
        artifact: Dict[str, Any],
        data: Dict[str, Any],
        action_name: str,
        source_id: str,
    ) -> List[Dict[str, Any]]:
        self.validate_requirement_action_references(
            artifact=artifact,
            data=data,
            action_name=action_name,
            source_id=source_id,
        )
        generated = self.clean_requirement_records(
            data.get("REQ"),
            existing=artifact.get("REQ", []),
        )
        if generated:
            merged = self.merge_requirement_records(
                artifact.get("REQ", []),
                generated,
            )
            artifact["REQ"] = self.dedupe_candidate_requirement_rows(merged)
            meta = artifact.setdefault("meta", {})
            meta["requirements_changed"] = True
            meta["requirements_changed_by"] = source_id
            meta["requirements_changed_reason"] = action_name
        if action_name in {"update_requirement", "refine_requirement"} and isinstance(data, dict):
            removed = self.remove_merged_requirement_records(
                artifact,
                data.get("remove_REQ"),
                generated,
            )
            if removed:
                meta = artifact.setdefault("meta", {})
                meta["requirements_changed"] = True
                meta["requirements_changed_by"] = source_id
                meta["requirements_changed_reason"] = action_name
        return generated

    def validate_requirement_action_references(
        self,
        *,
        artifact: Dict[str, Any],
        data: Dict[str, Any],
        action_name: str,
        source_id: str,
    ) -> None:
        existing_rows = [
            row for row in (artifact.get("REQ") or []) if isinstance(row, dict)
        ]
        existing_req_ids = {
            str(row.get("id") or "").strip()
            for row in existing_rows
            if str(row.get("id") or "").strip()
        }
        valid_sources = self.requirement_context_refs(artifact)
        valid_sources.discard("")
        for row in existing_rows:
            valid_sources.update(self.requirement_sources(row))
        if source_id:
            valid_sources.add(source_id)

        generated_ids = set()
        for index, row in enumerate(data.get("REQ") or []):
            if not isinstance(row, dict):
                continue
            req_id = str(row.get("id") or "").strip()
            if req_id:
                if req_id not in existing_req_ids:
                    raise ValueError(
                        f"{action_name} REQ[{index}] references unknown id: {req_id}"
                    )
                generated_ids.add(req_id)
            sources = self.requirement_sources(row)
            if not sources:
                raise ValueError(
                    f"{action_name} REQ[{index}] must reference at least one source"
                )
            unknown_sources = sorted(
                source for source in sources if source not in valid_sources
            )
            if unknown_sources:
                raise ValueError(
                    f"{action_name} REQ[{index}] references unknown source: "
                    + ", ".join(unknown_sources)
                )

        remove_rows = data.get("remove_REQ") or []
        if not isinstance(remove_rows, list):
            raise ValueError(f"{action_name} remove_REQ must be a list")
        remove_ids = [str(item or "").strip() for item in remove_rows if str(item or "").strip()]
        unknown_remove_ids = sorted(set(remove_ids) - existing_req_ids)
        if unknown_remove_ids:
            raise ValueError(
                f"{action_name} remove_REQ references unknown id: "
                + ", ".join(unknown_remove_ids)
            )
        conflicting_ids = sorted(set(remove_ids) & generated_ids)
        if conflicting_ids:
            raise ValueError(
                f"{action_name} cannot update and remove the same REQ: "
                + ", ".join(conflicting_ids)
            )

    @staticmethod
    def validate_coverage_references(
        artifact: Dict[str, Any],
        rows: Any,
        *,
        removed_req_ids: Optional[List[str]] = None,
    ) -> None:
        if not isinstance(rows, list):
            raise ValueError("coverage must be a list")
        url_ids = {
            str(row.get("id") or "").strip()
            for row in (artifact.get("URL") or [])
            if isinstance(row, dict) and str(row.get("id") or "").strip()
        }
        req_ids = {
            str(row.get("id") or "").strip()
            for row in (artifact.get("REQ") or [])
            if isinstance(row, dict) and str(row.get("id") or "").strip()
        }
        removed = {str(item or "").strip() for item in (removed_req_ids or []) if str(item or "").strip()}
        for index, row in enumerate(rows):
            if not isinstance(row, dict):
                raise ValueError(f"coverage[{index}] must be an object")
            source_id = str(row.get("source_id") or "").strip()
            if source_id not in url_ids:
                raise ValueError(f"coverage[{index}] references unknown URL: {source_id or '<empty>'}")
            covered_by = row.get("covered_by") or []
            if not isinstance(covered_by, list):
                raise ValueError(f"coverage[{index}].covered_by must be a list")
            refs = {str(item or "").strip() for item in covered_by if str(item or "").strip()}
            unknown_req_ids = sorted(refs - req_ids)
            if unknown_req_ids:
                raise ValueError(
                    f"coverage[{index}] references unknown REQ: "
                    + ", ".join(unknown_req_ids)
                )
            removed_refs = sorted(refs & removed)
            if removed_refs:
                raise ValueError(
                    f"coverage[{index}] references removed REQ: "
                    + ", ".join(removed_refs)
                )

    @staticmethod
    def requirement_payload(data: Any, *, action_name: str) -> Dict[str, Any]:
        if not isinstance(data, dict):
            raise ValueError(f"{action_name} output must be an object")
        payload = data
        for key in ("REQ", "coverage"):
            if key in payload and not isinstance(payload.get(key), list):
                raise ValueError(f"{action_name} {key} must be a list")
        return payload

    def update_requirement(
        self,
        *,
        artifact: Dict[str, Any],
        issue: Dict[str, Any],
        previous_responses: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        working_artifact = copy.deepcopy(artifact)
        current_REQ = self.requirement_context(working_artifact)
        current_URL = self.scope_requirement_context(working_artifact)
        source_id = str(issue.get("meeting_id") or issue.get("id") or "").strip()
        generated_all: List[Dict[str, Any]] = []
        final_coverage: List[Dict[str, Any]] = self.requirement_coverage_records(
            working_artifact,
            [],
        )
        reasons: List[str] = []
        coverage_decisions: Dict[str, Dict[str, Any]] = {}
        coverage_gaps: List[Dict[str, Any]] = self.coverage_gaps(
            final_coverage,
            current_URL,
        )
        max_passes = (
            REQUIREMENT_COVERAGE_BATCH_LIMIT
            if coverage_gaps
            else REQUIREMENT_UPDATE_LIMIT
        )
        attempts = 0
        for pass_index in range(max_passes):
            attempts += 1
            current_REQ = self.requirement_context(working_artifact)
            requirement_mode = "update" if current_REQ else "create"
            active_gaps = (
                coverage_gaps[:REQUIREMENT_COVERAGE_BATCH_SIZE]
                if coverage_gaps
                else []
            )
            context_URL = active_gaps if active_gaps else current_URL
            context_REQ = (
                self.relevant_requirement_context(current_REQ, context_URL, issue)
                if active_gaps
                else current_REQ
            )
            context = self.requirement_action_context(
                artifact=working_artifact,
                issue=issue,
                previous_responses=previous_responses,
                current_URL=context_URL,
                current_REQ=context_REQ,
                coverage_gaps=active_gaps,
                requirement_mode=requirement_mode,
            )
            if active_gaps:
                context["feedback"] = self.relevant_feedback_context(
                    context.get("feedback") or {},
                    context_URL,
                    context_REQ,
                    issue,
                )
                context["system_models"] = self.relevant_system_model_context(
                    context.get("system_models") or [],
                    context_URL,
                    context_REQ,
                    issue,
                )
            context["pass"] = pass_index + 1
            task = self.update_requirement_task(
                requirement_mode=requirement_mode,
                source_id=source_id,
                coverage_gaps=active_gaps,
            )
            data = self.invoke_requirements_analyst_object_json(
                task,
                context,
                mode="update_requirement",
            )
            data = self.requirement_payload(
                data,
                action_name="update_requirement",
            )
            data = self.repair_requirement_output(
                data=data,
                context=context,
                action_name="update_requirement",
            )
            generated = self.apply_requirement_action_output(
                artifact=working_artifact,
                data=data,
                action_name="update_requirement",
                source_id=source_id,
            )
            generated_all.extend(generated)
            reason = str((data or {}).get("reason") or "").strip()
            if reason:
                reasons.append(reason)
            final_coverage = self.requirement_coverage_records(working_artifact, [])
            active_coverage_gaps = self.coverage_gaps(final_coverage, context_URL)
            if active_coverage_gaps:
                coverage_REQ = self.relevant_requirement_context(
                    self.requirement_context(working_artifact),
                    active_coverage_gaps,
                    issue,
                )
                coverage_context = self.requirement_action_context(
                    artifact=working_artifact,
                    issue=issue,
                    previous_responses=previous_responses,
                    current_URL=active_coverage_gaps,
                    current_REQ=coverage_REQ,
                    coverage_gaps=active_coverage_gaps,
                    requirement_mode="coverage",
                )
                coverage_data = self.invoke_requirements_analyst_object_json(
                    self.update_requirement_coverage_task(),
                    coverage_context,
                    mode="update_requirement_coverage",
                )
                coverage_rows = coverage_data.get("coverage")
                coverage_issues = self.requirement_coverage_batch_issues(
                    coverage_rows,
                    active_coverage_gaps,
                )
                if coverage_issues:
                    raise RuntimeError(
                        "update_requirement coverage output invalid: "
                        + "; ".join(coverage_issues)
                    )
                self.validate_coverage_references(
                    working_artifact,
                    coverage_rows,
                    removed_req_ids=data.get("remove_REQ") or [],
                )
                for row in coverage_rows:
                    source_id = str(row.get("source_id") or "").strip()
                    if source_id:
                        coverage_decisions[source_id] = copy.deepcopy(row)
                final_coverage = self.requirement_coverage_records(
                    working_artifact,
                    list(coverage_decisions.values()),
                )
            coverage_gaps = self.coverage_gaps(final_coverage, current_URL)
            if not coverage_gaps:
                break
        if coverage_gaps:
            missing = ", ".join(
                str(row.get("source_id") or "").strip()
                for row in coverage_gaps
                if isinstance(row, dict) and str(row.get("source_id") or "").strip()
            )
            raise RuntimeError(
                "需求正式化來源追蹤仍未完成；"
                f"已重試 update_requirement {attempts} 次；"
                f"missing={missing or '<none>'}。需要 more_discussion 或 human decision。"
            )

        cleanup_result = self.cleanup_requirement_granularity(
            artifact=working_artifact,
            issue=issue,
            previous_responses=previous_responses,
            source_id=source_id,
            include_type_issues=False,
        )
        generated_all.extend(cleanup_result.get("REQ", []))
        final_coverage = self.requirement_coverage_records(
            working_artifact,
            list(coverage_decisions.values()),
        )
        renumber_mapping = renumber_system_requirement_ids(working_artifact)
        if renumber_mapping:
            generated_all = replace_system_requirement_refs(generated_all, renumber_mapping)
            cleanup_result = replace_system_requirement_refs(cleanup_result, renumber_mapping)
            final_coverage = self.requirement_coverage_records(
                working_artifact,
                list(coverage_decisions.values()),
            )
        artifact["REQ"] = copy.deepcopy(working_artifact.get("REQ", []))
        artifact["coverage"] = final_coverage
        artifact_meta = artifact.setdefault("meta", {})
        working_meta = working_artifact.get("meta") if isinstance(working_artifact.get("meta"), dict) else {}
        artifact_meta.update(working_meta)

        return {
            "action": "update_requirement",
            "REQ": generated_all,
            "coverage": final_coverage,
            "coverage_gaps": coverage_gaps,
            "coverage_summary": self.requirement_coverage_summary(final_coverage),
            "requirement_cleanup": cleanup_result,
            "reason": "；".join(reasons),
            "warnings": [],
            "source_id": source_id,
        }

    def cleanup_requirement_granularity(
        self,
        *,
        artifact: Dict[str, Any],
        issue: Dict[str, Any],
        previous_responses: Optional[List[Dict[str, Any]]],
        source_id: str,
        include_type_issues: bool = True,
    ) -> Dict[str, Any]:
        generated_all: List[Dict[str, Any]] = []
        reasons: List[str] = []
        attempts = 0
        cleanup_issues = self.requirement_cleanup_issues(
            artifact,
            include_type=include_type_issues,
        )
        while cleanup_issues and attempts < REQUIREMENT_REFINE_LIMIT:
            attempts += 1
            current_REQ = self.requirement_context(artifact)
            context = self.requirement_action_context(
                artifact=artifact,
                issue=issue,
                previous_responses=previous_responses,
                current_URL=self.scope_requirement_context(artifact),
                current_REQ=current_REQ,
                cleanup_issues=cleanup_issues,
                requirement_mode="refine_granularity_cleanup",
            )
            context["pass"] = attempts
            task = self.refine_requirement_task(source_id=source_id)
            data = self.invoke_requirements_analyst_object_json(
                task,
                context,
                mode="refine_requirement",
            )
            data = self.requirement_payload(
                data,
                action_name="refine_requirement",
            )
            data = self.repair_requirement_output(
                data=data,
                context=context,
                action_name="refine_requirement",
            )
            generated = self.apply_requirement_action_output(
                artifact=artifact,
                data=data,
                action_name="refine_requirement",
                source_id=source_id,
            )
            generated_all.extend(generated)
            reason = str((data or {}).get("reason") or "").strip()
            if reason:
                reasons.append(reason)
            cleanup_issues = self.requirement_cleanup_issues(
                artifact,
                include_type=include_type_issues,
            )

        if cleanup_issues:
            reasons.append(
                "需求正式化已完成；剩餘 REQ 粒度、類型或合併問題保留給 refine_requirement 議題處理。"
            )
        return {
            "action": "refine_requirement",
            "attempts": attempts,
            "REQ": generated_all,
            "remaining_cleanup_issues": cleanup_issues,
            "status": "needs_refine_requirement" if cleanup_issues else "completed",
            "reason": "；".join(reasons),
        }

    def refine_requirement(
        self,
        *,
        artifact: Dict[str, Any],
        issue: Dict[str, Any],
        previous_responses: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        working_artifact = copy.deepcopy(artifact)
        trace = issue.get("trace") if isinstance(issue.get("trace"), dict) else {}
        issue_source_ids = [
            str(item).strip()
            for item in (trace.get("artifact_ids") or [])
            if str(item).strip()
        ]
        allowed_sources = set(issue_source_ids)
        current_URL = [
            row
            for row in self.scope_requirement_context(working_artifact)
            if str(row.get("id") or "").strip() in allowed_sources
        ]
        current_REQ = self.requirement_context(working_artifact)
        context_REQ = self.relevant_requirement_context(current_REQ, current_URL, issue)
        source_id = str(issue.get("meeting_id") or issue.get("id") or "").strip()
        context = self.requirement_action_context(
            artifact=working_artifact,
            issue=issue,
            previous_responses=previous_responses,
            current_URL=current_URL,
            current_REQ=context_REQ,
            requirement_mode="refine",
        )
        feedback = context.get("feedback")
        if isinstance(feedback, dict):
            context["feedback"] = self.relevant_feedback_context(
                feedback,
                current_URL,
                context_REQ,
                issue,
            )
        system_models = context.get("system_models")
        if isinstance(system_models, list):
            context["system_models"] = self.relevant_system_model_context(
                system_models,
                current_URL,
                context_REQ,
                issue,
            )
        task = self.refine_requirement_task(source_id=source_id)
        data = self.invoke_requirements_analyst_object_json(
            task,
            context,
            mode="refine_requirement",
        )
        data = self.requirement_payload(
            data,
            action_name="refine_requirement",
        )
        data = self.repair_requirement_output(
            data=data,
            context=context,
            action_name="refine_requirement",
        )
        generated = self.apply_requirement_action_output(
            artifact=working_artifact,
            data=data,
            action_name="refine_requirement",
            source_id=source_id,
        )
        self.validate_coverage_references(
            working_artifact,
            data.get("coverage") if isinstance(data, dict) else [],
            removed_req_ids=data.get("remove_REQ") if isinstance(data, dict) else [],
        )
        renumber_mapping = renumber_system_requirement_ids(working_artifact)
        if renumber_mapping:
            generated = replace_system_requirement_refs(generated, renumber_mapping)
        final_coverage = self.requirement_coverage_records(
            working_artifact,
            data.get("coverage") if isinstance(data, dict) else [],
        )
        artifact["REQ"] = copy.deepcopy(working_artifact.get("REQ", []))
        artifact["coverage"] = copy.deepcopy(final_coverage)
        artifact_meta = artifact.setdefault("meta", {})
        working_meta = (
            working_artifact.get("meta")
            if isinstance(working_artifact.get("meta"), dict)
            else {}
        )
        artifact_meta.update(working_meta)
        return {
            "action": "refine_requirement",
            "REQ": generated,
            "coverage": final_coverage,
            "coverage_gaps": [],
            "coverage_summary": self.requirement_coverage_summary(final_coverage),
            "reason": str((data or {}).get("reason") or "").strip(),
            "warnings": [],
            "source_id": source_id,
        }

    @staticmethod
    def requirement_repair_target_indexes(
        rows: List[Dict[str, Any]], issues: List[str]
    ) -> List[int]:
        selected = set()
        ids = {
            str(row.get("id") or "").strip(): index
            for index, row in enumerate(rows)
            if isinstance(row, dict) and str(row.get("id") or "").strip()
        }
        for issue in issues:
            text = str(issue or "")
            for req_id, index in ids.items():
                if re.search(rf"(?<![\w-]){re.escape(req_id)}(?![\w-])", text):
                    selected.add(index)
            row_match = re.search(r"\brow-(\d+)\b", text, re.IGNORECASE)
            if row_match:
                index = int(row_match.group(1)) - 1
                if 0 <= index < len(rows):
                    selected.add(index)
            req_match = re.search(r"\bREQ\[(\d+)\]", text, re.IGNORECASE)
            if req_match:
                index = int(req_match.group(1))
                if 0 <= index < len(rows):
                    selected.add(index)
        return sorted(selected) if selected else list(range(len(rows)))

    @classmethod
    def requirement_repair_subset(
        cls, data: Dict[str, Any], issues: List[str]
    ) -> tuple[Dict[str, Any], List[int]]:
        rows = data.get("REQ") if isinstance(data.get("REQ"), list) else []
        indexes = cls.requirement_repair_target_indexes(rows, issues)
        subset = copy.deepcopy(data)
        subset["REQ"] = [copy.deepcopy(rows[index]) for index in indexes]
        return subset, indexes

    @staticmethod
    def merge_requirement_repair(
        original: Dict[str, Any], repaired: Dict[str, Any], indexes: List[int]
    ) -> Dict[str, Any]:
        original_rows = original.get("REQ") if isinstance(original.get("REQ"), list) else []
        repaired_rows = repaired.get("REQ") if isinstance(repaired.get("REQ"), list) else []
        if not indexes or not repaired_rows:
            return original
        targets = set(indexes)
        first = min(targets)
        merged_rows = []
        for index, row in enumerate(original_rows):
            if index == first:
                merged_rows.extend(copy.deepcopy(repaired_rows))
            if index not in targets:
                merged_rows.append(row)
        merged = copy.deepcopy(original)
        merged["REQ"] = merged_rows
        return merged

    def compact_requirement_repair_context(
        self, context: Dict[str, Any], subset: Dict[str, Any]
    ) -> Dict[str, Any]:
        compact = copy.deepcopy(context)
        rows = subset.get("REQ") if isinstance(subset.get("REQ"), list) else []
        source_ids = {
            str(source).strip()
            for row in rows
            if isinstance(row, dict)
            for source in (row.get("source") or [])
            if str(source).strip()
        }
        urls = context.get("current_URL") if isinstance(context.get("current_URL"), list) else []
        compact_urls = [
            row
            for row in urls
            if isinstance(row, dict)
            and str(row.get("id") or "").strip() in source_ids
        ]
        compact["current_URL"] = compact_urls
        compact["current_REQ"] = copy.deepcopy(rows)
        issue = context.get("issue") if isinstance(context.get("issue"), dict) else {}
        feedback = context.get("feedback")
        if isinstance(feedback, dict):
            compact["feedback"] = self.relevant_feedback_context(
                feedback, compact_urls, rows, issue
            )
        models = context.get("system_models")
        if isinstance(models, list):
            compact["system_models"] = self.relevant_system_model_context(
                models, compact_urls, rows, issue
            )
        return compact

    def invoke_targeted_requirement_repair(
        self,
        *,
        data: Dict[str, Any],
        context: Dict[str, Any],
        issues: List[str],
        repair_kind: str,
        action_name: str,
    ) -> Dict[str, Any]:
        subset, indexes = self.requirement_repair_subset(data, issues)
        issue_keys = {
            "title_repair": "title_issues",
            "nfr_repair": "nfr_issues",
            "type_repair": "mixed_issues",
            "targeted_repair": "mixed_issues",
        }
        repair_task = requirement_repair_prompt(
            repair_kind,
            **{issue_keys[repair_kind]: issues},
            output=subset,
        )
        repaired = self.invoke_requirements_analyst_object_json(
            repair_task,
            self.compact_requirement_repair_context(context, subset),
            mode="repair_requirement",
        )
        repaired = self.requirement_payload(repaired, action_name=action_name)
        return self.merge_requirement_repair(data, repaired, indexes)

    def repair_requirement_output(
        self,
        *,
        data: Dict[str, Any],
        context: Dict[str, Any],
        action_name: str,
    ) -> Dict[str, Any]:
        allowed_coverage_sources = {
            str(row.get("id") or "").strip()
            for row in (context.get("current_URL") or [])
            if isinstance(row, dict) and str(row.get("id") or "").strip()
        }
        coverage_issues = self.requirement_coverage_issues(
            data.get("coverage") if isinstance(data, dict) else [],
            allowed_source_ids=allowed_coverage_sources,
        )
        if coverage_issues:
            coverage_input = {
                "REQ": [],
                "remove_REQ": [],
                "coverage": copy.deepcopy(data.get("coverage", [])),
                "reason": str(data.get("reason") or ""),
            }
            repair_task = requirement_repair_prompt(
                "coverage_repair",
                coverage_issues=coverage_issues,
                output=coverage_input,
            )
            repaired = self.invoke_requirements_analyst_object_json(
                repair_task,
                context,
                mode="repair_requirement",
            )
            repaired = self.requirement_payload(
                repaired,
                action_name=f"{action_name} coverage repair",
            )
            data = copy.deepcopy(data)
            data["coverage"] = copy.deepcopy(repaired.get("coverage", []))
            coverage_issues = self.requirement_coverage_issues(
                data.get("coverage") if isinstance(data, dict) else [],
                allowed_source_ids=allowed_coverage_sources,
            )
            if coverage_issues:
                data["coverage"] = [
                    copy.deepcopy(row)
                    for row in (data.get("coverage") or [])
                    if isinstance(row, dict)
                    and str(row.get("source_id") or "").strip() in allowed_coverage_sources
                ]
                coverage_issues = self.requirement_coverage_issues(
                    data["coverage"],
                    allowed_source_ids=allowed_coverage_sources,
                )
                if coverage_issues:
                    raise RuntimeError(
                        f"{action_name} coverage repair failed: "
                        + "; ".join(coverage_issues)
                    )

        data = self.normalize_requirement_titles(
            data,
            stakeholder_names=self.requirement_title_stakeholders(context),
        )
        title_issues = self.requirement_title_issues(
            data.get("REQ") if isinstance(data, dict) else [],
            stakeholder_names=self.requirement_title_stakeholders(context),
        )
        if title_issues:
            data = self.invoke_targeted_requirement_repair(
                data=data,
                context=context,
                issues=title_issues,
                repair_kind="title_repair",
                action_name=f"{action_name} title repair",
            )
            data = self.normalize_requirement_titles(
                data,
                stakeholder_names=self.requirement_title_stakeholders(context),
            )
            title_issues = self.requirement_title_issues(
                data.get("REQ") if isinstance(data, dict) else [],
                stakeholder_names=self.requirement_title_stakeholders(context),
            )
            if title_issues:
                raise RuntimeError(
                    f"{action_name} requirement title repair failed: "
                    + "; ".join(title_issues)
                )

        nfr_issues = self.nfr_issues(
            data.get("REQ") if isinstance(data, dict) else []
        )
        if nfr_issues:
            data = self.invoke_targeted_requirement_repair(
                data=data,
                context=context,
                issues=nfr_issues,
                repair_kind="nfr_repair",
                action_name=f"{action_name} non-functional repair",
            )
            nfr_issues = self.nfr_issues(
                data.get("REQ") if isinstance(data, dict) else []
            )
            if nfr_issues:
                raise RuntimeError(
                    f"{action_name} non-functional field repair failed: "
                    + "; ".join(nfr_issues)
                )

        if isinstance(data, dict):
            data["REQ"] = self.dedupe_candidate_requirement_rows(
                self.normalize_generated_requirement_ids(data.get("REQ", []))
            )
        mixed_issues = self.type_issues(data.get("REQ") if isinstance(data, dict) else [])
        if mixed_issues and str(action_name).strip() == "update_requirement":
            warnings = data.setdefault("warnings", []) if isinstance(data, dict) else []
            if isinstance(warnings, list):
                warnings.extend(
                    {
                        "type": "requires_refine_requirement",
                        "message": issue,
                    }
                    for issue in mixed_issues
                )
            return data
        if mixed_issues:
            data = self.invoke_targeted_requirement_repair(
                data=data,
                context=context,
                issues=mixed_issues,
                repair_kind="type_repair",
                action_name=f"{action_name} type repair",
            )
            if isinstance(data, dict):
                data["REQ"] = self.dedupe_candidate_requirement_rows(
                    self.normalize_generated_requirement_ids(data.get("REQ", []))
                )
            mixed_issues = self.type_issues(data.get("REQ") if isinstance(data, dict) else [])
            if mixed_issues:
                data = self.invoke_targeted_requirement_repair(
                    data=data,
                    context=context,
                    issues=mixed_issues,
                    repair_kind="targeted_repair",
                    action_name=f"{action_name} targeted repair",
                )
                if isinstance(data, dict):
                    data["REQ"] = self.dedupe_candidate_requirement_rows(
                        self.normalize_generated_requirement_ids(data.get("REQ", []))
                    )
                mixed_issues = self.type_issues(data.get("REQ") if isinstance(data, dict) else [])
                if mixed_issues:
                    if isinstance(data, dict):
                        data["REQ"] = self.dedupe_candidate_requirement_rows(
                            self.coerce_mixed_requirement_rows(
                                self.normalize_generated_requirement_ids(data.get("REQ", []))
                            )
                        )
                    mixed_issues = self.type_issues(data.get("REQ") if isinstance(data, dict) else [])
                    if mixed_issues:
                        raise RuntimeError(
                            f"{action_name} targeted mixed requirement repair failed: "
                            + "; ".join(mixed_issues)
                        )
        return data

    def update_requirement_task(
        self,
        *,
        requirement_mode: str,
        source_id: str,
        coverage_gaps: Optional[List[Dict[str, Any]]] = None,
    ) -> str:
        return update_requirement(
            requirement_mode=requirement_mode,
            source_id=source_id,
            coverage_gaps=coverage_gaps,
        )

    @staticmethod
    def update_requirement_coverage_task() -> str:
        return update_requirement_coverage()

    def refine_requirement_task(
        self,
        *,
        source_id: str,
    ) -> str:
        return refine_requirement(source_id=source_id)

    @staticmethod
    def scope_requirement_context(artifact: Dict[str, Any]) -> List[Dict[str, Any]]:
        rows = artifact.get("URL") if isinstance(artifact.get("URL"), list) else []
        out: List[Dict[str, Any]] = []
        for row in rows or []:
            if not isinstance(row, dict):
                continue
            if str(row.get("status") or "").strip().lower() == "superseded":
                continue
            item: Dict[str, Any] = {}
            for key in ("id", "text", "source", "source_id", "resolution_reason"):
                value = row.get(key)
                if value not in (None, "", [], {}):
                    item[key] = value
            stakeholder = row.get("stakeholder")
            if isinstance(stakeholder, dict):
                name = str(stakeholder.get("name") or "").strip()
                if name:
                    item["stakeholder"] = name
            if item.get("text"):
                out.append(item)
        return out

    @staticmethod
    def scope_discussion_context(previous_responses: Optional[List[Dict[str, Any]]]) -> List[Dict[str, str]]:
        rows: List[Dict[str, str]] = []
        for row in previous_responses or []:
            if not isinstance(row, dict):
                continue
            response = row.get("response") if isinstance(row.get("response"), dict) else {}
            text = str(response.get("text") or "").strip()
            if not text:
                continue
            rows.append({
                "agent": str(row.get("agent") or "").strip(),
                "text": text,
            })
        return rows

    @staticmethod
    def feedback_context(feedback: Any) -> Dict[str, List[Dict[str, Any]]]:
        if not isinstance(feedback, dict):
            return {}
        out: Dict[str, List[Dict[str, Any]]] = {}
        for section in ("findings", "constraints", "risks", "recommendations"):
            rows: List[Dict[str, Any]] = []
            for row in (feedback.get(section) or []):
                if not isinstance(row, dict):
                    continue
                item: Dict[str, Any] = {}
                for key in ("id", "text", "source", "related_requirement_ids", "status"):
                    value = row.get(key)
                    if value not in (None, "", [], {}):
                        item[key] = value
                if item:
                    rows.append(item)
            if rows:
                out[section] = rows
        return out

    @staticmethod
    def system_model_context(artifact: Dict[str, Any]) -> List[Dict[str, Any]]:
        rows = artifact.get("system_models") if isinstance(artifact.get("system_models"), list) else []
        out: List[Dict[str, Any]] = []
        for row in (rows or []):
            if not isinstance(row, dict):
                continue
            item: Dict[str, Any] = {}
            for key in ("id", "name", "type", "description", "source"):
                value = row.get(key)
                if value not in (None, "", [], {}):
                    item[key] = value
            text_rows = row.get("text")
            if isinstance(text_rows, list) and text_rows:
                item["use_case_count"] = len(text_rows)
            if item:
                out.append(item)
        return out

    @staticmethod
    def requirement_context(artifact: Dict[str, Any]) -> List[Dict[str, Any]]:
        rows = artifact.get("REQ") if isinstance(artifact.get("REQ"), list) else []
        return [
            AnalystRequirementFlow.requirement_record(row)
            for row in rows
            if isinstance(row, dict)
        ]

    @staticmethod
    def requirement_source_index(rows: List[Dict[str, Any]]) -> Dict[str, List[str]]:
        index: Dict[str, List[str]] = {}
        if not isinstance(rows, list):
            return index
        for row in rows:
            if not isinstance(row, dict):
                continue
            req_id = str(row.get("id") or "").strip()
            if not req_id:
                continue
            for source_id in AnalystRequirementFlow.requirement_sources(row):
                source = str(source_id).strip()
                if not source:
                    continue
                bucket = index.setdefault(source, [])
                if req_id not in bucket:
                    bucket.append(req_id)
        return index

    @staticmethod
    def next_requirement_id(rows: List[Dict[str, Any]]) -> str:
        prefix = "REQ"
        max_num = 0
        for row in rows or []:
            rid = str(row.get("id") or "").strip()
            if not rid.startswith(f"{prefix}-"):
                continue
            try:
                max_num = max(max_num, int(rid[len(prefix) + 1:]))
            except ValueError:
                continue
        return f"{prefix}-{max_num + 1}"

    @staticmethod
    def requirement_key(row: Dict[str, Any]) -> str:
        description = str(row.get("description") or "").strip()
        sources = ",".join(AnalystRequirementFlow.requirement_sources(row))
        return requirement_dedupe_key(f"{description}|{sources}")

    @staticmethod
    def dedupe_candidate_requirement_rows(rows: Any) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        seen_keys: set[str] = set()
        source_rows: Dict[str, List[Dict[str, Any]]] = {}
        for row in rows or []:
            if not isinstance(row, dict):
                continue
            item = dict(row)
            description_key = requirement_dedupe_key(str(item.get("description") or ""))
            if not description_key:
                continue
            sources = [
                source_id
                for source_id in AnalystRequirementFlow.requirement_sources(item)
                if source_id.startswith("URL-")
            ]
            global_key = "|".join(sorted(sources)) + "|" + description_key
            if global_key in seen_keys:
                continue
            duplicate = False
            for source_id in sources:
                for existing in source_rows.get(source_id, []):
                    existing_key = requirement_dedupe_key(
                        str(existing.get("description") or "")
                    )
                    left_chars = {ch for ch in description_key if not ch.isspace()}
                    right_chars = {ch for ch in existing_key if not ch.isspace()}
                    if not left_chars or not right_chars:
                        continue
                    overlap = len(left_chars & right_chars) / max(
                        1,
                        min(len(left_chars), len(right_chars)),
                    )
                    if overlap >= 0.85:
                        duplicate = True
                        break
                if duplicate:
                    break
            if duplicate:
                continue
            out.append(item)
            seen_keys.add(global_key)
            for source_id in sources:
                source_rows.setdefault(source_id, []).append(item)
        return out

    @staticmethod
    def normalize_generated_requirement_ids(rows: Any) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        for row in rows or []:
            if not isinstance(row, dict):
                continue
            item = dict(row)
            rid = str(item.get("id") or "").strip()
            if rid and not re.fullmatch(r"REQ-\d+", rid):
                item.pop("id", None)
            out.append(item)
        return out

    @staticmethod
    def coerce_mixed_requirement_rows(rows: Any) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        for row in rows or []:
            if not isinstance(row, dict):
                continue
            out.append(dict(row))
        return out

    @staticmethod
    def requirement_coverage_issues(
        rows: Any,
        *,
        allowed_source_ids: Optional[set[str]] = None,
    ) -> List[str]:
        if not isinstance(rows, list):
            return []
        valid_statuses = {"covered", "needs_clarification", "assumption", "risk", "excluded"}
        issues: List[str] = []
        for idx, row in enumerate(rows, 1):
            if not isinstance(row, dict):
                issues.append(f"coverage[{idx}] 不是 object")
                continue
            source_id = str(row.get("source_id") or "").strip()
            status = str(row.get("status") or "").strip()
            if not source_id:
                issues.append(f"coverage[{idx}] 缺少 source_id")
            elif allowed_source_ids is not None and source_id not in allowed_source_ids:
                issues.append(f"coverage[{idx}] references unavailable URL: {source_id}")
            if status not in valid_statuses:
                issues.append(f"{source_id or f'coverage[{idx}]'}: status 不合法「{status or '<empty>'}」")
        return issues

    @classmethod
    def requirement_coverage_batch_issues(
        cls,
        rows: Any,
        current_URL: List[Dict[str, Any]],
    ) -> List[str]:
        if not isinstance(rows, list):
            return ["coverage 必須是 array"]
        issues = cls.requirement_coverage_issues(rows)
        expected = {
            str(row.get("id") or row.get("source_id") or "").strip()
            for row in current_URL or []
            if isinstance(row, dict)
            and str(row.get("id") or row.get("source_id") or "").strip()
        }
        actual: List[str] = [
            str(row.get("source_id") or "").strip()
            for row in rows
            if isinstance(row, dict) and str(row.get("source_id") or "").strip()
        ]
        duplicates = sorted({source_id for source_id in actual if actual.count(source_id) > 1})
        missing = sorted(expected - set(actual))
        unknown = sorted(set(actual) - expected)
        if duplicates:
            issues.append("coverage source_id 重複: " + ", ".join(duplicates))
        if missing:
            issues.append("coverage 缺少 source_id: " + ", ".join(missing))
        if unknown:
            issues.append("coverage 包含非本批 source_id: " + ", ".join(unknown))
        return issues


    @staticmethod
    def requirement_title_stakeholders(context: Any) -> List[str]:
        if not isinstance(context, dict):
            return []
        names: List[str] = []
        for key in ("current_URL", "URL"):
            for row in context.get(key) or []:
                if not isinstance(row, dict):
                    continue
                stakeholder = row.get("stakeholder")
                name = ""
                if isinstance(stakeholder, dict):
                    name = str(stakeholder.get("name") or "").strip()
                else:
                    name = str(stakeholder or "").strip()
                if len(name) >= 2:
                    names.append(name)
        return list(dict.fromkeys(names))

    @staticmethod
    def normalize_requirement_titles(
        data: Dict[str, Any],
        *,
        stakeholder_names: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        if not isinstance(data, dict):
            return data
        rows = data.get("REQ")
        if not isinstance(rows, list):
            return data
        prefixes = [
            str(name or "").strip()
            for name in (stakeholder_names or [])
            if len(str(name or "").strip()) >= 2
        ]
        if not prefixes:
            return data
        for row in rows:
            if not isinstance(row, dict):
                continue
            title = str(row.get("title") or "").strip()
            if not title:
                continue
            for prefix in prefixes:
                if not title.startswith(prefix):
                    continue
                next_title = title[len(prefix):].lstrip(" ：:，,、-－—")
                if next_title:
                    row["title"] = next_title
                break
        return data

    @staticmethod
    def requirement_title_issues(rows: Any, *, stakeholder_names: Optional[List[str]] = None) -> List[str]:
        if not isinstance(rows, list):
            return []
        prefixes = [
            str(name or "").strip()
            for name in (stakeholder_names or [])
            if len(str(name or "").strip()) >= 2
        ]
        issues: List[str] = []
        for idx, row in enumerate(rows, 1):
            if not isinstance(row, dict):
                continue
            req_id = str(row.get("id") or f"row-{idx}").strip()
            title = str(row.get("title") or "").strip()
            if not title:
                continue
            if any(term in title for term in ("系統應", "需要", "必須")):
                issues.append(f"{req_id}: title 像完整需求句「{title}」")
                continue
            if any(mark in title for mark in ("。", "，", "；")):
                issues.append(f"{req_id}: title 含句子標點「{title}」")
                continue
            if any(title.startswith(prefix) for prefix in prefixes):
                issues.append(f"{req_id}: title 以利害關係人作為前綴「{title}」")
        return issues





    @staticmethod
    def type_issues(rows: Any) -> List[str]:
        multi_intent_markers = ("且", "並且", "以及", "同時", "；", ";")
        issues: List[str] = []
        source_rows: Dict[str, List[Dict[str, Any]]] = {}
        for idx, row in enumerate(rows or [], 1):
            if not isinstance(row, dict):
                continue
            for source_id in AnalystRequirementFlow.requirement_sources(row):
                if source_id.startswith("URL-"):
                    source_rows.setdefault(source_id, []).append(row)
            req_type = str(row.get("type") or "").strip().lower().replace("_", "-")
            req_id = str(row.get("id") or f"REQ[{idx}]").strip()
            description = str(row.get("description") or "")
            marker_count = sum(1 for marker in multi_intent_markers if marker in description)
            if marker_count >= 2:
                issues.append(f"{req_id} 可能混有多核心意圖，請檢查是否需要拆分")
            if req_type == "non-functional":
                if not str(row.get("metric") or "").strip():
                    issues.append(f"{req_id} 是 non-functional，但缺少 metric")
                if not str(row.get("validation") or "").strip():
                    issues.append(f"{req_id} 是 non-functional，但缺少 validation")
        for source_id, mapped_rows in source_rows.items():
            if len(mapped_rows) < 2:
                continue
            for left_index, left in enumerate(mapped_rows):
                left_id = str(left.get("id") or "").strip() or f"{source_id}[{left_index + 1}]"
                left_text = requirement_dedupe_key(str(left.get("description") or ""))
                left_chars = {ch for ch in left_text if not ch.isspace()}
                if not left_chars:
                    continue
                for right in mapped_rows[left_index + 1:]:
                    right_id = str(right.get("id") or "").strip() or source_id
                    right_text = requirement_dedupe_key(str(right.get("description") or ""))
                    right_chars = {ch for ch in right_text if not ch.isspace()}
                    if not right_chars:
                        continue
                    overlap = len(left_chars & right_chars) / max(1, min(len(left_chars), len(right_chars)))
                    if overlap >= 0.85:
                        issues.append(
                            f"{source_id} 同時形成 {left_id} 與 {right_id}，但 description 高度重複；若要拆成多筆，必須有不同核心意圖"
                        )
        return issues

    @staticmethod
    def granularity_issues(rows: Any, current_URL: Any) -> List[str]:
        if not isinstance(rows, list) or not isinstance(current_URL, list):
            return []
        url_count = len([row for row in current_URL if isinstance(row, dict)])
        req_rows = [row for row in rows if isinstance(row, dict)]
        req_count = len(req_rows)
        if url_count < 8 or req_count < 8:
            return []
        single_source_count = 0
        for row in req_rows:
            url_sources = [
                source_id
                for source_id in AnalystRequirementFlow.requirement_sources(row)
                if source_id.startswith("URL-")
            ]
            if len(url_sources) == 1:
                single_source_count += 1
        issues: List[str] = []
        if req_count >= int(url_count * 0.9) and single_source_count >= int(req_count * 0.75):
            issues.append(
                "REQ 粒度疑似過細：REQ 數量接近 URL 數量，且多數 REQ 只追蹤單一 URL；"
                "請依同一 stakeholder、同一系統能力、同一限制或品質面向合併，保留多個 URL source。"
            )
        return issues

    @classmethod
    def requirement_cleanup_issues(
        cls,
        artifact: Dict[str, Any],
        *,
        include_type: bool = True,
    ) -> List[str]:
        rows = cls.requirement_context(artifact)
        current_URL = cls.scope_requirement_context(artifact)
        issues = []
        if include_type:
            issues.extend(cls.type_issues(rows))
        issues.extend(cls.granularity_issues(rows, current_URL))
        return issues

    @staticmethod
    def nfr_issues(rows: Any) -> List[str]:
        issues: List[str] = []
        for idx, row in enumerate(rows or [], 1):
            if not isinstance(row, dict):
                continue
            req_type = str(row.get("type") or "").strip().lower().replace("_", "-")
            if req_type != "non-functional":
                continue
            req_id = str(row.get("id") or f"REQ[{idx}]").strip()
            missing: List[str] = []
            if not str(row.get("category") or "").strip():
                missing.append("category")
            if not str(row.get("metric") or "").strip():
                missing.append("metric")
            if not str(row.get("validation") or "").strip():
                missing.append("validation")
            if missing:
                issues.append(f"{req_id} 的 {', '.join(missing)} 未填")
        return issues

    @staticmethod
    def requirement_sources(row: Dict[str, Any]) -> List[str]:
        source_rows: List[str] = []
        value = row.get("source") if isinstance(row, dict) else None
        if isinstance(value, list):
            source_rows.extend(str(item).strip() for item in value if str(item).strip())
        else:
            text = str(value or "").strip()
            if text:
                source_rows.append(text)
        return list(dict.fromkeys(source_rows))

    @staticmethod
    def requirement_record(row: Dict[str, Any]) -> Dict[str, Any]:
        source = row if isinstance(row, dict) else {}
        out: Dict[str, Any] = {}
        placeholder_values = {
            "待確認",
            "未確認",
            "待補",
            "目前無資料",
            "無",
            "none",
            "n/a",
            "-",
        }
        for key in (
            "id",
            "title",
            "description",
            "rationale",
        ):
            value = str(source.get(key) or "").strip()
            if key == "id" and value and not re.fullmatch(r"REQ-\d+", value):
                value = ""
            if key == "rationale" and value.lower() in placeholder_values:
                value = ""
            if value:
                out[key] = value
        req_type = str(source.get("type") or "").strip().lower().replace("_", "-")
        if req_type in {"functional", "non-functional", "constraint"}:
            out["type"] = req_type
        if req_type == "non-functional":
            for key in ("category", "metric", "validation"):
                value = str(source.get(key) or "").strip()
                if value and value.lower() not in placeholder_values:
                    out[key] = value
        priority = str(source.get("priority") or "").strip().lower()
        if req_type != "constraint" and priority in {"must", "should", "could"}:
            out["priority"] = priority
        sources = AnalystRequirementFlow.requirement_sources(source)
        if sources:
            out["source"] = sources
        for key in (
            "acceptance_criteria",
            "dependencies",
            "risks",
            "assumptions",
        ):
            value = source.get(key)
            if isinstance(value, list):
                rows = [str(item).strip() for item in value if str(item).strip()]
            else:
                text = str(value or "").strip()
                rows = [text] if text else []
            if key in {"acceptance_criteria", "dependencies", "risks", "assumptions"}:
                rows = [
                    item for item in rows
                    if item.strip().lower() not in placeholder_values
                ]
            out[key] = list(dict.fromkeys(rows))
        return out

    def clean_requirement_records(
        self,
        rows: Any,
        *,
        existing: Any,
    ) -> List[Dict[str, Any]]:
        existing_rows = [
            self.requirement_record(row)
            for row in existing or []
            if isinstance(row, dict)
        ]
        existing_ids = {
            str(row.get("id") or "").strip()
            for row in existing_rows
            if str(row.get("id") or "").strip()
        }
        seen = {
            self.requirement_key(row)
            for row in existing_rows
            if self.requirement_key(row)
        }
        out: List[Dict[str, Any]] = []
        for row in rows or []:
            if not isinstance(row, dict):
                continue
            item = self.requirement_record(row)
            if not item.get("description") or not item.get("source"):
                continue
            item_id = str(item.get("id") or "").strip()
            if item_id and item_id in existing_ids:
                out.append(item)
                continue
            marker = self.requirement_key(item)
            if not marker or marker in seen:
                continue
            item["id"] = self.next_requirement_id(existing_rows + out)
            out.append(item)
            seen.add(marker)
        return out

    def merge_requirement_records(
        self,
        existing: Any,
        generated: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        rows = [
            self.requirement_record(row)
            for row in existing or []
            if isinstance(row, dict)
        ]
        by_id = {
            str(row.get("id") or "").strip(): idx
            for idx, row in enumerate(rows)
            if str(row.get("id") or "").strip()
        }
        seen = {
            self.requirement_key(row)
            for row in rows
            if self.requirement_key(row)
        }
        for item in generated:
            item_id = str(item.get("id") or "").strip()
            if item_id and item_id in by_id:
                rows[by_id[item_id]] = self.requirement_record(item)
                continue
            marker = self.requirement_key(item)
            if marker and marker not in seen:
                rows.append(item)
                seen.add(marker)
        return rows

    def remove_merged_requirement_records(
        self,
        artifact: Dict[str, Any],
        remove_ids: Any,
        generated: List[Dict[str, Any]],
    ) -> List[str]:
        if not isinstance(remove_ids, list):
            return []
        requested = {
            str(item).strip()
            for item in remove_ids
            if str(item).strip().startswith("REQ-")
        }
        if not requested:
            return []
        target_ids = {
            str(row.get("id") or "").strip()
            for row in generated or []
            if isinstance(row, dict) and str(row.get("id") or "").strip()
        }
        requested -= target_ids
        if not requested:
            return []
        rows = [
            row
            for row in (artifact.get("REQ") or [])
            if isinstance(row, dict)
        ]
        removable: set[str] = set()
        for row in rows:
            req_id = str(row.get("id") or "").strip()
            if req_id not in requested:
                continue
            url_sources = [
                source_id
                for source_id in self.requirement_sources(row)
                if source_id.startswith("URL-")
            ]
            if not url_sources:
                continue
            covered_elsewhere = True
            for source_id in url_sources:
                has_cover = any(
                    str(other.get("id") or "").strip() != req_id
                    and source_id in self.requirement_sources(other)
                    for other in rows
                    if isinstance(other, dict)
                )
                if not has_cover:
                    covered_elsewhere = False
                    break
            if covered_elsewhere:
                removable.add(req_id)
        if not removable:
            return []
        remaining = [
            row
            for row in rows
            if str(row.get("id") or "").strip() not in removable
        ]
        removed = [
            str(row.get("id") or "").strip()
            for row in rows
            if str(row.get("id") or "").strip() in removable
        ]
        if removed:
            artifact["REQ"] = remaining
        return removed

    def requirement_coverage_records(
        self,
        artifact: Dict[str, Any],
        raw_coverage: Any,
    ) -> List[Dict[str, Any]]:
        valid_statuses = {"covered", "needs_clarification", "assumption", "risk", "excluded"}
        url_ids = [
            str(row.get("id") or "").strip()
            for row in (artifact.get("URL") or [])
            if isinstance(row, dict) and str(row.get("id") or "").strip()
        ]
        req_ids = {
            str(row.get("id") or "").strip()
            for row in (artifact.get("REQ") or [])
            if isinstance(row, dict) and str(row.get("id") or "").strip()
        }
        by_source: Dict[str, Dict[str, Any]] = {}
        if isinstance(raw_coverage, list):
            for row in raw_coverage:
                if not isinstance(row, dict):
                    continue
                source_id = str(row.get("source_id") or "").strip()
                if not source_id:
                    continue
                status = str(row.get("status") or "").strip()
                if status not in valid_statuses:
                    raise ValueError(f"coverage status invalid: {source_id} -> {status or '<empty>'}")
                covered_by = [
                    str(item).strip()
                    for item in (row.get("covered_by") or [])
                    if str(item).strip() in req_ids
                ]
                by_source[source_id] = {
                    "source_id": source_id,
                    "status": "covered" if covered_by else status,
                    "covered_by": covered_by,
                    "reason": str(row.get("reason") or "").strip(),
                }

        req_coverage: Dict[str, List[str]] = {}
        for req in artifact.get("REQ") or []:
            if not isinstance(req, dict):
                continue
            req_id = str(req.get("id") or "").strip()
            if not req_id:
                continue
            for source_id in self.requirement_sources(req):
                sid = str(source_id or "").strip()
                if sid:
                    req_coverage.setdefault(sid, []).append(req_id)

        coverage: List[Dict[str, Any]] = []
        for source_id in url_ids:
            covered_by = list(dict.fromkeys(req_coverage.get(source_id, [])))
            existing = by_source.get(source_id, {})
            status = "covered" if covered_by else str(existing.get("status") or "uncovered")
            reason = str(existing.get("reason") or "").strip()
            if not covered_by and not reason:
                reason = "此 User Requirement 尚未被任何 REQ.source 覆蓋。"
            coverage.append(
                {
                    "source_id": source_id,
                    "status": status,
                    "covered_by": covered_by,
                    "reason": reason,
                }
            )
        return coverage

    @staticmethod
    def requirement_coverage_summary(coverage: List[Dict[str, Any]]) -> Dict[str, int]:
        summary = {
            "total": 0,
            "covered": 0,
            "needs_clarification": 0,
            "assumption": 0,
            "risk": 0,
            "excluded": 0,
            "uncovered": 0,
            "unresolved": 0,
        }
        for row in coverage or []:
            if not isinstance(row, dict):
                continue
            summary["total"] += 1
            status = str(row.get("status") or "").strip()
            if status in summary:
                summary[status] += 1
            else:
                summary["unresolved"] += 1
        return summary

    @staticmethod
    def coverage_gaps(
        coverage: List[Dict[str, Any]],
        current_URL: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        by_id = {
            str(row.get("id") or "").strip(): row
            for row in current_URL or []
            if isinstance(row, dict) and str(row.get("id") or "").strip()
        }
        gaps: List[Dict[str, Any]] = []
        for row in coverage or []:
            if not isinstance(row, dict):
                continue
            source_id = str(row.get("source_id") or "").strip()
            if not source_id or row.get("covered_by"):
                continue
            status = str(row.get("status") or "").strip()
            reason = str(row.get("reason") or "").strip()
            if status in {"needs_clarification", "excluded", "assumption", "risk"} and reason:
                continue
            source = by_id.get(source_id, {})
            gaps.append(
                {
                    "id": source_id,
                    "source_id": source_id,
                    "text": str(source.get("text") or "").strip(),
                    "stakeholder": source.get("stakeholder"),
                    "reason": reason,
                }
            )
        return gaps

    def merge_meeting_requirements(
        self,
        artifact: Dict[str, Any],
        output: Any,
        *,
        issue: Dict[str, Any],
    ) -> None:
        requirements = self.requirement_candidate_rows(output)
        if not isinstance(requirements, list) or not requirements:
            return
        existing = [
            dict(row)
            for row in (artifact.get("URL", []) or [])
            if isinstance(row, dict)
        ]
        seen = {
            requirement_dedupe_key(row.get("text"))
            for row in existing
            if str(row.get("text") or "").strip()
        }
        added = []
        source_id = str(issue.get("meeting_id") or issue.get("id") or "").strip()
        for row in requirements:
            if not isinstance(row, dict):
                continue
            text = str(row.get("text") or "").strip()
            if not text:
                continue
            marker = requirement_dedupe_key(text)
            if marker in seen:
                continue
            candidate = dict(row)
            candidate.pop("id", None)
            candidate["text"] = text
            candidate["source"] = "meeting"
            if source_id:
                candidate["source_id"] = source_id
            added.append(candidate)
            seen.add(marker)
        if not added:
            if isinstance(output, dict):
                output["requirements"] = []
            elif isinstance(output, list):
                output.clear()
            return
        merged = ensure_requirement_candidate_ids(existing + added)
        artifact["URL"] = merged
        meta = artifact.setdefault("meta", {})
        previous_status = meta.get("requirements_review_status")
        previous_by = meta.get("requirements_review_by")
        previous_round = meta.get("requirements_review_round")
        previous_cycle = meta.get("requirements_review_cycle")
        if previous_status:
            meta["previous_requirements_review"] = {
                "status": previous_status,
                "by": previous_by,
                "round": previous_round,
                "cycle": previous_cycle,
            }
        meta.pop("requirements_review_status", None)
        meta.pop("requirements_review_by", None)
        meta.pop("requirements_review_round", None)
        meta["review_invalid_by"] = source_id
        meta["requirements_changed"] = True
        meta["requirements_changed_by"] = source_id
        meta["requirements_changed_reason"] = "analyze_requirements"
        added_rows = merged[-len(added):]
        if isinstance(output, dict):
            output["requirements"] = added_rows
        elif isinstance(output, list):
            output[:] = added_rows

    def analyze_conflicts(
        self,
        *,
        artifact: Dict[str, Any],
        last_result: Optional[Dict[str, Any]] = None,
        force: bool = False,
    ) -> Dict[str, Any]:
        from storage.artifact import (
            conflict_payload,
            reindex_conflict_report_rows,
            unresolved_conflict_report_rows,
        )

        previous_action_result = last_result if isinstance(last_result, dict) else {}
        if isinstance(previous_action_result.get("action_result"), dict):
            previous_action_result = previous_action_result.get("action_result") or {}
        meta = artifact.get("meta") if isinstance(artifact.get("meta"), dict) else {}
        candidate_output = previous_action_result.get("output")
        if candidate_output in (None, "", [], {}):
            candidate_output = previous_action_result.get("requirements")
        has_new_requirements = self.has_requirement_candidates(candidate_output)
        if not force and not bool(meta.get("requirements_changed")) and not has_new_requirements:
            return {
                "action": "analyze_conflicts",
                "skipped": True,
                "reason": "沒有由 analyze_requirements 產生新需求或需求變更候選，略過衝突重新辨識。",
                "conflict_report": [],
            }

        steps = []
        current = copy.deepcopy(artifact)
        for step_action, record_action in (
            ("detect_pair_conflicts", "detect_pair_conflicts"),
            ("detect_group_conflicts", "detect_group_conflicts"),
        ):
            current = self.run_conflict_analysis_loop(step_action, artifact=current)
            steps.append(
                {
                    "action": record_action,
                    "summary": f"完成 {record_action}",
                }
            )

        previous_report = (
            artifact.get("conflict", {}).get("report", [])
            if isinstance(artifact.get("conflict"), dict)
            else []
        )
        resolved_signatures = set()
        if isinstance(artifact.get("conflict"), dict):
            resolved_signatures = {
                str(value).strip()
                for value in (artifact.get("conflict", {}).get("resolved_signatures") or [])
                if str(value).strip()
            }
        if isinstance(current, dict) and isinstance(current.get("conflict"), dict):
            current_report = current["conflict"].get("report")
            if previous_report:
                merged_report = list(previous_report)
                if isinstance(current_report, list) and current_report:
                    merged_report.extend(current_report)
                current["conflict"]["report"] = unresolved_conflict_report_rows(
                    merged_report,
                    resolved_signatures,
                )
            if resolved_signatures:
                current["conflict"]["resolved_signatures"] = sorted(resolved_signatures)
            artifact["conflict"] = current["conflict"]
        payload = conflict_payload(current if isinstance(current, dict) else artifact, include_report=True)
        report_rows = [
            row for row in (payload.get("report", []) or [])
            if isinstance(row, dict) and str(row.get("final_label") or "").strip() == "Conflict"
        ]
        report_rows = unresolved_conflict_report_rows(report_rows, resolved_signatures)
        report_rows = reindex_conflict_report_rows(report_rows)
        self.ensure_conflict_report_titles(report_rows, stage="analyze_conflicts")
        report_artifact = {
            **(current if isinstance(current, dict) else artifact),
            "conflict": {
                **payload,
                "report": report_rows,
            },
        }
        report_artifact = self.resolve_conflicts(report_artifact)
        steps.append(
            {
                "action": "resolve_conflicts",
                "summary": f"完成 resolve_conflicts：{len(report_rows)} 筆 Conflict",
            }
        )
        report_rows = [
            row for row in ((report_artifact.get("conflict", {}) or {}).get("report", []) or [])
            if isinstance(row, dict) and str(row.get("final_label") or "").strip() == "Conflict"
        ]
        report_rows = unresolved_conflict_report_rows(report_rows, resolved_signatures)
        report_rows = reindex_conflict_report_rows(report_rows)
        self.ensure_conflict_report_titles(report_rows, stage="analyze_conflicts")
        artifact["conflict"] = {
            **(artifact.get("conflict") if isinstance(artifact.get("conflict"), dict) else {}),
            **(report_artifact.get("conflict", payload) or {}),
            "report": report_rows,
        }
        if resolved_signatures:
            artifact["conflict"]["resolved_signatures"] = sorted(resolved_signatures)
        report_md = ""
        if report_rows:
            report_md = self.generate_conflict_report(
                {
                    "conflict_report": report_rows,
                }
            )
            steps.append(
                {
                    "action": "generate_conflict_report",
                    "summary": f"完成 generate_conflict_report：{len(report_rows)} 筆 Conflict",
                }
            )
        return {
            "action": "analyze_conflicts",
            "steps": steps,
            "conflict_report": report_rows,
            "conflict_report_markdown": report_md,
            "forced": bool(force or meta.get("requirements_changed")),
        }

    @staticmethod
    def has_requirement_candidates(output: Any) -> bool:
        return bool(AnalystRequirementFlow.requirement_candidate_rows(output))

    @staticmethod
    def requirement_candidate_rows(output: Any) -> List[Dict[str, Any]]:
        if isinstance(output, list):
            return [row for row in output if isinstance(row, dict)]
        if isinstance(output, dict):
            rows = output.get("requirements")
            if isinstance(rows, list):
                return [row for row in rows if isinstance(row, dict)]
        return []

    def meeting_requirement_sources(
        self,
        previous_responses: Optional[List[Dict[str, Any]]],
        issue: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        rows: List[Dict[str, Any]] = []
        for row in previous_responses or []:
            if not isinstance(row, dict):
                continue
            response = row.get("response") if isinstance(row.get("response"), dict) else {}
            text = str(response.get("text") or "").strip()
            if not text:
                continue
            agent_name = str(row.get("agent") or "").strip() or "stakeholder"
            speaking_as = response.get("speaking_as") or []
            if isinstance(speaking_as, str):
                speaking_as = [speaking_as]
            names = [
                str(name).strip()
                for name in speaking_as
                if str(name).strip()
            ]
            if not names and agent_name == "user":
                names = ["user"]
            if agent_name != "user" and not names:
                continue
            for name in names:
                rows.append(
                    {
                        "name": name,
                        "type": "meeting_stakeholder",
                        "text": [text],
                    }
                )
        if not rows:
            description = str(issue.get("description") or "").strip()
            if description:
                rows.append(
                    {
                        "name": "meeting_issue",
                        "type": "meeting_context",
                        "text": [description],
                    }
                )
        return rows
