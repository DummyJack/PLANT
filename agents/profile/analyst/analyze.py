# Analyst requirements logic: scope, drafts, requirement records, and change candidates.
import re
from typing import Any, Dict, List, Optional

from agents.base import analyst_draft_decision_table_note
from storage.markdown import clean_llm_output


class AnalystRequirements:
    def run_requirements_analyst(
        self,
        action: str,
        *,
        rough_idea: str = "",
        stakeholders: Optional[List[Dict]] = None,
        artifact: Optional[Dict[str, Any]] = None,
        draft_version: Optional[int] = None,
        round_num: Optional[int] = None,
        recent_decisions_limit: Optional[int] = None,
    ):
        """requirements-analyst skill 統一入口。

        action:
            "generate_scope"          -> 回傳 Dict (scope)
            "analyze_requirements"    -> 回傳 Dict (requirements list)
            "create_draft"            -> 回傳 str  (Markdown)
            "update_draft"            -> 回傳 Dict (requirements + change_candidates)
        """
        if action == "generate_scope":
            return self.ra_generate_scope(rough_idea, stakeholders or [], artifact=artifact)
        if action == "analyze_requirements":
            return self.ra_analyze_requirements(stakeholders or [])
        if action == "create_draft":
            return self.ra_create_draft(
                artifact or {},
                draft_version=draft_version,
                round_num=round_num,
                recent_decisions_limit=recent_decisions_limit,
            )
        if action == "update_draft":
            return self.ra_update_draft(artifact or {})
        raise ValueError(f"未知 requirements action: {action}")

    @staticmethod
    def normalize_requirement_text(text: str) -> str:
        value = str(text or "").strip()
        if not value:
            return ""
        value = re.sub(r"^\s*[-*•]+\s*", "", value)
        value = re.sub(
            r"^\s*(需求|Requirement)\s*[:：]\s*",
            "",
            value,
            flags=re.IGNORECASE,
        )
        value = value.strip().strip("\"'“”「」")
        value = re.sub(r"\s+", " ", value).strip()
        return value

    @staticmethod
    def normalize_requirement_record(
        req: Dict[str, Any],
        *,
        fallback_source_stakeholders: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        out = dict(req) if isinstance(req, dict) else {}
        out["text"] = AnalystRequirements.normalize_requirement_text(out.get("text"))
        rtype = str(out.get("type") or "FR").strip()
        if rtype not in {"FR", "NFR", "constraint"}:
            rtype = "FR"
        out["type"] = rtype
        priority = str(out.get("priority") or "should").strip()
        if priority not in {"must", "should", "could"}:
            priority = "should"
        out["priority"] = priority
        src = out.get("source_stakeholders")
        if not isinstance(src, list):
            src = []
        src = [str(s).strip() for s in src if str(s).strip()]
        if not src and fallback_source_stakeholders:
            src = [
                str(s).strip()
                for s in fallback_source_stakeholders
                if str(s).strip()
            ]
        out["source_stakeholders"] = src
        out["verification_method"] = str(out.get("verification_method") or "").strip()
        out["acceptance_criteria"] = str(out.get("acceptance_criteria") or "").strip()
        out["rationale"] = str(out.get("rationale") or "").strip()
        out["source"] = str(out.get("source") or "").strip()
        status = str(out.get("status") or "unverified").strip().lower()
        if status in {"approved", "baselined"}:
            status = "verified"
        elif status not in {"unverified", "verified"}:
            status = "unverified"
        out["status"] = status
        return out

    def ra_generate_scope(
        self, rough_idea: str, stakeholders: List[Dict],
        *, artifact: Optional[Dict[str, Any]] = None,
    ) -> Dict:
        context: Dict[str, Any] = {"rough_idea": rough_idea, "stakeholders": stakeholders}
        if artifact:
            if artifact.get("scope"):
                context["current_scope"] = artifact["scope"]
            if artifact.get("requirements"):
                context["requirements"] = artifact["requirements"]
            if artifact.get("conflicts"):
                context["conflicts"] = artifact["conflicts"]
            dr = (artifact.get("feedback") or {}).get("domain_research")
            if dr:
                context["domain_research"] = dr
            models = (artifact.get("system_models") or {}).get("models")
            if models:
                context["system_models"] = [
                    {"name": m.get("name"), "type": m.get("type")} for m in models
                ]
        task = """依 requirements-analyst skill，根據 Context 產出或更新專案範圍。

只輸出：
{"scope":{"description":"...", "in_scope":["..."], "out_of_scope":["..."], "assumptions":["..."], "unknowns":["..."]}}

流程邊界：
- description 來自 rough_idea。
- scope 判斷應綜合 stakeholders、requirements、conflicts、domain_research 與 system_models（若有）。
- 若 Context 有 current_scope，請以 current_scope 為基礎進行更新與修正，不要從零重寫。
- 不得擴張 Context 未支持的範圍。
- 勿輸出 Markdown。"""
        try:
            data = self.invoke_requirements_analyst_json(task, context)
        except Exception as e:
            self.logger.warning(f"scope 生成失敗: {e}")
            return {"in_scope": [], "out_of_scope": [], "description": ""}
        scope = data.get("scope") or {}
        if not isinstance(scope, dict):
            return {"in_scope": [], "out_of_scope": [], "description": ""}
        return {
            "in_scope": scope.get("in_scope", []),
            "out_of_scope": scope.get("out_of_scope", []),
            "description": scope.get("description", ""),
            "assumptions": scope.get("assumptions", []),
            "unknowns": scope.get("unknowns", []),
        }

    def ra_analyze_requirements(self, stakeholders: List[Dict]) -> Dict[str, Any]:
        all_requirements = []
        for idx, one_sh in enumerate(stakeholders):
            sh_label = one_sh.get("name") or one_sh.get("id") or f"利害關係人{idx + 1}"
            context = {"stakeholders": [one_sh]}
            task = f"""依 requirements-analyst skill，根據 Context 中此單一利害關係人產出結構化需求清單。

只輸出：
{{"requirements":[...]}}

流程邊界：
- 本輪只分析此一利害關係人。
- source_stakeholders 固定填 ["{sh_label}"]。
- id 先不要定，由系統後續指派。
- 只整理 Context 已支持的需求；不要擴張 scope，不要編造未被支持的細節。
- 勿輸出 Markdown。

其餘 requirement record 內容與品質標準，一律遵循 requirements-analyst skill。"""
            try:
                data = self.invoke_requirements_analyst_json(task, context)
            except Exception as e:
                self.logger.warning(f"需求分析失敗（{sh_label}）: {e}")
                continue
            reqs = data.get("requirements", [])
            if not isinstance(reqs, list):
                continue
            for r in reqs:
                if not r.get("text"):
                    continue
                normalized = self.normalize_requirement_record(
                    r,
                    fallback_source_stakeholders=[sh_label],
                )
                all_requirements.append(normalized)

        typed_groups: Dict[str, List[Dict[str, Any]]] = {}
        ordered_types: List[str] = []
        for r in all_requirements:
            req_type = (r.get("type") or "").strip().upper() or "REQ"
            if req_type not in typed_groups:
                typed_groups[req_type] = []
                ordered_types.append(req_type)
            typed_groups[req_type].append(r)

        assigned: List[Dict[str, Any]] = []
        counter = 1
        for req_type in ordered_types:
            for r in typed_groups[req_type]:
                r["type"] = req_type
                r["id"] = f"REQ-{counter}"
                assigned.append(r)
                counter += 1
        return {"requirements": assigned}

    def ra_create_draft(
        self,
        artifact: Dict[str, Any],
        draft_version: Optional[int] = None,
        round_num: Optional[int] = None,
        recent_decisions_limit: Optional[int] = None,
    ) -> str:
        requirements = artifact.get("requirements", [])
        for req in requirements:
            req_norm = self.normalize_requirement_record(req)
            req.update(req_norm)

        n = 10 if recent_decisions_limit is None else max(0, recent_decisions_limit)
        decisions = artifact.get("decisions", [])[-n:] if n else []
        scope = artifact.get("scope", {}) or {}
        feedback = artifact.get("feedback", {}) or {}
        stakeholder_names = [
            (s.get("name") or str(s))
            for s in artifact.get("stakeholders", [])
            if s.get("name") or str(s).strip()
        ]
        context = {
            "scope": scope,
            "project_overview": scope.get("description", ""),
            "stakeholders": artifact.get("stakeholders", []),
            "stakeholder_names": stakeholder_names,
            "requirements": artifact.get("requirements", []),
            "conflicts": artifact.get("conflicts", []),
            "open_questions": artifact.get("open_questions", []),
            "decisions": decisions,
            "system_models": artifact.get("system_models", {}),
            "feedback": feedback,
            "domain_research": feedback.get("domain_research"),
            "draft_version": draft_version if draft_version is not None else 0,
        }
        version_note = ""
        if draft_version is not None:
            version_note = f" 本稿版本: draft_v{draft_version}。"
        if round_num is not None:
            version_note += f" 對應輪次: Round {round_num}。"
        dec_tbl = analyst_draft_decision_table_note()
        task = f"""依 requirements-analyst skill，僅根據 Context 產出完整需求草稿 Markdown。{version_note}

草稿邊界：
- 這是一份草稿，不是正式定版文件；只整理 Context 內已有的需求、衝突、決議、研究與模型資訊。
- 正式需求條目只能來自 Context.requirements，並且必須逐筆保留原 id。
- 不得重新編號、不得產生新的 FR/NFR ID、不得合併或拆分需求、不得改變需求語意。

需求分區：
- Functional Requirements：只列 Context.requirements 中 type 為 FR/functional 的需求。
- Non-Functional Requirements：只列 Context.requirements 中 type 為 NFR/non-functional 的需求；若沒有 NFR，該區塊寫「無」。
- Constraints：只列 Context.requirements 中 type 為 constraint 的 verified 需求，或 Context 中已明確標記且已確認的 constraints。
- Unverified Requirements / Pending Decisions：只列 status 非 verified、pending decision、未解衝突、待補驗證或待補 acceptance 的內容；不得混入正式 Functional / Non-Functional Requirements。

需求表欄位：
- 每一筆需求列必須包含：ID、Status、Priority、Requirement、Stakeholder、Acceptance Criteria、Verification Method。

禁止事項：
- 不得新增未定案內容、量化指標、法規名稱、技術方案或依賴。
- system_models 僅作為需求理解、流程說明與模型附錄，不得從模型內容反推新增正式需求。
- domain_research 僅作為限制、風險或待確認事項，不得擴張功能範圍。
- open_questions、to_confirm、assumptions 必須保留為待確認內容，不得寫成已確認需求。

其餘草稿結構、欄位格式與品質標準，一律遵循 requirements-analyst skill。
{dec_tbl}"""
        try:
            raw = self.invoke_requirements_analyst_text(task, context)
        except Exception as e:
            self.logger.warning("draft 生成失敗: %s", e)
            return f"# Requirements Draft\n\n（生成失敗: {e}）"
        md = clean_llm_output(raw)
        expected_ids = {
            str(req.get("id") or "").strip()
            for req in requirements
            if isinstance(req, dict) and str(req.get("id") or "").strip()
        }
        draft_req_ids = set(re.findall(r"\bREQ[-_A-Za-z0-9]+\b", md or ""))
        unknown_ids = sorted(draft_req_ids - expected_ids)
        missing_ids = sorted(expected_ids - draft_req_ids)
        if unknown_ids:
            self.logger.warning("draft 包含 Context.requirements 以外的需求 ID: %s", unknown_ids)
        if missing_ids:
            self.logger.warning("draft 未保留部分 Context.requirements ID: %s", missing_ids)

        models = artifact.get("system_models", {}).get("models", [])
        if models:
            sys_hdr = "## 系統模型\n"
            md += f"\n\n---\n\n{sys_hdr}"
            for m in models:
                name = m.get("name", "未命名模型")
                plantuml = (m.get("plantuml") or "").strip()
                if plantuml:
                    md += f"\n### {name}\n\n```plantuml\n{plantuml}\n```\n"
        return md

    def ra_update_draft(self, artifact: Dict) -> Dict:
        context = {
            "requirements": artifact.get("requirements", []),
            "decisions": artifact.get("decisions", []),
            "discussions": artifact.get("discussions", []),
            "conflicts": artifact.get("conflicts", []),
            "scope": artifact.get("scope", {}),
            "domain_research": artifact.get("feedback", {}).get("domain_research"),
            "system_models": artifact.get("system_models", {}),
        }
        task = """依 requirements-analyst skill，基於 Context.requirements 更新需求。

更新邊界：
1. requirements 陣列必須保留所有既有需求 id；不得重新編號。
2. 只調整受本輪 decisions 或 discussions 直接影響的條目；與本輪無關的需求不要改動。
3. 既有 id、status、type 除非 decisions 明確要求，不得任意改動。
4. 可追加 scope 內、且由 discussions/decisions 明確支持的新需求；不得新增超出 scope.out_of_scope 的內容。
5. 不得自行新增 NFR、法規名稱、技術方案、依賴或量化指標；若只是推論，放到 open_questions/to_confirm，不要寫入 requirements。
6. 已解決的 conflict 對應需求應與決策方向一致。
7. 可整理 wording，但不得改變需求實質內容，也不得把未定案內容寫成已確認。

其餘 requirement record 與品質標準，一律遵循 requirements-analyst skill。

只輸出一個 JSON 物件：{"requirements":[...]}。"""
        try:
            data = self.invoke_requirements_analyst_json(task, context)
        except Exception as e:
            self.logger.warning(f"draft 更新失敗: {e}")
            return {
                "requirements": artifact.get("requirements", []),
                "conflicts": artifact.get("conflicts", []),
                "requirement_change_candidates": [],
            }
        requirements = data.get("requirements", artifact.get("requirements", []))
        if not isinstance(requirements, list):
            requirements = artifact.get("requirements", [])
        prev_by_id = {
            r.get("id"): r for r in artifact.get("requirements", []) if r.get("id")
        }
        returned_ids = {r.get("id") for r in requirements if r.get("id")}
        for pid, prev_req in prev_by_id.items():
            if pid not in returned_ids:
                requirements.append(dict(prev_req))
                self.logger.debug("update_draft: 補回既有需求 %s", pid)
        for req in requirements:
            normalized = self.normalize_requirement_record(req)
            req.update(normalized)
        change_candidates = self.build_requirement_change_candidates(
            artifact.get("requirements", []),
            requirements,
            artifact=artifact,
        )
        return {
            "requirements": requirements,
            "conflicts": artifact.get("conflicts", []),
            "requirement_change_candidates": change_candidates,
        }

    def build_requirement_change_candidates(
        self,
        previous_requirements: List[Dict[str, Any]],
        updated_requirements: List[Dict[str, Any]],
        *,
        artifact: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """從舊新版需求清單推導可追蹤的變更候選，不自動產生刪除。"""
        previous_by_id = {
            req.get("id"): dict(req)
            for req in previous_requirements
            if isinstance(req, dict) and req.get("id")
        }
        decisions = (artifact or {}).get("decisions", []) or []
        discussions = (artifact or {}).get("discussions", []) or []
        source_ids = [
            item.get("id")
            for item in list(decisions)[-5:] + list(discussions)[-2:]
            if isinstance(item, dict) and item.get("id")
        ]
        candidates: List[Dict[str, Any]] = []
        seen_keys = set()
        next_index = 1

        for req in updated_requirements:
            if not isinstance(req, dict):
                continue
            req_id = req.get("id")
            if not req_id:
                continue
            before = previous_by_id.get(req_id)
            if before is None:
                key = ("add", req_id)
                if key in seen_keys:
                    continue
                seen_keys.add(key)
                candidates.append(
                    {
                        "id": f"RC-{next_index:03d}",
                        "requirement_id": req_id,
                        "change_type": "add",
                        "field": "requirement",
                        "before": None,
                        "after": dict(req),
                        "reason": "Added by analyst draft update.",
                        "source_ids": list(source_ids),
                        "status": "proposed",
                    }
                )
                next_index += 1
                continue

            changed_fields = [
                field
                for field in (
                    "text",
                    "type",
                    "priority",
                    "source_stakeholders",
                    "verification_method",
                    "acceptance_criteria",
                )
                if before.get(field) != req.get(field)
            ]
            if not changed_fields:
                continue
            for field in changed_fields:
                key = ("update", req_id, field)
                if key in seen_keys:
                    continue
                seen_keys.add(key)
                candidates.append(
                    {
                        "id": f"RC-{next_index:03d}",
                        "requirement_id": req_id,
                        "change_type": "update",
                        "field": field,
                        "before": before.get(field),
                        "after": req.get(field),
                        "reason": "Updated by analyst draft refresh after decisions/discussions.",
                        "source_ids": list(source_ids),
                        "status": "proposed",
                    }
                )
                next_index += 1

        return candidates


    def invoke_requirements_analyst_text(
        self, task: str, context: Dict[str, Any]
    ) -> str:
        return self.invoke_skill("requirements-analyst", task, context=context)

    def invoke_requirements_analyst_json(
        self, task: str, context: Dict[str, Any]
    ) -> Dict[str, Any]:
        raw = self.invoke_requirements_analyst_text(task, context)
        return self.parse_topic_response_json(raw)
