# Analyst requirements logic: scope, drafts, requirement records, and change candidates.
import re
from typing import Any, Dict, List, Optional

from storage.markdown import clean_llm_output
from agents.skills.base import get_skill
from agents.profile.scenario import scenario_prompt_value

from .conflict_store import all_conflict_rows, conflict_entries_count
from .validation import (
    requirement_record as analyst_requirement_record,
    requirement_records,
    requirement_text as analyst_requirement_text,
    scope_payload,
)
from .requirements import requirement_discussion_pool
from .prompts import requirements_skill_guidance, user_requirement_extraction_contract


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
        conflict_report_md: str = "",
        meeting_record_md: str = "",
        round_num: Optional[int] = None,
    ):
        """requirements-analyst skill 統一入口。

        action:
            "analyze_scenario"        -> 回傳 Dict (scenario)
            "generate_scope"          -> 回傳 Dict (scope)
            "analyze_requirements"    -> 回傳 Dict (requirements list)
            "create_draft"            -> 回傳 str  (Markdown)
            "update_draft"            -> 回傳 Dict (requirements + change_candidates)
        """
        allowed_actions = {
            "analyze_scenario",
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
            context={
                "requirements_action": action,
                "rough_idea": rough_idea,
                "stakeholders": stakeholders or [],
                "artifact": artifact or {},
                "version": draft_version,
                "previous_draft": previous_draft,
                "conflict_report_md": conflict_report_md,
                "meeting_record_md": meeting_record_md,
                "round_num": round_num,
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
            "max_iterations": kwargs["max_iterations"],
            "stakeholder_count": len(stakeholders),
            "requirements_count": len(requirement_discussion_pool(artifact)),
            "decisions_count": len(artifact.get("decisions", []) or []),
            "conflicts_count": conflict_entries_count(artifact),
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
            if action == "analyze_scenario":
                output = self.analyze_scenario(kwargs.get("rough_idea", ""))
            elif action == "generate_scope":
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
                    draft_version=kwargs.get("version"),
                    previous_draft=kwargs.get("previous_draft"),
                    conflict_report_md=kwargs.get("conflict_report_md") or "",
                    meeting_record_md=kwargs.get("meeting_record_md") or "",
                    round_num=kwargs.get("round_num"),
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

    def analyze_scenario(self, rough_idea: str) -> Dict[str, Any]:
        context = {"rough_idea": rough_idea}
        task = """# 任務
根據 rough_idea，產生一個可實際開發的系統情境名稱。

# 判斷重點
- 將 rough_idea 轉成清楚的系統名稱。

# 輸出 JSON
{
  "scenario": {
    "name": "可以做的系統名稱"
  }
}"""
        try:
            data = self.invoke_direct_requirements_json(
                task,
                context,
                action="requirements.scenario",
            )
        except Exception as e:
            raise RuntimeError(f"scenario 分析失敗: {e}") from e
        scenario = data.get("scenario") if isinstance(data.get("scenario"), dict) else data
        name = str((scenario or {}).get("name") or "").strip()
        if not name:
            raise ValueError("scenario 分析未產生有效 name")
        return {"name": name}

    def generate_scope(
        self, rough_idea: str, stakeholders: List[Dict],
        *, artifact: Optional[Dict[str, Any]] = None,
    ) -> Dict:
        context: Dict[str, Any] = {}
        if artifact:
            if artifact.get("scenario"):
                context["scenario"] = scenario_prompt_value(artifact["scenario"])
            elif rough_idea:
                context["scenario"] = scenario_prompt_value(rough_idea)
            if artifact.get("scope"):
                context["current_scope"] = artifact["scope"]
            req_pool = requirement_discussion_pool(artifact)
            if req_pool:
                context["URL"] = req_pool
        task = """# 任務
根據產品情境與 User Requirements，界定本專案需求範圍。

# 可用資料
- scenario：產品情境。
- URL：目前已整理出的 User Requirements。

# 判斷規則
- in_scope 放本專案應處理的產品能力、使用情境、需求主題或限制。
- out_of_scope 放明確不屬於本專案、不符合產品情境，或已被排除的內容。
- 不要加入 assumptions、unknowns、description、status 或 source。

# 輸出 JSON
{
  "scope": {
    "in_scope": [],
    "out_of_scope": []
  }
}"""
        try:
            data = self.invoke_direct_requirements_json(
                task,
                context,
                action="requirements.scope",
            )
        except Exception as e:
            raise RuntimeError(f"scope 生成失敗: {e}") from e
        scope = data.get("scope") or {}
        return scope_payload(scope)

    def analyze_requirements(self, stakeholders: List[Dict]) -> Dict[str, Any]:
        all_requirements = []
        for idx, one_sh in enumerate(stakeholders):
            sh_label = one_sh.get("name") or one_sh.get("id") or f"利害關係人{idx + 1}"
            sh_texts = one_sh.get("text") or []
            if isinstance(sh_texts, list):
                sh_text = "\n".join(str(text).strip() for text in sh_texts if str(text).strip())
            else:
                sh_text = str(sh_texts or "").strip()
            context = {"stakeholders": [one_sh]}
            task = f"""請依照 requirements-analyst skill，只根據輸入的單一利害關係人內容抽取 User Requirements。

{user_requirement_extraction_contract()}
"""
            try:
                data = self.invoke_requirements_analyst_json(task, context, mode="analysis")
            except Exception as e:
                raise RuntimeError(f"需求分析失敗（{sh_label}）: {e}") from e
            raw_rows = data if isinstance(data, list) else []
            normalized_rows = [
                row for row in requirement_records([
                    {
                        **row,
                        "stakeholder": {"name": sh_label, "text": sh_text},
                        "source": "initial",
                    }
                    for row in raw_rows
                    if isinstance(row, dict)
                ])
                if row.get("stakeholder") and row.get("source")
            ]
            all_requirements.extend(normalized_rows)

        return {"requirements": all_requirements}

    def create_draft(
        self,
        artifact: Dict[str, Any],
        draft_version: Optional[int] = None,
        previous_draft: Optional[str] = None,
        conflict_report_md: str = "",
        meeting_record_md: str = "",
        round_num: Optional[int] = None,
    ) -> str:
        URL = requirement_discussion_pool(artifact)
        for req in URL:
            req_norm = self.requirement_record(req)
            req.update(req_norm)

        scope = artifact.get("scope", {}) or {}
        context = {
            "scenario": scenario_prompt_value(artifact.get("scenario", {}) or {}),
            "scope": scope,
            "stakeholders": artifact.get("stakeholders", []),
            "URL": URL,
            "conflict_report": (conflict_report_md or "").strip(),
            "meeting_record": (meeting_record_md or "").strip(),
            "feedback": artifact.get("feedback") if isinstance(artifact.get("feedback"), dict) else {},
            "system_models": artifact.get("system_models", []) or [],
            "version": draft_version if draft_version is not None else 0,
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
            task = f"""請根據上一版需求草稿與最新輸入資料，將上一版需求草稿修訂為新的需求草稿 Markdown。{version_note}

修訂方式：
- 這是文字層面的迭代修訂，不是從零重寫；請保留上一版草稿的主要章節結構、可讀格式與已仍然有效的內容。
- 依最新 User Requirements、衝突報告與會議記錄更新內容；若上一版內容已過期，必須修正或移到待確認區。
- 需求草稿條目只能來自 User Requirements，並且必須逐筆保留原 id。
- 不得重新編號、不得合併或拆分需求、不得改變需求語意。
- 新增需求只能來自 User Requirements 中已有 id 的條目；不得從上一版文字自行推導新需求。
- 若 User Requirements 已移除或不再包含某個 id，新的草稿不得保留該 id 作為需求草稿條目。

需求分區：
- Candidate Requirements：只列 User Requirements 中的候選需求。
- Pending Decisions / Open Issues：只列會議紀錄、未解衝突或待確認內容；不得混入候選需求。

需求表欄位：
- 每一筆需求列必須包含：ID、Priority、Stakeholder、Requirement、Source。

禁止事項：
- 不得新增未定案內容、未被輸入資料支持的量化指標或外部依賴。
- meeting_record 中尚未決議的問題、to_confirm、assumptions 必須保留為待確認內容，不得寫成已確認需求。
- 不得保留上一版中已被最新會議記錄或 User Requirements 推翻的內容。

若有本輪決策，請更新精簡決策表。"""
        else:
            task = f"""請根據輸入資料產出需求草稿 Markdown，讓後續正式 SRS 能追蹤需求、決策與缺口。{version_note}

草稿邊界：
- 這是一份草稿，不是正式定版文件；只整理輸入資料內已有的需求、衝突、決議與開放問題。
- 需求草稿條目只能來自 User Requirements，並且必須逐筆保留原 id。
- 不得重新編號、不得合併或拆分需求、不得改變需求語意。

需求分區：
- Candidate Requirements：只列 User Requirements 中的候選需求。
- Pending Decisions / Open Issues：只列會議紀錄、未解衝突或待確認內容；不得混入候選需求。

需求表欄位：
- 每一筆需求列必須包含：ID、Priority、Stakeholder、Requirement、Source。

禁止事項：
- 不得新增未定案內容、未被輸入資料支持的量化指標或外部依賴。
- meeting_record 中尚未決議的問題、to_confirm、assumptions 必須保留為待確認內容，不得寫成已確認需求。

若有決策，請用精簡決策表呈現。"""
        try:
            raw = self.invoke_requirements_analyst_text(task, context, mode="draft")
        except Exception as e:
            raise RuntimeError(f"draft 生成失敗: {e}") from e
        md = clean_llm_output(raw)
        expected_ids = {
            str(req.get("id") or "").strip()
            for req in URL
            if isinstance(req, dict) and str(req.get("id") or "").strip()
        }
        draft_req_ids = set(re.findall(r"\bURL-\d+\b", md or ""))
        unknown_ids = sorted(draft_req_ids - expected_ids)
        missing_ids = sorted(expected_ids - draft_req_ids)
        if unknown_ids:
            self.logger.warning("draft 包含 User Requirements 以外的需求 ID: %s", unknown_ids)
        if missing_ids:
            self.logger.warning("draft 未保留部分 User Requirements ID: %s", missing_ids)

        return md

    def update_draft(self, artifact: Dict) -> Dict:
        context = {
            "requirements": artifact.get("requirements", []),
            "decisions": artifact.get("decisions", []),
            "discussions": artifact.get("discussions", []),
            "conflicts": all_conflict_rows(artifact),
            "scope": artifact.get("scope", {}),
        }
        task = """請基於 User Requirements 更新需求，重點是消化已明確形成的 decisions / discussions 對需求文字的影響。

更新邊界：
1. requirements 陣列必須保留所有既有需求 id；不得重新編號。
2. 只調整受本輪 decisions 或 discussions 直接影響的條目；與本輪無關的需求不要改動。
3. 既有 id 除非 decisions 明確要求，不得任意改動。
4. 可追加 scope 內、且由 discussions/decisions 明確支持的新需求；不得新增超出 scope.out_of_scope 的內容。
5. 若只是推論，放到 open_questions/to_confirm，不要寫入 requirements。
6. 已解決的 conflict 對應需求應與決策方向一致。
7. 可整理 wording，但不得改變需求實質內容，也不得把未定案內容寫成已確認。
8. 每筆需求只保留 id、text、priority、stakeholder、source。
9. stakeholder 必須保留為 {"name":"...","text":"..."}，不得改成字串。
10. source 只表示來源階段，例如 initial 或 elicitation_r1；不得改成原話。

只輸出一個 JSON 物件：{"requirements":[...]}。"""
        try:
            data = self.invoke_direct_requirements_json(
                task,
                context,
                action="requirements.update_draft",
            )
        except Exception as e:
            raise RuntimeError(f"draft 更新失敗: {e}") from e
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
        change_candidates = self.build_change_record(
            artifact.get("requirements", []),
            requirements,
            artifact=artifact,
        )
        return {
            "requirements": requirements,
            "conflicts": all_conflict_rows(artifact),
            "change_record": change_candidates,
        }

    def finalize_requirements(self, artifact: Dict) -> Dict:
        candidate_pool = requirement_discussion_pool(artifact)
        context = {
            "URL": candidate_pool,
            "decisions": artifact.get("decisions", []),
            "discussions": artifact.get("discussions", []),
            "conflicts": all_conflict_rows(artifact),
            "scope": artifact.get("scope", {}),
            "stakeholders": artifact.get("stakeholders", []),
            "elicitation": artifact.get("elicitation", {}),
        }
        task = """請根據輸入資料將候選需求池定版為正式 requirements。

輸入來源：
- User Requirements 是需求池，包含初始分析與 requirement elicitation meeting 產生的候選需求。
- 會議決策、討論紀錄與衝突結果是會議協調後的正式依據。

定版規則：
1. 正式 requirements 只能來自 URL，或由 decisions/discussions 明確支持的候選修訂；不得憑空新增需求。
2. 必須消化已明確形成的 decisions 與已解決 conflicts。
3. 若候選需求重複或只是同一需求的細化，請合併成一筆正式需求。
4. 若候選需求仍缺少支持、超出 scope.out_of_scope，或只是 open question，不要寫入正式 requirements。
5. 每筆正式需求都要有 id，格式為 REQ-1、REQ-2、REQ-3；不要使用 URL-*。
6. 每筆需求只輸出 text、priority、stakeholder、source。
7. stakeholder 必須保留為 {"name":"...","text":"..."}，name 是利害關係人名稱，text 是其原話或具體情境片段。
8. source 只表示來源階段，例如 initial 或 elicitation_r1；不得改成原話。
9. priority 只能是 must、should 或 could；不收錄的項目不要輸出。

只輸出一個 JSON 物件：{"requirements":[...]}。勿輸出 Markdown。"""
        try:
            data = self.invoke_direct_requirements_json(
                task,
                context,
                action="requirements.finalize",
            )
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
            "conflicts": all_conflict_rows(artifact),
            "change_record": [],
        }

    def build_change_record(
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
                    "priority",
                    "stakeholder",
                    "source",
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
        self, task: str, context: Dict[str, Any], *, mode: str = "analysis"
    ) -> str:
        self.validate_skill_usage("requirements-analyst")
        skill = get_skill("requirements-analyst")
        skill_content = str(skill.get("content") or "")
        selected_guidance = requirements_skill_guidance(skill_content, mode)
        prompt = (
            "# Skill: requirements-analyst\n\n"
            f"{selected_guidance}\n\n"
            "# 任務\n\n"
            f"{task}"
        )
        messages = self.build_direct_messages(prompt, context=context)
        if self.tools:
            return self.chat_with_tools(messages, active_skill="requirements-analyst")
        return self.model.chat(messages, action=self.usage_action("skill.requirements-analyst"))

    def invoke_requirements_analyst_json(
        self, task: str, context: Dict[str, Any], *, mode: str = "analysis"
    ) -> Dict[str, Any]:
        raw = self.invoke_requirements_analyst_text(task, context, mode=mode)
        return self.parse_issue_response_json(raw)

    def invoke_direct_requirements_text(
        self, task: str, context: Dict[str, Any], *, action: str
    ) -> str:
        messages = self.build_direct_messages(task, context=context)
        return self.model.chat(messages, action=self.usage_action(action))

    def invoke_direct_requirements_json(
        self, task: str, context: Dict[str, Any], *, action: str
    ) -> Dict[str, Any]:
        raw = self.invoke_direct_requirements_text(task, context, action=action)
        return self.parse_issue_response_json(raw)
