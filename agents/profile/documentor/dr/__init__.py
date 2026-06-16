# Handles Design Rationale generation for documentor workflow.
from __future__ import annotations

import re
import json
from typing import Any, Dict, List

from agents.profile.documentor.actions.dr import design_rationale
from storage.artifact import ensure_trace_req
from utils.topology import (
    inject_trace_topologies,
    render_trace_topology_assets,
)

from .context import DocumentorDrContext
from .normalize import DocumentorDrNormalize


class DocumentorDr(DocumentorDrContext, DocumentorDrNormalize):
    @staticmethod
    def retry_design_rationale_prompt(prompt: str, error: Exception) -> str:
        return (
            f"{prompt.rstrip()}\n\n"
            "# Format Validation Error\n"
            f"{error}\n\n"
            "# Retry Instruction\n"
            "- 你剛剛輸出了舊格式或不合法格式。\n"
            "- 請只重新輸出本批 Requirement Context 的完整 Design Rationale 主體 Markdown。\n"
            "- 每個 block 標題必須使用 context.srs_id，格式只能是 `### FR-*:`、`### NFR-*:` 或 `### CON-*:`。\n"
            "- 不得使用 `REQ-*` 作為 block 標題。\n"
            "- 不得輸出表格式 rationale。\n"
            "- Trace Explanation 必須使用英文純文字標籤與 bullet，例如 `Stakeholder`、`User Requirement`；標籤不得使用 `###` 或編號。每個 bullet 第一句必須以 evidence ID 開頭，並說明該 ID 如何影響下一個節點或正式需求。\n"
            "- Requirement Formation 必須明確寫出 URL/Meeting/trace 節點如何收斂成目前 FR/NFR/CON。\n"
            "- 不得輸出 `Type`、`Source`、`Context`、`Decision`、`Rationale`、`Impact`、`SRS ID` 舊欄位或章節。\n"
            "- 不要輸出 H1，不要輸出 Appendix，不要解釋錯誤，不要包程式碼區塊。\n"
        )

    @staticmethod
    def trace_repair_prompt(requirements: List[Dict[str, Any]], previous_errors: List[str] | None = None) -> str:
        payload = [
            {
                "id": req.get("id"),
                "srs_id": req.get("srs_id"),
                "trace_warnings": req.get("trace_warnings") or [],
                "trace_repair_tasks": req.get("trace_repair_tasks") or [],
            }
            for req in requirements
            if isinstance(req, dict) and req.get("trace_repair_tasks")
        ]
        return (
            "# Trace Repair Proposal\n"
            "你是 trace repair agent。請只根據 trace_repair_tasks 提出可驗證的修補 proposal。\n"
            "不得新增不存在的 evidence id，不得把低信心推測當成正式 trace。\n"
            "edge_label 只能依 repair_type 使用 runtime 允許值；不要自創長句、同義詞或說明文字。\n"
            "connect_statement_to_url / identify_url_source 只能用「整理」；connect_resolve_to_formalize_meeting 只能用「正式化」；identify_conflict_resolution_meeting 只能用「解決」；connect_feedback_to_formalize_meeting、connect_model_to_formalize_meeting、identify_formalization_meeting 必須用空字串。\n"
            "只輸出 JSON，不要 Markdown。\n\n"
            "# Output JSON\n"
            "{\n"
            '  "proposals": [\n'
            "    {\n"
            '      "target_requirement_id": "FR-* | NFR-* | CON-*",\n'
            '      "repair_type": "connect_statement_to_url | connect_feedback_to_formalize_meeting | connect_model_to_formalize_meeting | connect_resolve_to_formalize_meeting | identify_url_source | identify_conflict_resolution_meeting | identify_formalization_meeting",\n'
            '      "candidate_from": "existing evidence id or empty",\n'
            '      "candidate_to": "existing evidence id or empty",\n'
            '      "edge_label": "整理 | 解決 | 正式化 | empty string; must match repair_type",\n'
            '      "reason": "why this repair follows the task",\n'
            '      "confidence": "high | medium | low"\n'
            "    }\n"
            "  ]\n"
            "}\n\n"
            "# Runtime Context\n"
            f"{json.dumps(payload, ensure_ascii=False, indent=2)}\n\n"
            "# Previous Validation Errors\n"
            f"{json.dumps(previous_errors or [], ensure_ascii=False, indent=2)}"
        )

    @staticmethod
    def parse_trace_repair_proposals(raw: Any) -> List[Dict[str, Any]]:
        text = str(raw or "").strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*", "", text)
            text = re.sub(r"\s*```$", "", text).strip()
        match = re.search(r"\{.*\}", text, flags=re.S)
        if not match:
            return []
        try:
            payload = json.loads(match.group(0))
        except Exception:
            return []
        proposals = payload.get("proposals") if isinstance(payload, dict) else []
        return [proposal for proposal in proposals or [] if isinstance(proposal, dict)]

    def repair_trace_contexts(self, requirements: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        repaired = [dict(req) for req in requirements]
        previous_warning_count = sum(len(req.get("trace_warnings") or []) for req in repaired)
        validation_errors: List[str] = []
        for _round in range(self.TRACE_AGENT_REPAIR_MAX_ROUNDS):
            repairable = []
            for req in repaired:
                agent_tasks, human_tasks = self.split_agent_repair_tasks(req)
                req["trace_repair_tasks"] = agent_tasks
                if human_tasks:
                    req["trace_human_review_tasks"] = human_tasks
                if agent_tasks:
                    repairable.append(req)
            if not repairable:
                break
            raw = self.model.chat(
                self.build_direct_messages(self.trace_repair_prompt(repairable, validation_errors)),
                action=self.usage_action("documentor.trace_repair"),
            )
            proposals = self.parse_trace_repair_proposals(raw)
            if not proposals:
                break
            validation_errors = []
            proposals_by_target: Dict[str, List[Dict[str, Any]]] = {}
            for proposal in proposals:
                target = str(proposal.get("target_requirement_id") or "").strip()
                if target:
                    proposals_by_target.setdefault(target, []).append(proposal)
            next_repaired: List[Dict[str, Any]] = []
            applied_any = False
            for req in repaired:
                target = str(req.get("srs_id") or req.get("id") or "").strip()
                req_proposals: List[Dict[str, Any]] = []
                for alias in self.trace_target_aliases(req):
                    req_proposals.extend(proposals_by_target.get(alias, []))
                for proposal in req_proposals:
                    validation = self.validate_trace_repair_proposal(req, proposal)
                    if not validation.get("accepted"):
                        validation_errors.extend(str(error) for error in validation.get("errors") or [])
                        rejected = dict(proposal)
                        rejected["status"] = "needs_human_review"
                        rejected["validation_errors"] = validation.get("errors") or []
                        req.setdefault("trace_human_review_tasks", []).append(rejected)
                updated = self.apply_trace_repair_proposals(req, req_proposals)
                applied_any = applied_any or bool(updated.get("trace_repair_applied") != req.get("trace_repair_applied"))
                next_repaired.append(updated)
            repaired = next_repaired
            warning_count = sum(len(req.get("trace_warnings") or []) for req in repaired)
            if not applied_any or warning_count >= previous_warning_count:
                break
            previous_warning_count = warning_count
        return repaired

    def generate_dr(self, artifact: Dict[str, Any]) -> str:
        artifact_for_dr = dict(artifact or {})
        ensure_trace_req(artifact_for_dr)
        versioned_conflicts = self.versioned_conflict_report_rows()
        if versioned_conflicts:
            conflict_state = dict(artifact_for_dr.get("conflict") or {})
            conflict_state["report"] = versioned_conflicts
            artifact_for_dr["conflict"] = conflict_state
        req_rows = [row for row in (artifact_for_dr.get("REQ") or []) if isinstance(row, dict)]
        appendix = self.build_dr_appendix(artifact_for_dr)
        self.resolve_dr_appendix_model_images(appendix)
        requirements = self.build_dr_body_context(req_rows, appendix)
        requirements = self.repair_trace_contexts(requirements)
        public_requirements = self.public_dr_requirement_contexts(requirements)
        batches = self.split_dr_body_context(public_requirements)
        body_parts: List[str] = []
        for batch in batches:
            prompt = design_rationale(batch)
            action = self.usage_action("documentor.generate_dr")
            last_error: ValueError | None = None
            part = ""
            for attempt in range(2):
                task = prompt if attempt == 0 else self.retry_design_rationale_prompt(prompt, last_error or ValueError("invalid design rationale format"))
                raw = self.model.chat(
                    self.build_direct_messages(task),
                    action=action,
                )
                part = str(raw or "").strip()
                if part.startswith("```"):
                    part = re.sub(r"^```(?:markdown|md)?\s*", "", part)
                    part = re.sub(r"\s*```$", "", part).strip()
                part = re.sub(r"(?m)^#\s+Design Rationale\s*", "", part).strip()
                try:
                    self.validate_design_rationale_block(part)
                    break
                except ValueError as exc:
                    last_error = exc
                    if attempt == 1:
                        raise
            body_parts.append(part)
        body = "\n\n".join(part for part in body_parts if part.strip()).strip()
        body = self.normalize_design_rationale_body(body, public_requirements)
        body = self.normalize_design_rationale_links(body)
        body = self.normalize_design_rationale_citation_phrasing(body)
        body = self.remove_design_rationale_appendix_refs(body)
        body = inject_trace_topologies(body, requirements)
        body = self.normalize_horizontal_rules(body)
        if "dr-trace-topology" in body:
            body = render_trace_topology_assets() + "\n\n" + body
        markdown = "# Design Rationale\n\n" + body.strip() + "\n"
        return self.normalize_horizontal_rules(markdown)
