# Analyst requirements logic: scope, drafts, requirement records, and change candidates.
import re
from typing import Any, Dict, List, Optional

from storage.markdown import clean_llm_output

from .validation import (
    requirement_record as analyst_requirement_record,
    requirement_records,
    requirement_text as analyst_requirement_text,
    scope_payload,
)
from .requirements import requirement_discussion_pool


class AnalystRequirements:
    def run_requirements_analyst(
        self,
        action: str,
        *,
        rough_idea: str = "",
        stakeholders: Optional[List[Dict]] = None,
        artifact: Optional[Dict[str, Any]] = None,
        draft_version: Optional[int] = None,
        previous_draft: Optional[str] = None,
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
        allowed_actions = {
            "generate_scope",
            "analyze_requirements",
            "create_draft",
            "update_draft",
            "finalize_requirements",
        }
        if action not in allowed_actions:
            raise ValueError(f"未知 requirements action: {action}")
        opa = self.run_action_loop(
            name="requirements_analysis",
            max_iterations=3,
            loop_cap=self.agent_loop_round_cap(),
            context={
                "requirements_action": action,
                "rough_idea": rough_idea,
                "stakeholders": stakeholders or [],
                "artifact": artifact or {},
                "draft_version": draft_version,
                "previous_draft": previous_draft,
                "round_num": round_num,
                "recent_decisions_limit": recent_decisions_limit,
            },
            build_observation=self.build_requirements_analysis_observation,
            decide_action=self.decide_requirements_analysis_action,
            execute_action=self.execute_requirements_analysis_action,
        )
        trace = opa.get("opa_trace") or []
        result = dict((trace[-1].get("result") if trace else {}) or {})
        if result.get("error"):
            raise RuntimeError(result.get("error"))
        return result.get("output")

    def build_requirements_analysis_observation(self, **kwargs: Any) -> Dict[str, Any]:
        artifact = kwargs.get("artifact") or {}
        stakeholders = kwargs.get("stakeholders") or []
        return {
            "action": kwargs.get("requirements_action", ""),
            "iteration": kwargs.get("iteration", 0) + 1,
            "max_iterations": kwargs.get("max_iterations", 3),
            "stakeholder_count": len(stakeholders),
            "requirements_count": len(requirement_discussion_pool(artifact)),
            "decisions_count": len(artifact.get("decisions", []) or []),
            "conflicts_count": len(artifact.get("conflicts", []) or []),
            "has_scope": bool(artifact.get("scope")),
        }

    def decide_requirements_analysis_action(
        self,
        *,
        observation: Dict[str, Any],
        last_result: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        if isinstance(last_result, dict) and not last_result.get("error"):
            return {
                "action": "done",
                "params": {},
                "reasoning": "上一輪需求分析任務已完成，結束本次 requirements analysis。",
            }
        action = str(observation.get("action") or "").strip()
        return {
            "action": action,
            "params": {},
            "reasoning": f"執行 Analyst requirements analysis 任務：{action}。",
        }

    def execute_requirements_analysis_action(
        self,
        *,
        decision: Dict[str, Any],
        **kwargs: Any,
    ) -> Dict[str, Any]:
        action = str(decision.get("action") or "").strip()
        try:
            if action == "generate_scope":
                output = self.generate_scope(
                    kwargs.get("rough_idea", ""),
                    kwargs.get("stakeholders") or [],
                    artifact=kwargs.get("artifact") or {},
                )
            elif action == "analyze_requirements":
                output = self.analyze_requirements(kwargs.get("stakeholders") or [])
            elif action == "create_draft":
                output = self.create_draft(
                    kwargs.get("artifact") or {},
                    draft_version=kwargs.get("draft_version"),
                    previous_draft=kwargs.get("previous_draft"),
                    round_num=kwargs.get("round_num"),
                    recent_decisions_limit=kwargs.get("recent_decisions_limit"),
                )
            elif action == "update_draft":
                output = self.update_draft(kwargs.get("artifact") or {})
            elif action == "finalize_requirements":
                output = self.finalize_requirements(kwargs.get("artifact") or {})
            else:
                raise ValueError(f"未知 requirements action: {action}")
        except Exception as e:
            return {
                "action": action,
                "status": "failed",
                "error": str(e),
                "summary": f"requirements analysis failed: {action}",
            }
        return {
            "action": action,
            "status": "success",
            "output": output,
            "summary": f"完成 requirements analysis: {action}",
        }

    @staticmethod
    def requirement_text(text: str) -> str:
        return analyst_requirement_text(text)

    @staticmethod
    def requirement_record(
        req: Dict[str, Any],
    ) -> Dict[str, Any]:
        return analyst_requirement_record(req)

    def generate_scope(
        self, rough_idea: str, stakeholders: List[Dict],
        *, artifact: Optional[Dict[str, Any]] = None,
    ) -> Dict:
        context: Dict[str, Any] = {"rough_idea": rough_idea, "stakeholders": stakeholders}
        if artifact:
            if artifact.get("scope"):
                context["current_scope"] = artifact["scope"]
            req_pool = requirement_discussion_pool(artifact)
            if req_pool:
                context["requirements"] = req_pool
            if artifact.get("conflicts"):
                context["conflicts"] = artifact["conflicts"]
        task = """# 任務
根據 rough_idea、stakeholder text、reqt_candidates 與目前會議結果，界定本專案需求範圍。

# 判斷規則
- in_scope 只放目前有 stakeholder 發言或 reqt_candidates 支持的產品能力、使用情境或需求主題。
- out_of_scope 只放明確超出產品目標、利害關係人情境或已被排除的內容。
- 不要加入 assumptions、unknowns、description、status、source。
- 若已有 current_scope，請修正與補充，不要整份重寫。
- 勿輸出 Markdown。

# 輸出
{
  "scope": {
    "in_scope": [],
    "out_of_scope": []
  }
}"""
        try:
            data = self.invoke_requirements_analyst_json(task, context)
        except Exception as e:
            raise RuntimeError(f"scope 生成失敗: {e}") from e
        scope = data.get("scope") or {}
        return scope_payload(scope)

    def analyze_requirements(self, stakeholders: List[Dict]) -> Dict[str, Any]:
        all_requirements = []
        for idx, one_sh in enumerate(stakeholders):
            sh_label = one_sh.get("name") or one_sh.get("id") or f"利害關係人{idx + 1}"
            context = {"stakeholders": [one_sh]}
            task = f"""請只根據 Context 中此單一利害關係人的訊號，抽取結構化需求。

只輸出：
{{"requirements":[...]}}

分析邊界：
- 本輪只分析此一利害關係人。
- source_stakeholders 固定填 ["{sh_label}"]，這必須是 Context.stakeholders[0].name。
- source_stakeholders 不可填 user、analyst、expert、modeler、system 或任何不在 Context.stakeholders 中的名稱。
- id 先不要定，由系統後續指派。
- 每筆需求都必須有 text、type、priority、source_stakeholders、source、acceptance_criteria。
- source 必須引用此 source_stakeholders 在 Context 中說過的原話或具體情境片段；不可填分析階段名稱、agent 名稱或泛稱。
- acceptance_criteria 必須可觀察、可驗收；不能只重述 text。
- 若 type 是 NFR，請輸出初步 metric 與 target；metric 是要觀察或衡量的指標，target 是目標條件或待確認門檻。
- NFR 的 metric/target 只能根據此利害關係人的 text 推導；資訊不足時 target 請寫「待確認」，不要憑空填入數字。
- 資訊不足時不要硬產生需求，改由後續 open question 處理。
- 勿輸出 Markdown。

其餘 requirement record 內容與品質標準，一律遵循 requirements-analyst skill。"""
            try:
                data = self.invoke_requirements_analyst_json(task, context)
            except Exception as e:
                raise RuntimeError(f"需求分析失敗（{sh_label}）: {e}") from e
            all_requirements.extend(
                requirement_records(data.get("requirements", []))
            )

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

    def create_draft(
        self,
        artifact: Dict[str, Any],
        draft_version: Optional[int] = None,
        previous_draft: Optional[str] = None,
        round_num: Optional[int] = None,
        recent_decisions_limit: Optional[int] = None,
    ) -> str:
        requirements = requirement_discussion_pool(artifact)
        for req in requirements:
            req_norm = self.requirement_record(req)
            req.update(req_norm)

        _ = recent_decisions_limit
        decisions = artifact.get("decisions", [])
        scope = artifact.get("scope", {}) or {}
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
            "requirements": requirements,
            "conflicts": artifact.get("conflicts", []),
            "open_questions": artifact.get("open_questions", []),
            "decisions": decisions,
            "draft_version": draft_version if draft_version is not None else 0,
        }
        previous_draft_text = (previous_draft or "").strip()
        is_revision = bool(previous_draft_text and draft_version and draft_version > 0)
        if is_revision:
            context["previous_draft"] = previous_draft_text
        version_note = ""
        if draft_version is not None:
            version_note = f" 本稿版本: draft_v{draft_version}。"
        if round_num is not None:
            version_note += f" 對應輪次: Round {round_num}。"
        if is_revision:
            task = f"""請根據 Context.previous_draft 與最新 Context，將上一版需求草稿修訂為新的需求草稿 Markdown。{version_note}

修訂方式：
- 這是文字層面的迭代修訂，不是從零重寫；請保留上一版草稿的主要章節結構、可讀格式與已仍然有效的內容。
- 依最新 Context.requirements、decisions、conflicts、open_questions 更新內容；若上一版內容已過期，必須修正或移到待確認區。
- 正式需求條目只能來自 Context.requirements，並且必須逐筆保留原 id。
- 不得重新編號、不得產生新的 FR/NFR ID、不得合併或拆分需求、不得改變需求語意。
- 新增 requirement 只能來自 Context.requirements 中已有 id 的條目；不得從上一版文字自行推導新需求。
- 若 Context.requirements 已移除或不再包含某個 id，新的草稿不得保留該 id 作為正式需求。

需求分區：
- Functional Requirements：只列 Context.requirements 中 type 為 FR/functional 的需求。
- Non-Functional Requirements：只列 Context.requirements 中 type 為 NFR/non-functional 的需求；若沒有 NFR，該區塊寫「無」。
- Constraints：只列 Context.requirements 中 type 為 constraint 的需求，或 Context 中已明確標記且已確認的 constraints。
- Pending Decisions / Open Issues：只列 pending decision、未解衝突或待補 acceptance 的內容；不得混入正式 Functional / Non-Functional Requirements。

需求表欄位：
- 每一筆需求列必須包含：ID、Priority、Requirement、Stakeholder、Acceptance Criteria。
- 若 Acceptance Criteria 缺漏，必須保留缺口狀態，不得替需求補未被 Context 支持的內容。

禁止事項：
- 不得新增未定案內容、未被 Context 支持的量化指標或外部依賴。
- open_questions、to_confirm、assumptions 必須保留為待確認內容，不得寫成已確認需求。
- 不得保留上一版中已被最新 decisions 或 Context.requirements 推翻的內容。

其餘草稿結構、欄位格式與品質標準，一律遵循 requirements-analyst skill。
若有本輪決策，請更新精簡決策表。"""
        else:
            task = f"""請根據 Context 產出需求草稿 Markdown，讓後續正式 SRS 能追蹤需求、決策與缺口。{version_note}

草稿邊界：
- 這是一份草稿，不是正式定版文件；只整理 Context 內已有的需求、衝突、決議與開放問題。
- 正式需求條目只能來自 Context.requirements，並且必須逐筆保留原 id。
- 不得重新編號、不得產生新的 FR/NFR ID、不得合併或拆分需求、不得改變需求語意。

需求分區：
- Functional Requirements：只列 Context.requirements 中 type 為 FR/functional 的需求。
- Non-Functional Requirements：只列 Context.requirements 中 type 為 NFR/non-functional 的需求；若沒有 NFR，該區塊寫「無」。
- Constraints：只列 Context.requirements 中 type 為 constraint 的需求，或 Context 中已明確標記且已確認的 constraints。
- Pending Decisions / Open Issues：只列 pending decision、未解衝突或待補 acceptance 的內容；不得混入正式 Functional / Non-Functional Requirements。

需求表欄位：
- 每一筆需求列必須包含：ID、Priority、Requirement、Stakeholder、Acceptance Criteria。
- 若 Acceptance Criteria 缺漏，必須保留缺口狀態，不得替需求補未被 Context 支持的內容。

禁止事項：
- 不得新增未定案內容、未被 Context 支持的量化指標或外部依賴。
- open_questions、to_confirm、assumptions 必須保留為待確認內容，不得寫成已確認需求。

其餘草稿結構、欄位格式與品質標準，一律遵循 requirements-analyst skill。
若有決策，請用精簡決策表呈現。"""
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

        return md

    def update_draft(self, artifact: Dict) -> Dict:
        context = {
            "requirements": artifact.get("requirements", []),
            "decisions": artifact.get("decisions", []),
            "discussions": artifact.get("discussions", []),
            "conflicts": artifact.get("conflicts", []),
            "scope": artifact.get("scope", {}),
        }
        task = """請基於 Context.requirements 更新需求，重點是消化已明確形成的 decisions / discussions 對需求文字與驗收欄位的影響。

更新邊界：
1. requirements 陣列必須保留所有既有需求 id；不得重新編號。
2. 只調整受本輪 decisions 或 discussions 直接影響的條目；與本輪無關的需求不要改動。
3. 既有 id、type 除非 decisions 明確要求，不得任意改動。
4. 可追加 scope 內、且由 discussions/decisions 明確支持的新需求；不得新增超出 scope.out_of_scope 的內容。
5. 若只是推論，放到 open_questions/to_confirm，不要寫入 requirements。
6. 已解決的 conflict 對應需求應與決策方向一致。
7. 可整理 wording，但不得改變需求實質內容，也不得把未定案內容寫成已確認。
8. acceptance_criteria 只能根據已確認討論補強；如果缺少驗收資訊，保留空值或待確認，不要自行補驗收條件。

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
            normalized = self.requirement_record(req)
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

    def finalize_requirements(self, artifact: Dict) -> Dict:
        candidate_pool = requirement_discussion_pool(artifact)
        context = {
            "reqt_candidates": candidate_pool,
            "decisions": artifact.get("decisions", []),
            "discussions": artifact.get("discussions", []),
            "conflicts": artifact.get("conflicts", []),
            "scope": artifact.get("scope", {}),
            "stakeholders": artifact.get("stakeholders", []),
            "elicitation": artifact.get("elicitation", {}),
        }
        task = """請根據 Context 將候選需求池定版為正式 requirements。

輸入來源：
- Context.reqt_candidates 是需求池，包含初始分析與 requirement elicitation meeting 產生的候選需求。
- Context.decisions / discussions / conflicts 是會議協調後的決策、討論與衝突結果。

定版規則：
1. 正式 requirements 只能來自 reqt_candidates，或由 decisions/discussions 明確支持的候選修訂；不得憑空新增需求。
2. 必須消化已明確形成的 decisions 與已解決 conflicts。
3. 若候選需求重複或只是同一需求的細化，請合併成一筆正式需求。
4. 若候選需求仍缺少支持、超出 scope.out_of_scope，或只是 open question，不要寫入正式 requirements。
5. 每筆正式需求都要有 id，格式為 REQ-1、REQ-2、REQ-3；不要使用 REQT-CAND-*。
6. 每筆需求都必須包含 text、type、priority、source_stakeholders、source、acceptance_criteria。
7. source_stakeholders 只能使用 Context.stakeholders 中的 name，不可填 user、analyst、expert、modeler、system。
8. source 必須保留利害關係人原話或具體情境片段，不可填流程名稱或 agent 名稱。
9. acceptance_criteria 只能根據候選需求、會議討論或決策補強；資訊不足時保留簡短缺口，不要自行編造。

只輸出一個 JSON 物件：{"requirements":[...]}。勿輸出 Markdown。"""
        try:
            data = self.invoke_requirements_analyst_json(task, context)
        except Exception as e:
            raise RuntimeError(f"正式 requirements 定版失敗: {e}") from e
        requirements = data.get("requirements", [])
        if not isinstance(requirements, list):
            requirements = []
        normalized: List[Dict[str, Any]] = []
        seen_ids = set()
        for idx, req in enumerate(requirements, 1):
            if not isinstance(req, dict):
                continue
            row = self.requirement_record(req)
            if not row.get("text"):
                continue
            rid = str(row.get("id") or "").strip()
            if not re.fullmatch(r"REQ-\d+", rid) or rid in seen_ids:
                rid = f"REQ-{len(normalized) + 1}"
            row["id"] = rid
            seen_ids.add(rid)
            normalized.append(row)
        return {
            "requirements": normalized,
            "conflicts": artifact.get("conflicts", []),
            "requirement_change_candidates": [],
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
            for item in list(decisions) + list(discussions)
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
                        "id": f"RC-{next_index}",
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
                        "id": f"RC-{next_index}",
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
        return self.parse_issue_response_json(raw)
