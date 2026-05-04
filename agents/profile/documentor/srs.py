# SRS generation implementation using Analyst draft, SRS skill polish, and output validation.
from datetime import datetime
import re
from typing import Any, Dict, List, Optional

from storage.markdown import clean_llm_output


class DocumentorSrs:
    FORBIDDEN_SRS_TERMS = (
        "pending_review",
        "open_question",
        "open_questions",
        "requirement_change_candidates",
    )

    @staticmethod
    def clean_text(value: Any) -> str:
        return " ".join(str(value or "").split()).strip()

    @classmethod
    def sanitize_requirement_for_srs(cls, req: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "id": cls.clean_text(req.get("id")),
            "type": cls.clean_text(req.get("type")),
            "priority": cls.clean_text(req.get("priority")),
            "status": cls.clean_text(req.get("status")),
            "text": cls.clean_text(req.get("text")),
            "source_stakeholders": [
                cls.clean_text(s)
                for s in (req.get("source_stakeholders") or [])
                if cls.clean_text(s)
            ],
            "source": cls.clean_text(req.get("source")),
            "rationale": cls.clean_text(req.get("rationale")),
            "verification_method": cls.clean_text(req.get("verification_method")),
            "acceptance_criteria": cls.clean_text(req.get("acceptance_criteria")),
        }

    @classmethod
    def filter_formal_list(cls, rows: Any) -> List[str]:
        cleaned: List[str] = []
        for row in rows or []:
            if isinstance(row, dict):
                status = cls.clean_text(row.get("status")).lower()
                if status and status not in {"verified", "resolved", "confirmed"}:
                    continue
                text = cls.clean_text(row.get("text") or row.get("description") or row.get("name"))
            else:
                text = cls.clean_text(row)
            if text:
                cleaned.append(text)
        return cleaned

    @classmethod
    def extract_requirement_like_ids(cls, markdown: str) -> set:
        return set(re.findall(r"\bREQ[-_A-Za-z0-9]+\b", markdown or ""))

    @classmethod
    def has_acceptance_criteria_label(cls, block: str) -> bool:
        lower = (block or "").lower()
        return (
            "acceptance criteria" in lower
            or "acceptance criterion" in lower
            or "驗收條件" in block
            or "驗收標準" in block
        )

    @classmethod
    def has_verification_method_label(cls, block: str) -> bool:
        lower = (block or "").lower()
        return (
            "verification method" in lower
            or "verification methods" in lower
            or "verification:" in lower
            or "驗證方式" in block
            or "驗證方法" in block
        )

    @classmethod
    def validate_srs_output(
        cls,
        markdown: str,
        context: Dict[str, Any],
    ) -> None:
        requirements = [
            req for req in (context.get("requirements", []) or [])
            if isinstance(req, dict)
        ]
        expected_ids = {
            cls.clean_text(req.get("id"))
            for req in requirements
            if cls.clean_text(req.get("id"))
        }
        if len(expected_ids) != len(requirements):
            missing_source_ids = len(requirements) - len(expected_ids)
            raise ValueError(
                "SRS skill output validation failed:\n"
                f"- verified requirements without IDs: {missing_source_ids}"
            )

        report: List[str] = []
        lower_markdown = (markdown or "").lower()

        missing_ids = sorted(rid for rid in expected_ids if rid not in (markdown or ""))
        if missing_ids:
            report.append(f"- missing requirement IDs: {', '.join(missing_ids)}")

        unknown_ids = sorted(cls.extract_requirement_like_ids(markdown) - expected_ids)
        if unknown_ids:
            report.append(f"- unknown requirement IDs: {', '.join(unknown_ids)}")

        forbidden = [
            term for term in cls.FORBIDDEN_SRS_TERMS
            if term.lower() in lower_markdown
        ]
        if forbidden:
            report.append(f"- forbidden terms found: {', '.join(forbidden)}")

        missing_acceptance: List[str] = []
        missing_verification: List[str] = []
        for rid in sorted(expected_ids):
            idx = (markdown or "").find(rid)
            if idx < 0:
                continue
            block = (markdown or "")[idx: idx + 2500]
            if not cls.has_acceptance_criteria_label(block):
                missing_acceptance.append(rid)
            if not cls.has_verification_method_label(block):
                missing_verification.append(rid)

        if missing_acceptance:
            report.append(
                "- missing Acceptance Criteria near requirement IDs: "
                + ", ".join(missing_acceptance)
            )
        if missing_verification:
            report.append(
                "- missing Verification Method near requirement IDs: "
                + ", ".join(missing_verification)
            )

        if report:
            raise ValueError(
                "SRS skill output validation failed:\n" + "\n".join(report)
            )

    def polish_srs_with_skill(
        self,
        analyst_draft: str,
        context: Dict[str, Any],
    ) -> str:
        if "SRS" not in self.skill_names:
            raise ValueError("DocumentorAgent 未賦予 SRS skill，無法產生正式 SRS")

        requirement_ids = [
            self.clean_text(req.get("id"))
            for req in (context.get("requirements", []) or [])
            if isinstance(req, dict) and self.clean_text(req.get("id"))
        ]
        task = f"""# 任務
請依 SRS skill 將下列 Analyst requirement draft 整理成正式、可交付的 Software Requirements Specification。

# 硬性限制
- 以 Analyst requirement draft 作為文件草稿來源，但正式需求只能來自 Context.requirements。
- Context.requirements 已經只包含 verified requirements；其他未驗證內容只能作為背景，不得寫成正式需求。
- 不得新增、刪除、合併、拆分或改寫 requirement ID。
- 不得新增 Context.requirements 以外的需求。
- 不得把 pending/open/unresolved/candidate 內容寫成正式需求。
- 每一條 requirement 必須保留 Acceptance Criteria 與 Verification Method。
- 每一條 requirement 必須以獨立小節呈現，且小節中必須逐字包含下列英文欄位標題：
  - Requirement:
  - Acceptance Criteria:
  - Verification Method:
- 不得只把 Acceptance Criteria 或 Verification Method 放在總表、附錄或其他遠離 requirement ID 的區塊。
- 若 Analyst draft 與 Context.requirements 不一致，以 Context.requirements 為準。
- 若原資料不足，保留「待補」，不得臆測。
- 最終只輸出 Markdown，不要解釋、不要包 code fence。

# Verified Requirement IDs
{", ".join(requirement_ids) if requirement_ids else "無"}

# Analyst Requirement Draft
{analyst_draft}
"""
        polished = self.invoke_skill("SRS", task, context=context)
        return clean_llm_output(polished)

    @classmethod
    def build_formal_only_context(
        cls,
        artifact: Dict[str, Any],
        *,
        latest_version: int,
        draft_md: str,
    ) -> Dict[str, Any]:
        allowed_statuses = {"verified"}
        requirements = [
            cls.sanitize_requirement_for_srs(req)
            for req in (artifact.get("requirements", []) or [])
            if isinstance(req, dict)
            and str(req.get("status") or "").strip().lower() in allowed_statuses
        ]
        verified_requirement_ids = {
            str(req.get("id") or "").strip()
            for req in requirements
            if str(req.get("id") or "").strip()
        }
        decisions = [
            dict(row)
            for row in (artifact.get("decisions", []) or [])
            if isinstance(row, dict)
            and (
                not row.get("affected_requirement_ids")
                or verified_requirement_ids.intersection(
                    {str(rid).strip() for rid in (row.get("affected_requirement_ids") or []) if str(rid).strip()}
                )
            )
        ]
        resolved_conflicts = [
            dict(row)
            for row in (artifact.get("conflicts", []) or [])
            if isinstance(row, dict) and str(row.get("label") or "").strip() == "Neutral"
        ]

        verification_context = []
        for req in requirements:
            verification_context.append({
                "requirement_id": req.get("id"),
                "source_stakeholders": req.get("source_stakeholders") or [],
                "source": req.get("source", ""),
                "rationale": req.get("rationale", ""),
                "acceptance_criteria": req.get("acceptance_criteria", ""),
                "verification_method": req.get("verification_method", ""),
            })

        revision_history = []
        for v in range(0, latest_version + 1):
            revision_history.append({
                "version": f"0.{v + 1}" if v < latest_version else "1.0",
                "draft_version": v,
                "description": (
                    "Initial draft" if v == 0 else
                    (f"Draft v{v} refined through meeting decisions" if v < latest_version else "Formal SRS baseline")
                ),
            })

        glossary_terms = []
        for req in requirements:
            for s in (req.get("source_stakeholders") or []):
                if s and s not in glossary_terms:
                    glossary_terms.append(s)
        real_stakeholders = [
            row for row in (artifact.get("stakeholders", []) or [])
            if isinstance(row, dict)
        ]
        product_roles = [
            cls.clean_text(row.get("name"))
            for row in real_stakeholders
            if cls.clean_text(row.get("name"))
        ]
        internal_roles = {"analyst", "expert", "modeler", "mediator", "documentor"}

        return {
            "document_metadata": {
                "generated_date": datetime.now().strftime("%Y-%m-%d"),
                "prepared_by": "Plant",
                "document_status": "formal_baseline",
            },
            "draft_version": latest_version,
            "draft_markdown": draft_md,
            "rough_idea": artifact.get("rough_idea", ""),
            "product_concept": artifact.get("rough_idea", ""),
            "scope": artifact.get("scope", {}),
            "stakeholders": real_stakeholders,
            "product_roles": product_roles,
            "internal_roles_to_exclude_from_product_roles": sorted(internal_roles),
            "requirements": requirements,
            "decisions": decisions,
            "resolved_conflicts": resolved_conflicts,
            "system_models": artifact.get("system_models", {}),
            "verification_context": verification_context,
            "revision_history": revision_history,
            "glossary_terms": glossary_terms,
            "assumptions": cls.filter_formal_list(artifact.get("assumptions", [])),
            "constraints": cls.filter_formal_list(artifact.get("constraints", [])),
            "dependencies": cls.filter_formal_list(artifact.get("dependencies", [])),
        }

    def generate_srs_impl(self, artifact: Optional[Dict[str, Any]] = None) -> str:
        """使用 Analyst 最新 draft 作為輸入，再由 SRS skill 正式化；驗證失敗則中止。"""
        latest_version = self.store.get_draft_version()
        if latest_version < 0:
            raise ValueError("尚無需求草稿，請先產生 draft 再生成 SRS")
        draft_md = self.store.load_draft(latest_version)
        if not draft_md:
            raise ValueError(f"無法載入草稿 draft_v{latest_version}.md")

        artifact = artifact or {}
        context = self.build_formal_only_context(
            artifact,
            latest_version=latest_version,
            draft_md=draft_md,
        )
        polished_srs = self.polish_srs_with_skill(draft_md, context)
        self.validate_srs_output(polished_srs, context)
        self.logger.info(f"  已由 SRS skill 產生並驗證正式 SRS（draft_v{latest_version}）")
        return polished_srs
