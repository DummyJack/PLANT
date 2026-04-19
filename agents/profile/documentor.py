from typing import Dict, Any, Optional, List
from agents.base import BaseAgent
from utils import documentor_srs_body_lang, srs_title_instruction


class DocumentorAgent(BaseAgent):
    name = "documentor"

    system_prompt = """你是 SRS 撰寫專家，負責把 formal-ready 需求資料編寫成正式、可交付的軟體需求規格書。

規則：
1. requirement_change_candidates、pending_review、未回答 open_questions、未解 conflict 與未正式套用的變更，不得寫成已定案 requirement。
2. 你只根據 formal-only context 編寫，不自行補決策，不把討論過程寫入正式文件。
3. 生成流程分兩階段：先依 annotated template 產出完整 SRS 草稿，再依 clean bare template 輸出正式稿。
4. 最終正式稿不得保留 template 的說明文字、提示語、註解、emoji、placeholder 指示或其他 authoring residue。
5. 文件語氣必須像基線規格文件，不得寫成會議摘要、工作紀錄、討論整理或建議書。"""

    def __init__(
        self,
        model,
        store,
        tools: Optional[list] = None,
        registry=None,
        project_config=None,
    ):
        super().__init__(
            model,
            tools=tools,
            registry=registry,
            skill_names=["srs-generation"],
            project_config=project_config,
        )
        self.store = store

    @staticmethod
    def _clean_text(value: Any) -> str:
        return " ".join(str(value or "").split()).strip()

    @classmethod
    def _sanitize_requirement_for_srs(cls, req: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "id": cls._clean_text(req.get("id")),
            "type": cls._clean_text(req.get("type")),
            "priority": cls._clean_text(req.get("priority")),
            "status": cls._clean_text(req.get("status")),
            "text": cls._clean_text(req.get("text")),
            "source_stakeholders": [
                cls._clean_text(s)
                for s in (req.get("source_stakeholders") or [])
                if cls._clean_text(s)
            ],
            "source": cls._clean_text(req.get("source")),
            "rationale": cls._clean_text(req.get("rationale")),
            "verification_method": cls._clean_text(req.get("verification_method")),
            "acceptance_criteria": cls._clean_text(req.get("acceptance_criteria")),
        }

    @classmethod
    def _filter_formal_list(cls, rows: Any) -> List[str]:
        cleaned: List[str] = []
        for row in rows or []:
            if isinstance(row, dict):
                status = cls._clean_text(row.get("status")).lower()
                if status and status not in {"approved", "baselined", "resolved", "confirmed"}:
                    continue
                text = cls._clean_text(row.get("text") or row.get("description") or row.get("name"))
            else:
                text = cls._clean_text(row)
            if text:
                cleaned.append(text)
        return cleaned

    @staticmethod
    def _build_formal_only_context(
        artifact: Dict[str, Any],
        *,
        latest_version: int,
        draft_md: str,
    ) -> Dict[str, Any]:
        allowed_statuses = {"approved", "baselined"}
        requirements = [
            DocumentorAgent._sanitize_requirement_for_srs(req)
            for req in (artifact.get("requirements", []) or [])
            if isinstance(req, dict)
            and str(req.get("status") or "").strip().lower() in allowed_statuses
        ]
        approved_requirement_ids = {
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
                or approved_requirement_ids.intersection(
                    {str(rid).strip() for rid in (row.get("affected_requirement_ids") or []) if str(rid).strip()}
                )
            )
        ]
        resolved_conflicts = [
            dict(row)
            for row in (artifact.get("conflicts", []) or [])
            if isinstance(row, dict) and str(row.get("label") or "").strip() == "Neutral"
        ]

        stakeholder_rtm = []
        for req in requirements:
            stakeholder_rtm.append({
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

        return {
            "draft_version": latest_version,
            "draft_markdown": draft_md,
            "rough_idea": artifact.get("rough_idea", ""),
            "scope": artifact.get("scope", {}),
            "stakeholders": artifact.get("stakeholders", []),
            "requirements": requirements,
            "decisions": decisions,
            "resolved_conflicts": resolved_conflicts,
            "system_models": artifact.get("system_models", {}),
            "stakeholder_rtm": stakeholder_rtm,
            "revision_history": revision_history,
            "glossary_terms": glossary_terms,
            "assumptions": DocumentorAgent._filter_formal_list(artifact.get("assumptions", [])),
            "constraints": DocumentorAgent._filter_formal_list(artifact.get("constraints", [])),
            "dependencies": DocumentorAgent._filter_formal_list(artifact.get("dependencies", [])),
        }

    def generate_srs(self, artifact: Optional[Dict[str, Any]] = None) -> str:
        opa = self.run_single_opa(
            mode="document_output",
            context={"artifact": artifact or {}},
        )
        result = opa.get("result") or {}
        return (result.get("srs_markdown") or "").strip()

    def build_observation(self, *, mode: str, **kwargs: Any) -> Dict[str, Any]:
        if mode == "document_output":
            artifact = kwargs.get("artifact") or {}
            latest_version = self.store.get_draft_version()
            return {
                "draft_version": latest_version,
                "has_draft": latest_version >= 0,
                "requirements_count": len(artifact.get("requirements", []) or []),
                "decisions_count": len(artifact.get("decisions", []) or []),
                "conflicts_count": len(artifact.get("conflicts", []) or []),
                "iteration": kwargs.get("iteration", 0) + 1,
                "max_iterations": kwargs.get("max_iterations", 1),
            }
        return super().build_observation(mode=mode, **kwargs)

    def decide_action(
        self,
        *,
        mode: str,
        observation: Dict[str, Any],
        last_result: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        if mode == "document_output":
            return {
                "action": "generate_srs",
                "params": {},
                "reasoning": "formal-ready requirement 已齊備，生成正式 SRS。",
            }
        return super().decide_action(
            mode=mode,
            observation=observation,
            last_result=last_result,
            **kwargs,
        )

    def _generate_srs_impl(self, artifact: Optional[Dict[str, Any]] = None) -> str:
        """Step F2: 以 formal-ready context 走雙模板流程產出正式 SRS。

        Stage 1:
            使用 srs-generation 的 template.md 產出完整 SRS 草稿。
        Stage 2:
            使用 template-bare.md 將草稿整理為乾淨、可交付的正式稿。

        回傳最終正式 SRS Markdown。
        """
        latest_version = self.store.get_draft_version()
        if latest_version < 0:
            raise ValueError("尚無需求草稿，請先產生 draft 再生成 SRS")
        draft_md = self.store.load_draft(latest_version)
        if not draft_md:
            raise ValueError(f"無法載入草稿 draft_v{latest_version}.md")

        artifact = artifact or {}
        context = self._build_formal_only_context(
            artifact,
            latest_version=latest_version,
            draft_md=draft_md,
        )
        title_rule = srs_title_instruction()
        body_lang = documentor_srs_body_lang()
        draft_task = f"""依 srs-generation skill 的 template.md 與 checklist，根據 Context 的 formal-ready 資料先產出一份完整 SRS 草稿（Markdown）。

只保留以下四個原則：

1. formal-only
- Context 只包含 formal-ready inputs。
- 不得自行補入未批准需求、候選變更、未回答問題、未定案內容或未解衝突。

2. source-only
- SRS 的 requirement 內容必須且僅可來自 Context.requirements。
- Context.draft_markdown 只能作為編排與措辭參考，不可作為新增 requirement 內容的來源。
- 若 Context 中沒有明確支持，請標示「待補」或不寫。
- Context.stakeholder_rtm 僅可作為 traceability / verification 輔助參考，不可主導正式 SRS 的章節骨架、文件形狀或 requirement 呈現格式。

3. no process residue
- 正式 SRS 不得描述會議過程、投票過程、主持人折衷、討論歷程、人工裁決歷程或草稿修訂歷程。
- 不得把 unresolved 狀態、待裁決事項、內部工作註記寫成正文事實。

4. no hallucination
- 不得自行新增、推測或編造任何 requirement、系統邊界、角色、外部整合、法規義務、標準、數值門檻或其他未被 Context 支持的內容。
- 若某欄位缺乏來源支撐，可明確標示「待補」，但不得用推測語句掩蓋資訊缺口。
- Context.revision_history 可用於文件資訊與修訂紀錄，但不可擴張成額外的舊式文件包或多餘章節。

本階段目的：
- 使用 template.md 的說明、提示、章節規範與寫作提示，先把內容寫完整。
- 可以參考 template.md 中的說明文字來決定每段該寫什麼。
- 但輸出仍必須是一份可閱讀的 SRS 草稿 Markdown，不可把你的推理過程寫出來。

其餘章節結構、章節名稱、文件骨架、requirements 呈現格式與 checklist 驗證規則，一律遵循 srs-generation skill 內建 template.md，不要在輸出中自行改寫或擴充。

標題格式：{title_rule}
{body_lang} 只輸出 SRS 草稿 Markdown，勿包程式碼區塊。"""

        srs_draft = self.invoke_skill("srs-generation", draft_task, context=context)
        srs_draft = self.strip_code_fences(srs_draft).strip()

        final_context = dict(context)
        final_context["generated_srs_draft"] = srs_draft
        final_task = f"""依 srs-generation skill 的 template-bare.md，將 Context.generated_srs_draft 重新整理為最終正式稿。

規則：
1. 只能根據 Context.generated_srs_draft 與 Context 內 formal-ready 資料整理，不得新增 draft 中沒有、且 Context 也未支持的新 requirement 或新事實。
2. 這一階段的目的不是重寫內容，而是把內容正確落進 template-bare.md 的乾淨骨架。
3. 最終輸出不得包含 template.md 裡的說明文字、提示文字、emoji、註解、教學語氣、寫作指示或 checklist 敘述。
4. 若 draft 中有不適合正式稿的教學殘留、提示語、空白 placeholder 或 process residue，這一階段必須去除。
5. 章節、標題、表格與骨架以 template-bare.md 為準；內容以 generated_srs_draft 為主。

標題格式：{title_rule}
{body_lang} 只輸出最終正式 SRS Markdown，勿包程式碼區塊。"""

        srs_md_full = self.invoke_skill("srs-generation", final_task, context=final_context)
        srs_md_full = self.strip_code_fences(srs_md_full)
        self.logger.info(
            f"  已依 srs-generation skill 由 draft_v{latest_version} 兩階段產生正式 SRS"
        )
        return srs_md_full.strip()

    def execute_action(
        self,
        *,
        mode: str,
        decision: Dict[str, Any],
        **kwargs: Any,
    ) -> Dict[str, Any]:
        if mode == "document_output":
            srs = self._generate_srs_impl(kwargs.get("artifact"))
            return {
                "action": decision.get("action", ""),
                "status": "success",
                "srs_markdown": srs,
                "summary": "完成 documentor SRS generation",
            }
        return super().execute_action(mode=mode, decision=decision, **kwargs)

    @staticmethod
    def strip_code_fences(text: str) -> str:
        stripped = text.strip()
        if stripped.startswith("```"):
            first_newline = stripped.find("\n")
            if first_newline != -1:
                stripped = stripped[first_newline + 1 :]
            if stripped.endswith("```"):
                stripped = stripped[:-3]
        return stripped.strip()
