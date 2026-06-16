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
from .actions.reqt.update import update_requirement
from .repair import requirement_repair_prompt


REQUIREMENT_UPDATE_LIMIT = 2
REQUIREMENT_REFINE_LIMIT = 2
REQUIREMENT_COVERAGE_BATCH_SIZE = 5
REQUIREMENT_COVERAGE_BATCH_LIMIT = 8


# Defines AnalystRequirementFlow class for this module workflow.
class AnalystRequirementFlow:
    # Defines execute update requirement function for this module workflow.
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

    # Defines execute refine requirement function for this module workflow.
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

    # Defines requirement action context function for this module workflow.
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

    # Defines apply requirement action output function for this module workflow.
    def apply_requirement_action_output(
        self,
        *,
        artifact: Dict[str, Any],
        data: Dict[str, Any],
        action_name: str,
        source_id: str,
    ) -> List[Dict[str, Any]]:
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

    @staticmethod
    # Defines requirement update payload function for this module workflow.
    def requirement_update_payload(data: Any, *, action_name: str) -> Dict[str, Any]:
        if not isinstance(data, dict) or not isinstance(data.get("requirement_update"), dict):
            raise ValueError(f"{action_name} output must contain requirement_update object")
        payload = data["requirement_update"]
        for key in ("REQ", "coverage"):
            if key in payload and not isinstance(payload.get(key), list):
                raise ValueError(f"{action_name} requirement_update.{key} must be a list")
        return payload

    # Defines update requirement function for this module workflow.
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
            context = self.requirement_action_context(
                artifact=working_artifact,
                issue=issue,
                previous_responses=previous_responses,
                current_URL=context_URL,
                current_REQ=current_REQ,
                coverage_gaps=active_gaps,
                requirement_mode=requirement_mode,
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
            data = self.requirement_update_payload(
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
            final_coverage = self.requirement_coverage_records(
                working_artifact,
                data.get("coverage") if isinstance(data, dict) else [],
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
        final_coverage = self.requirement_coverage_records(working_artifact, [])
        renumber_mapping = renumber_system_requirement_ids(working_artifact)
        if renumber_mapping:
            generated_all = replace_system_requirement_refs(generated_all, renumber_mapping)
            cleanup_result = replace_system_requirement_refs(cleanup_result, renumber_mapping)
            final_coverage = self.requirement_coverage_records(working_artifact, [])
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

    # Defines requirement granularity cleanup function for this module workflow.
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
            data = self.requirement_update_payload(
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

    # Defines refine requirement function for this module workflow.
    def refine_requirement(
        self,
        *,
        artifact: Dict[str, Any],
        issue: Dict[str, Any],
        previous_responses: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        trace = issue.get("trace") if isinstance(issue.get("trace"), dict) else {}
        issue_source_ids = [
            str(item).strip()
            for item in (trace.get("artifact_ids") or [])
            if str(item).strip()
        ]
        allowed_sources = set(issue_source_ids)
        current_URL = [
            row
            for row in self.scope_requirement_context(artifact)
            if str(row.get("id") or "").strip() in allowed_sources
        ]
        current_REQ = self.requirement_context(artifact)
        source_id = str(issue.get("meeting_id") or issue.get("id") or "").strip()
        context = self.requirement_action_context(
            artifact=artifact,
            issue=issue,
            previous_responses=previous_responses,
            current_URL=current_URL,
            current_REQ=current_REQ,
            requirement_mode="refine",
        )
        task = self.refine_requirement_task(source_id=source_id)
        data = self.invoke_requirements_analyst_object_json(
            task,
            context,
            mode="refine_requirement",
        )
        data = self.requirement_update_payload(
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
        renumber_mapping = renumber_system_requirement_ids(artifact)
        if renumber_mapping:
            generated = replace_system_requirement_refs(generated, renumber_mapping)
        final_coverage = self.requirement_coverage_records(
            artifact,
            data.get("coverage") if isinstance(data, dict) else [],
        )
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

    # Defines repair requirement output function for this module workflow.
    def repair_requirement_output(
        self,
        *,
        data: Dict[str, Any],
        context: Dict[str, Any],
        action_name: str,
    ) -> Dict[str, Any]:
        coverage_issues = self.requirement_coverage_issues(
            data.get("coverage") if isinstance(data, dict) else []
        )
        if coverage_issues:
            repair_task = requirement_repair_prompt(
                "coverage_repair",
                coverage_issues=coverage_issues,
                output=data,
            )
            data = self.invoke_requirements_analyst_object_json(
                repair_task,
                context,
                mode="repair_requirement",
            )
            data = self.requirement_update_payload(
                data,
                action_name=f"{action_name} coverage repair",
            )
            coverage_issues = self.requirement_coverage_issues(
                data.get("coverage") if isinstance(data, dict) else []
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
            repair_task = requirement_repair_prompt(
                "title_repair",
                title_issues=title_issues,
                output=data,
            )
            data = self.invoke_requirements_analyst_object_json(
                repair_task,
                context,
                mode="repair_requirement",
            )
            data = self.requirement_update_payload(
                data,
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
            repair_task = requirement_repair_prompt(
                "nfr_repair",
                nfr_issues=nfr_issues,
                output=data,
            )
            data = self.invoke_requirements_analyst_object_json(
                repair_task,
                context,
                mode="repair_requirement",
            )
            data = self.requirement_update_payload(
                data,
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
            repair_task = requirement_repair_prompt(
                "type_repair",
                mixed_issues=mixed_issues,
                output=data,
            )
            data = self.invoke_requirements_analyst_object_json(
                repair_task,
                context,
                mode="repair_requirement",
            )
            data = self.requirement_update_payload(
                data,
                action_name=f"{action_name} type repair",
            )
            if isinstance(data, dict):
                data["REQ"] = self.dedupe_candidate_requirement_rows(
                    self.normalize_generated_requirement_ids(data.get("REQ", []))
                )
            mixed_issues = self.type_issues(data.get("REQ") if isinstance(data, dict) else [])
            if mixed_issues:
                repair_task = requirement_repair_prompt(
                    "targeted_repair",
                    mixed_issues=mixed_issues,
                    output=data,
                )
                data = self.invoke_requirements_analyst_object_json(
                    repair_task,
                    context,
                    mode="repair_requirement",
                )
                data = self.requirement_update_payload(
                    data,
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

    # Defines update requirement task function for this module workflow.
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

    # Defines refine requirement task function for this module workflow.
    def refine_requirement_task(
        self,
        *,
        source_id: str,
    ) -> str:
        return refine_requirement(source_id=source_id)

    @staticmethod
    # Defines scope requirement context function for this module workflow.
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
    # Defines scope discussion context function for this module workflow.
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

    # Defines req source context function for this module workflow.
    def req_source_context(
        self,
        artifact: Dict[str, Any],
        issue: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        return self.scope_requirement_context(artifact)

    @staticmethod
    # Defines feedback context function for this module workflow.
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
    # Defines system model context function for this module workflow.
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
            text_rows = row.get("text") or row.get("use_case_text")
            if isinstance(text_rows, list) and text_rows:
                item["use_case_count"] = len(text_rows)
            if item:
                out.append(item)
        return out

    @staticmethod
    # Defines requirement context function for this module workflow.
    def requirement_context(artifact: Dict[str, Any]) -> List[Dict[str, Any]]:
        rows = artifact.get("REQ") if isinstance(artifact.get("REQ"), list) else []
        return [
            AnalystRequirementFlow.requirement_record(row)
            for row in rows
            if isinstance(row, dict)
        ]

    @staticmethod
    # Defines requirement source index function for this module workflow.
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
    # Defines next requirement id function for this module workflow.
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
    # Defines requirement key function for this module workflow.
    def requirement_key(row: Dict[str, Any]) -> str:
        description = str(row.get("description") or "").strip()
        sources = ",".join(AnalystRequirementFlow.requirement_sources(row))
        return requirement_dedupe_key(f"{description}|{sources}")

    @staticmethod
    # Defines dedupe candidate requirement rows function for this module workflow.
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
    # Defines normalize generated requirement ids function for this module workflow.
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
    # Defines coerce mixed requirement rows function for this module workflow.
    def coerce_mixed_requirement_rows(rows: Any) -> List[Dict[str, Any]]:
        constraint_terms = (
            "法規", "合規", "政策", "規範", "主管機關", "稽核", "違規",
            "資料申報", "責任", "限制", "必須遵守", "不能違反",
        )
        quality_terms = (
            "效能", "穩定", "可靠", "可用", "即時", "延遲", "回應時間",
            "SLA", "高峰", "錯誤率", "準確率",
        )
        out: List[Dict[str, Any]] = []
        for row in rows or []:
            if not isinstance(row, dict):
                continue
            item = dict(row)
            req_type = str(item.get("type") or "").strip().lower().replace("_", "-")
            if req_type != "functional":
                out.append(item)
                continue
            text = " ".join(
                str(item.get(key) or "")
                for key in ("title", "description", "rationale")
            )
            if any(term in text for term in constraint_terms):
                item["type"] = "constraint"
            elif any(term in text for term in quality_terms):
                item["type"] = "non-functional"
                if not str(item.get("category") or "").strip():
                    item["category"] = "Performance" if any(term in text for term in ("效能", "延遲", "回應時間", "高峰")) else "Reliability"
                if not str(item.get("metric") or "").strip():
                    item["metric"] = "以相關來源需求與會議決議中的可觀察條件驗證"
                if not str(item.get("validation") or "").strip():
                    item["validation"] = "inspection"
            out.append(item)
        return out

    @staticmethod
    # Defines requirement coverage issues function for this module workflow.
    def requirement_coverage_issues(rows: Any) -> List[str]:
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
            if status not in valid_statuses:
                issues.append(f"{source_id or f'coverage[{idx}]'}: status 不合法「{status or '<empty>'}」")
        return issues


    @staticmethod
    # Defines requirement title stakeholders function for this module workflow.
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
                    name = str(stakeholder or row.get("stakeholder_name") or "").strip()
                if len(name) >= 2:
                    names.append(name)
        return list(dict.fromkeys(names))

    @staticmethod
    # Defines normalize requirement titles function for this module workflow.
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
    # Defines requirement title issues function for this module workflow.
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
    # Defines type issues function for this module workflow.
    def type_issues(rows: Any) -> List[str]:
        quality_terms = (
            "穩定性", "可用性", "可靠性", "效能", "性能", "回應時間",
            "故障率", "服務中斷", "SLA", "吞吐", "高峰", "負載",
            "正確率", "錯誤率",
        )
        constraint_terms = (
            "法規", "主管機關", "保存年限", "資料保存", "刪除限制",
            "合規", "隱私", "個資", "稽核", "不能違反",
        )
        capability_terms = (
            "提供", "允許", "支援", "顯示", "查詢", "通知", "建立", "更新",
            "修改", "刪除", "回報", "申訴", "管理", "設定", "記錄", "匯出",
            "偵測", "標示", "提示", "處理",
        )
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
            text_parts = [
                str(row.get(key) or "")
                for key in ("id", "title", "description")
            ]
            text = " ".join(text_parts)
            has_quality = any(term in text for term in quality_terms)
            has_constraint = any(term in text for term in constraint_terms)
            has_capability = any(term in text for term in capability_terms)
            req_id = str(row.get("id") or f"REQ[{idx}]").strip()
            marker_count = sum(1 for m in multi_intent_markers if m in text)
            has_multiple_intents = (
                (1 if has_capability else 0)
                + (1 if has_quality else 0)
                + (1 if has_constraint else 0)
            ) >= 2
            if marker_count >= 1 and has_multiple_intents:
                issues.append(
                    f"{req_id} 可能混有多核心意圖，請檢查是否為功能、品質、限制同時出現"
                )
            if req_type == "functional" and has_capability and has_quality:
                issues.append(
                    f"{req_id} 是 functional，但同時包含可獨立追蹤的品質、穩定性或效能語意"
                )
            if req_type == "functional" and has_capability and has_constraint:
                issues.append(
                    f"{req_id} 是 functional，但同時包含可獨立追蹤的限制、法規或政策語意"
                )
            if req_type == "non-functional" and has_capability and not has_quality:
                issues.append(
                    f"{req_id} 是 non-functional，但內容主要是系統能力"
                )
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
    # Defines requirement granularity issues function for this module workflow.
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
    # Defines requirement cleanup issues function for this module workflow.
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
    # Defines nfr issues function for this module workflow.
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
    # Defines requirement sources function for this module workflow.
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
    # Defines requirement record function for this module workflow.
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

    # Defines clean requirement records function for this module workflow.
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

    # Defines merge requirement records function for this module workflow.
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

    # Defines remove merged requirement records function for this module workflow.
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

    # Defines requirement coverage records function for this module workflow.
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
    # Defines requirement coverage summary function for this module workflow.
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
    # Defines coverage gaps function for this module workflow.
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

    # Defines merge meeting requirements function for this module workflow.
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

    # Defines analyze conflicts function for this module workflow.
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
            if isinstance(row, dict) and str(row.get("label") or "").strip() == "Conflict"
        ]
        report_rows = unresolved_conflict_report_rows(report_rows, resolved_signatures)
        report_rows = reindex_conflict_report_rows(report_rows)
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
            if isinstance(row, dict) and str(row.get("label") or "").strip() == "Conflict"
        ]
        report_rows = unresolved_conflict_report_rows(report_rows, resolved_signatures)
        report_rows = reindex_conflict_report_rows(report_rows)
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
    # Defines has requirement candidates function for this module workflow.
    def has_requirement_candidates(output: Any) -> bool:
        return bool(AnalystRequirementFlow.requirement_candidate_rows(output))

    @staticmethod
    # Defines requirement candidate rows function for this module workflow.
    def requirement_candidate_rows(output: Any) -> List[Dict[str, Any]]:
        if isinstance(output, list):
            return [row for row in output if isinstance(row, dict)]
        if isinstance(output, dict):
            rows = output.get("requirements")
            if isinstance(rows, list):
                return [row for row in rows if isinstance(row, dict)]
        return []

    # Defines meeting requirement sources function for this module workflow.
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
