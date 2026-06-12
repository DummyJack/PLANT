# Handles Design Rationale generation for documentor workflow.
import re
from typing import Any, Dict, List

from agents.profile.documentor.actions.dr import design_rationale
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

    def generate_dr(self, artifact: Dict[str, Any]) -> str:
        artifact_for_dr = dict(artifact or {})
        versioned_conflicts = self.versioned_conflict_report_rows()
        if versioned_conflicts:
            conflict_state = dict(artifact_for_dr.get("conflict") or {})
            conflict_state["report"] = versioned_conflicts
            artifact_for_dr["conflict"] = conflict_state
        req_rows = [row for row in (artifact_for_dr.get("REQ") or []) if isinstance(row, dict)]
        appendix = self.build_dr_appendix(artifact_for_dr)
        self.resolve_dr_appendix_model_images(appendix)
        requirements = self.build_dr_body_context(req_rows, appendix)
        batches = self.split_dr_body_context(requirements)
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
        body = self.normalize_design_rationale_body(body, requirements)
        body = self.normalize_design_rationale_links(body)
        body = self.normalize_design_rationale_citation_phrasing(body)
        body = self.remove_design_rationale_appendix_refs(body)
        body = inject_trace_topologies(body, requirements)
        body = self.normalize_horizontal_rules(body)
        if "dr-trace-topology" in body:
            body = render_trace_topology_assets() + "\n\n" + body
        markdown = "# Design Rationale\n\n" + body.strip() + "\n"
        return self.normalize_horizontal_rules(markdown)
