# SRS generation implementation using Analyst draft and SRS skill polish.
from datetime import datetime
from typing import Any, Dict, List, Optional

from agents.profile.analyst.conflict_store import all_conflict_rows
from storage.markdown import clean_llm_output


class DocumentorSrs:
    @staticmethod
    def clean_text(value: Any) -> str:
        return " ".join(str(value or "").split()).strip()

    @classmethod
    def stakeholder_name(cls, value: Any) -> str:
        if isinstance(value, dict):
            return cls.clean_text(value.get("name"))
        return cls.clean_text(value)

    @classmethod
    def sanitize_requirement_for_srs(cls, req: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "id": cls.clean_text(req.get("id")),
            "type": cls.clean_text(req.get("type")),
            "priority": cls.clean_text(req.get("priority")),
            "stakeholder": cls.stakeholder_name(req.get("stakeholder")),
            "text": cls.clean_text(req.get("text")),
            "source": cls.clean_text(req.get("source")),
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

# SRS skill 適配
- SRS skill 採 IEEE 830 結構；請輸出正式 SRS，而不是會議摘要或 backlog。
- 使用 IEEE 830 的 Introduction、Overall Description、Specific Requirements、Appendices 作為主要架構。
- skill/template 中的 FR-XXX、NFR-XXX、RTM、Stakeholder Sign-Off 是通用範例；本專案不採用那些新 ID 或獨立輸出。
- 本專案需求 ID 以正式需求的 REQ-* 為準；可以依 requirement type 分到 functional / non-functional 小節，但 ID 不得改名。
- 不要輸出 Requirements Traceability Matrix、Stakeholder Sign-Off、Open Issues、Change Request Process、Pending Decisions 這些章節。
- template 中沒有資料支撐的 placeholder 或範例區塊要省略，不要留下 {{PROJECT_NAME}}、{{TERM}}、placeholder、TODO 或範例資料。

# 硬性限制
- 以 Analyst requirement draft 作為文件草稿來源，但正式需求以輸入資料中的正式需求為準。
- 不得新增、刪除、合併、拆分或改寫 requirement ID。
- 不得新增正式需求以外的需求。
- 不得輸出正式需求 ID 清單以外的任何 REQ-* ID。
- 不得把 pending/open/unresolved/candidate 內容寫成正式需求。
- 每一條 requirement 必須保留 Acceptance Criteria。
- 每一條 requirement 必須以獨立小節呈現，且小節中必須逐字包含下列英文欄位標題：
  - Requirement:
  - Acceptance Criteria:
- 不得只把 Acceptance Criteria 放在總表、附錄或其他遠離 requirement ID 的區塊。
- 若 Analyst draft 與正式需求不一致，以正式需求為準。
- 若原資料不足，保留「待補」，不得臆測。
- 最終只輸出 Markdown，不要解釋、不要包 code fence。

# 正式需求 ID 清單
{", ".join(requirement_ids) if requirement_ids else "無"}

# Analyst Requirement Draft
{analyst_draft}
"""
        polished = self.invoke_skill("SRS", task, context=context)
        return clean_llm_output(polished)

    @classmethod
    def build_final_meeting_context(
        cls,
        artifact: Dict[str, Any],
        *,
        latest_version: int,
        draft_md: str,
    ) -> Dict[str, Any]:
        requirements = [
            cls.sanitize_requirement_for_srs(req)
            for req in (artifact.get("requirements", []) or [])
            if isinstance(req, dict)
        ]
        decisions = [
            dict(row)
            for row in (artifact.get("decisions", []) or [])
            if isinstance(row, dict)
        ]
        resolved_conflicts = [
            dict(row)
            for row in all_conflict_rows(artifact)
            if isinstance(row, dict) and str(row.get("label") or "").strip() == "Neutral"
        ]

        acceptance_context = []
        for req in requirements:
            acceptance_context.append({
                "requirement_id": req.get("id"),
                "stakeholder": req.get("stakeholder", ""),
                "source": req.get("source", ""),
                "acceptance_criteria": req.get("acceptance_criteria", ""),
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
            stakeholder = cls.stakeholder_name(req.get("stakeholder"))
            if stakeholder and stakeholder not in glossary_terms:
                glossary_terms.append(stakeholder)
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
            "system_models": artifact.get("system_models", []),
            "acceptance_context": acceptance_context,
            "revision_history": revision_history,
            "glossary_terms": glossary_terms,
            "assumptions": cls.filter_formal_list(artifact.get("assumptions", [])),
            "constraints": cls.filter_formal_list(artifact.get("constraints", [])),
            "dependencies": cls.filter_formal_list(artifact.get("dependencies", [])),
        }

    def generate_srs_internal(self, artifact: Optional[Dict[str, Any]] = None) -> str:
        """使用 Analyst 最新 draft 作為輸入，再由 SRS skill 正式化。"""
        latest_version = self.store.get_draft_version()
        if latest_version < 0:
            raise ValueError("尚無需求草稿，請先產生 draft 再生成 SRS")
        draft_md = self.store.load_draft(latest_version)
        if not draft_md:
            raise ValueError(f"無法載入草稿 draft_v{latest_version}.md")

        artifact = artifact or {}
        context = self.build_final_meeting_context(
            artifact,
            latest_version=latest_version,
            draft_md=draft_md,
        )
        polished_srs = self.polish_srs_with_skill(draft_md, context)
        self.logger.info(f"  已由 SRS skill 產生正式 SRS（draft_v{latest_version}）")
        return polished_srs
