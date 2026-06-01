import copy

# Analyst agent: requirement extraction, conflict analysis, elicitation, and issue response.
from typing import Any, Dict, List, Optional

from agents.base import BaseAgent

from .conflicts import AnalystConflicts
from .elicitation import AnalystElicitation
from .analyze import AnalystRequirements
from .issues import AnalystIssues
from .prompts import ANALYST_SYSTEM_PROMPT
from .requirements import ensure_requirement_candidate_ids, requirement_dedupe_key
from .validation import scope_payload


class AnalystAgent(
    AnalystIssues,
    AnalystRequirements,
    AnalystConflicts,
    AnalystElicitation,
    BaseAgent,
):
    name = "analyst"

    system_prompt = ""

    def __init__(
        self,
        model,
        tools: Optional[list] = None,
        registry=None,
        project_config=None,
    ):
        super().__init__(
            model,
            tools=tools,
            registry=registry,
            skill_names=["conflict-analyzer", "requirements-analyst"],
            project_config=project_config,
        )
        from agents.skills.base import get_skill

        parts = []
        for skill_name in ("requirements-analyst", "conflict-analyzer"):
            skill = get_skill(skill_name)
            if skill.get("content_system"):
                parts.append(skill["content_system"])
        blocks = [ANALYST_SYSTEM_PROMPT]
        blocks.extend(parts)
        self.system_prompt = "\n\n---\n\n".join([b for b in blocks if b])

    def get_optional_skill_context(
        self, issue: Dict, artifact_context: Optional[Dict]
    ) -> Optional[str]:
        return super().get_optional_skill_context(issue, artifact_context)

    def skill_usage_policy(self) -> str:
        return """requirements-analyst：
- 用於需求品質、需求文字、需求欄位完整性、acceptance criteria、可驗收性、歧義與 scope 邊界判斷。
- 用於 ELICIT 或會議回答需要轉成 requirement candidate、requirement change candidate 或 open question 時。
- 輸出限於需求品質與需求資料整理；遇到無法由需求證據支持的內容，改列 open question 或 change candidate。

conflict-analyzer：
- 用於 requirement pair conflict classification、conflict_discussion、需求間互斥/重疊/語義關係、SRS 條文衝突、驗收衝突、責任不清、scope 不清、重複但不一致，以及 requirement-level resolution options。
- 輸出限於需求間關係判斷與 resolution options；缺乏判斷依據時保留不確定性。

若議題只需要 Analyst 根據目前專案資料做一般需求分析，不要使用 skill。"""

    def tool_usage_policy(self, active_skill: Optional[str] = None) -> str:
        return """- artifact_query 用於查詢目前需求、衝突、open_questions、decisions 與相關來源。
- 使用工具取得專案事實後，仍須以 Analyst 角色判斷需求品質、可測試性、追蹤性與 scope 邊界。
- 工具結果不得直接覆蓋已定案需求；有不確定性時提出 open question 或 change candidate。"""

    def build_issue_response_observation(self, **kwargs: Any) -> Dict[str, Any]:
        return self.issue_response_observation(**kwargs)

    def decide_issue_response_action(
        self,
        *,
        observation: Dict[str, Any],
        last_result: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        return self.issue_response_decision(
            observation,
            done_reasoning="上一輪需求分析師回應已符合格式契約，結束本次回應。",
            active_reasoning="根據議題類型選擇需求分析師回應策略。",
            available_actions={
                "answer_question": "使用時機：有人在 open_questions 中指定 analyst 回答。不要使用：一般議題發言或資料更新。寫回或影響：只回答問題，不更新專案資料。",
                "respond_issue": "使用時機：只需要根據議題、前文與現有資料表達分析意見。不要使用：需要抽取需求、更新 scope、正式化 REQ-* 需求條目或處理衝突時。寫回或影響：只產生會議發言，不更新需求、scope 或衝突報告。",
                "analyze_requirements": "使用時機：會議中 stakeholder 以自然語言提出、補充或改寫需求。不要使用：只是整理既有 User Requirements 或討論既有衝突報告。寫回或影響：抽取需求候選或需求變更候選，並更新對應 User Requirement 來源。",
                "refine_scope": "使用時機：議題明確討論系統邊界、in scope / out of scope、外部系統或第三方責任。不要使用：只是在補需求文字或處理衝突解法。寫回或影響：更新 scope.json。",
                "refine_requirement": "使用時機：需要把已整理的 User Requirements 或會議決議正式化為 REQ-* 需求條目。不要使用：stakeholder 剛提出尚未整理的新需求，或只是判斷 scope。寫回或影響：更新 REQ-* 需求條目，包含類型、驗收條件、相依性、風險、假設與來源追蹤。",
                "analyze_conflicts": "使用時機：同一輪已先執行 analyze_requirements，且確實產生新需求或需求變更候選。不要使用：只是討論既有衝突報告的解法。寫回或影響：重新辨識衝突並產生新的衝突報告。",
                "discuss_conflict": "使用時機：針對既有衝突報告的解決選項與建議解法做採用、調整或人類裁決取捨。不要使用：有新需求需重新跑衝突辨識。寫回或影響：只形成會議發言與提案，不直接重跑衝突辨識。",
            },
            default_action="respond_issue",
            last_result=last_result,
        )

    def execute_issue_response_action(
        self,
        *,
        decision: Dict[str, Any],
        **kwargs: Any,
    ) -> Dict[str, Any]:
        action = str(decision.get("action") or "").strip()
        artifact = kwargs.get("artifact")
        analyst_action_result = None
        if isinstance(artifact, dict):
            try:
                if action == "analyze_requirements":
                    meeting_stakeholders = self.meeting_requirement_sources(
                        kwargs.get("previous_responses"),
                        kwargs["issue"],
                    )
                    output = self.run_requirements_analyst(
                        "analyze_requirements",
                        stakeholders=meeting_stakeholders,
                        artifact=artifact,
                    )
                    self.merge_meeting_requirements(
                        artifact,
                        output,
                        issue=kwargs["issue"],
                    )
                    analyst_action_result = {
                        "action": action,
                        "output": output,
                    }
                elif action == "refine_scope":
                    analyst_action_result = self.execute_refine_scope(
                        artifact=artifact,
                        issue=kwargs["issue"],
                        previous_responses=kwargs.get("previous_responses"),
                    )
                elif action == "refine_requirement":
                    analyst_action_result = self.execute_refine_requirement(
                        artifact=artifact,
                        issue=kwargs["issue"],
                        previous_responses=kwargs.get("previous_responses"),
                    )
                elif action == "analyze_conflicts":
                    analyst_action_result = self.execute_issue_conflict_analysis(
                        artifact=artifact,
                        last_result=kwargs.get("last_result"),
                    )
                elif action == "discuss_conflict":
                    analyst_action_result = {
                        "action": action,
                        "output": None,
                        "summary": "讀取既有衝突報告，針對解決選項與建議解法討論取捨，不重新執行衝突辨識。",
                    }
                elif action == "respond_issue":
                    analyst_action_result = {
                        "action": action,
                        "output": None,
                        "summary": "只產生會議回答，不更新專案資料。",
                    }
                elif action == "answer_question":
                    analyst_action_result = {
                        "action": action,
                        "output": None,
                        "summary": "回答 open question，不更新專案資料。",
                    }
            except Exception as e:
                analyst_action_result = {
                    "action": action,
                    "error": str(e),
                    "summary": f"analyst action failed: {action}",
                }
        elif action in {
            "analyze_requirements",
            "refine_scope",
            "refine_requirement",
            "analyze_conflicts",
        }:
            return {
                "action": action,
                "status": "failed",
                "error": "missing_artifact",
                "format_error": f"{action} requires artifact context",
                "summary": f"analyst {action} 缺少 artifact，無法執行分析",
            }
        return {
            "action": decision.get("action", ""),
            "status": "success",
            "action_result": analyst_action_result or {"action": action, "output": None},
            "summary": f"完成 analyst action: {decision.get('action', '')}",
        }

    def execute_refine_requirement(
        self,
        *,
        artifact: Dict[str, Any],
        issue: Dict[str, Any],
        previous_responses: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        current_REQ = self.requirement_context(artifact)
        current_URL = self.scope_requirement_context(artifact)
        scope = artifact.get("scope") if isinstance(artifact.get("scope"), dict) else {}
        feedback = self.feedback_context(artifact.get("feedback"))
        system_models = self.system_model_context(artifact)
        discussion = self.scope_discussion_context(previous_responses)
        source_id = str(issue.get("meeting_id") or issue.get("id") or "").strip()
        generated_all: List[Dict[str, Any]] = []
        final_coverage: List[Dict[str, Any]] = []
        reasons: List[str] = []
        max_passes = 3
        coverage_gaps: List[Dict[str, Any]] = []
        for pass_index in range(max_passes):
            current_REQ = self.requirement_context(artifact)
            requirement_mode = "update" if current_REQ else "create"
            context = {
                "issue": {
                    "id": issue.get("id"),
                    "meeting_id": issue.get("meeting_id"),
                    "title": issue.get("title"),
                    "category": issue.get("category"),
                    "trace": issue.get("trace", {}),
                },
                "current_URL": current_URL,
                "current_REQ": current_REQ,
                "scope": scope,
                "feedback": feedback,
                "system_models": system_models,
                "discussion": discussion,
                "mode": requirement_mode,
                "coverage_gaps": coverage_gaps,
                "pass": pass_index + 1,
            }
            task = self.refine_requirement_task(
                requirement_mode=requirement_mode,
                source_id=source_id,
                coverage_gaps=coverage_gaps,
            )
            data = self.invoke_requirements_analyst_object_json(
                task,
                context,
                mode="refine_requirement",
            )
            generated = self.clean_requirement_records(
                data.get("REQ") if isinstance(data, dict) else [],
                existing=artifact.get("REQ", []),
                source_ref=source_id,
            )
            if generated:
                artifact["REQ"] = self.merge_requirement_records(
                    artifact.get("REQ", []),
                    generated,
                )
                generated_all.extend(generated)
                meta = artifact.setdefault("meta", {})
                meta["requirements_changed"] = True
                meta["requirements_changed_by"] = source_id
                meta["requirements_changed_reason"] = "refine_requirement"
            reason = str((data or {}).get("reason") or "").strip()
            if reason:
                reasons.append(reason)
            final_coverage = self.requirement_coverage_records(
                artifact,
                data.get("coverage") if isinstance(data, dict) else [],
            )
            coverage_gaps = self.refine_requirement_coverage_gaps(final_coverage, current_URL)
            if not coverage_gaps:
                break

        return {
            "action": "refine_requirement",
            "REQ": generated_all,
            "coverage": final_coverage,
            "coverage_gaps": coverage_gaps,
            "coverage_summary": self.requirement_coverage_summary(final_coverage),
            "reason": "；".join(reasons),
            "source_id": source_id,
        }

    def refine_requirement_task(
        self,
        *,
        requirement_mode: str,
        source_id: str,
        coverage_gaps: Optional[List[Dict[str, Any]]] = None,
    ) -> str:
        gap_rule = ""
        if coverage_gaps:
            gap_rule = f"""
# 本次補齊目標
- 上一輪仍有 {len(coverage_gaps)} 筆 User Requirements 沒有明確去處。
- 本輪只處理 coverage_gaps 中列出的 URL-*。
- 對每筆 gap 必須二選一：
  1. 併入既有 REQ 或新增 REQ，並讓該 URL-* 出現在 REQ.source_ids。
  2. 若需求分類討論已明確判斷該 URL-* 不需要、超出範圍、仍需確認或只能作為風險/假設，則在 coverage 標為 excluded、needs_clarification、risk 或 assumption，並寫清楚 reason。
- 不要重寫已完整覆蓋的 REQ；只補缺口。
"""
        task = f"""# 任務
根據最新 current_URL、既有 current_REQ、scope、feedback、system_models 與本議題討論，精煉 requirements.json 中的 REQ-* 需求條目。
目標是讓 Requirements 更接近可寫入 SRS 的需求規格，而不是重新抽取 User Requirements。

# 模式
- mode={requirement_mode}
- create：根據 current_URL、scope、feedback 與 system_models，建立初步 REQ-* 需求條目，並以 type 分為 functional 或 non_functional。
- update：根據 current_URL、current_REQ、scope、feedback、system_models 與本議題討論修正既有 REQ-*；若 current_URL 或相關 artifact 明確顯示尚未覆蓋的重要功能需求或非功能需求，應新增 REQ。

# 規則
- current_URL 是最新 User Requirements 的權威來源；current_REQ 是結構化回寫基底。
- scope 只用來判斷需求是否屬於本系統範圍，不要把 scope 句子直接改寫成需求。
- feedback 只可作為領域背景、品質限制、風險與建議來源。
- feedback.findings 只能作為 rationale 或背景依據，不得單獨形成正式需求。
- feedback.constraints 若會影響系統品質、服務水準、安全、隱私、稽核、可靠性或可用性，可輔助形成 non_functional REQ；若仍不確定，放入 assumptions、risks 或 open_questions。
- feedback.risks 不得直接變成新的需求；只能寫入受影響 REQ 的 risks，或在風險代表品質底線時輔助形成 non_functional REQ。
- feedback.recommendations 只能作為建議依據；必須有 current_URL、會議決議或明確來源支持，才可轉成 REQ 欄位。
- system_models 只可作為流程、actor、資料、狀態或一致性參考，不得從模型單獨創造 stakeholder 未支持的新功能。
- 若 current_URL、scope、feedback、system_models 或本議題討論沒有呈現的內容，不要自行補入。
- 每筆新增或更新的 REQ 必須能追蹤到 current_URL 或相關 artifact 中看得到的來源，例如 URL-*、Meeting R*-M*、Feedback、Model SM-* 或既有 REQ-*。
- 若來源只來自 Feedback，只能形成 non_functional、risk 或 assumption，不得直接形成新的功能需求。
- 若來源只來自 System Models，只能用來補足流程、角色、資料、狀態或一致性缺口，不得單獨創造 stakeholder 未支持的新功能。
- User Requirements 可合併成一筆 REQ，但不得無聲略過 current_URL 中明確重要且尚未被 current_REQ 覆蓋的需求群。
- 本動作只做需求整理與初步正式化，不做業務裁決；來源需求未明確支持的優先順序、例外規則、數值門檻或取捨不要自行決定。
- 對不明確或有爭議的內容，放入 assumptions、risks 或在會議回覆中提出 open_questions；不要硬寫成確定需求。
- update 模式若要修正既有項目，必須保留該項 REQ-* id；create 模式不要自行編 id。
- type 只能是 functional 或 non_functional。
- 分類規則：
  - functional：描述系統提供的功能、流程、狀態變更、資料處理、通知、查詢、權限操作或紀錄能力。
  - non_functional：描述系統品質或服務水準，例如 performance、availability、security、privacy、usability、reliability、auditability、maintainability。若品質目標缺少數值，仍可產生 NFR，但 metric、validation 或 acceptance_criteria 留空，缺口放入 assumptions、risks 或 open_questions。
- 若同一組 URL 同時包含「系統能力」與「品質、治理或限制條件」，不要硬塞成一筆 functional；應拆成兩筆或多筆 REQ：
  - functional：功能、流程、資料處理、通知、查詢、操作、狀態變更。
  - non_functional：安全、隱私、稽核、可靠性、可用性、效能、透明性、公平性、合規、風險控制、資料保存或權限治理。
- 只有當品質或治理條件會影響驗收、設計、風險、權限、資料保存、稽核、可靠性、效能、可用性、安全、隱私或法規時才拆 non_functional；不要只因為文字出現「簡單、友善、快速、清楚」就拆 NFR，除非來源或討論明確支持可驗收的品質要求。
- non_functional 必須有 source_ids，且來源必須能在 current_URL、feedback、會議決議或相關 artifact 中找到；不得為了補齊 SRS 自行新增品質要求。
- 常見拆分例：
  - 查詢異常事件詳情 → functional。
  - 查詢需授權、留稽核、保護敏感資料 → non_functional。
  - 發送異常通知 → functional。
  - 重大異常通知需具備可靠性、可追蹤與不中斷服務要求 → non_functional。
- priority 只能是 must、should 或 could。
- description 使用「系統應...」或等價的可驗證系統行為，不要寫 stakeholder 願望句。
- acceptance_criteria 只有在來源需求或本議題討論明確支持可觀察結果、狀態、通知、查詢、紀錄、權限、保存或例外行為時才填。
- 不要把 acceptance_criteria 寫成重述 description；每一點應描述可驗證的系統行為或結果。
- 若缺少數值、時限、責任角色、例外處理或成功條件，不要硬補 acceptance_criteria；將缺口放入 assumptions、risks 或會議回覆的 open_questions。
- rationale 只有來源需求、會議討論、衝突決議或領域回饋明確支持時才填；不得用「由來源需求整理而來」這類空泛理由補滿。
- dependencies 只放已由來源或討論明確支持的 requirement id；不確定的依賴放入 assumptions 或 open_questions，不要猜。
- risks 只放會影響需求成立、驗收、合規、營運或模型一致性的風險。
- assumptions 只放目前採用但尚未完全確認的前提。
- non_functional 可包含 category、metric、validation；缺少明確數值或驗證方式時留空，不要自行補 TPS、延遲、可用性、法規名稱或「待確認」。
- functional 也可使用 validation 表示驗證方法；只有來源或討論明確支持驗證方法時才填，否則留空。
- priority 若來源或討論沒有明確優先級，填 should；這只代表預設排序，不代表 stakeholder 已明確表態。
- title 只能由 description 濃縮，不得新增 description 沒有的語意。
- status 使用 proposed；source_meeting 固定包含：{source_id}
- 避免和既有 REQ-* 需求條目重複；若只是同義改寫，不要重複輸出。
- 請優先補齊 current_URL 與相關 artifact 中可明確形成需求的 Functional 與 Non-Functional；不要只輸出功能需求。
- update 模式不是只審查 current_REQ；若 current_URL 有尚未被 current_REQ.source_ids 覆蓋、且語意已足以形成系統行為或限制的需求群，必須新增 REQ。
- 不要因為 current_URL 數量多就只輸出前幾筆或只寫 coverage；應將相近 URL 合併為較高層、可驗收的 REQ，讓每個清楚的 URL 至少被某筆 REQ.source_ids 覆蓋。
- 只有語意不完整、互相衝突、需要人類裁決或明確超出範圍的 URL，才可在 coverage 標為 needs_clarification、risk、assumption 或 excluded。
- 若本次輸出後仍有大量清楚 URL 未覆蓋，視為本任務未完成；請回到 current_URL 繼續分群並新增 REQ，而不是把補齊工作留到後續。
- 採用 coverage-driven refinement：每個 current_URL 中的 URL-* 都必須有去處，不能靜默略過。
- 若 URL-* 已形成或被合併進 REQ，該 URL-* 必須出現在某筆 REQ.source_ids。
- 若 URL-* 暫時不能形成 REQ，必須在 coverage 標記為 needs_clarification、assumption、risk 或 excluded，並說明 reason；不要硬寫成確定需求。
- coverage 必須涵蓋每個 current_URL 的 id，且 covered_by 只能引用本次輸出或既有 current_REQ 中的 REQ-*。
- 需求分類討論可以確認某個 User Requirement 是否仍需要；若 discussion 中 user/analyst 明確表示不需要、合併後已被取代、超出範圍或暫不納入，coverage 使用 excluded 或 needs_clarification，並在 reason 說明依據。
{gap_rule}

# 輸出 JSON
{{
  "REQ": [
    {{
      "type": "functional",
      "id": "update 模式才填既有 REQ-*；create 模式省略或留空",
      "title": "短標題",
      "description": "系統應...",
      "priority": "must",
      "source_ids": ["URL-1"],
      "source_meeting": ["{source_id}"],
	      "acceptance_criteria": [],
	      "rationale": "為何由這些 User Requirements 形成此需求條目",
	      "dependencies": [],
	      "risks": [],
      "assumptions": [],
      "category": "",
      "metric": "",
      "validation": "",
      "status": "proposed"
    }}
  ],
  "coverage": [
    {{
      "source_id": "URL-1",
      "status": "covered | needs_clarification | assumption | risk | excluded",
      "covered_by": ["REQ-1"],
      "reason": "為何已覆蓋或為何暫不能形成 REQ"
    }}
  ],
  "reason": "一句說明"
}}"""
        return task

    def execute_refine_scope(
        self,
        *,
        artifact: Dict[str, Any],
        issue: Dict[str, Any],
        previous_responses: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        current_scope = scope_payload(artifact.get("scope", {}))
        requirements = self.scope_requirement_context(artifact)
        discussion = self.scope_discussion_context(previous_responses)
        source_id = str(issue.get("meeting_id") or issue.get("id") or "").strip()
        context = {
            "issue": {
                "id": issue.get("id"),
                "meeting_id": issue.get("meeting_id"),
                "title": issue.get("title"),
                "category": issue.get("category"),
                "trace": issue.get("trace", {}),
            },
            "current_scope": current_scope,
            "requirements": requirements,
            "discussion": discussion,
            "scenario": str(artifact.get("scenario") or "").strip(),
        }
        task = f"""# 任務
根據 requirements 與本議題討論，產生 scope.json 的最小更新。

# 規則
- 主要依據 requirements 與 discussion；scenario 只能作為薄背景，不得用來新增 requirements 沒有支持的 scope。
- 只在討論已明確指出系統邊界、第三方責任、線下流程、in scope 或 out of scope 時更新。
- 不讀取 feedback、系統模型、衝突報告或 draft 作為直接 scope 來源。
- 不改寫需求、不產生 system requirement。
- Scope 是專案邊界，不是需求清單；詳細功能、驗收條件、限制與風險留給後續需求條目與草稿章節處理。
- 不得把單一 URL-* 或 REQ-* 改寫成 scope item。
- in_scope_add 只放高層系統責任邊界、能力域、流程域、資料責任或外部介接邊界。
- out_of_scope_add 放明確不屬於本系統、由第三方/線下/外部組織負責，或會議已裁定排除的內容。
- 若討論只是補功能、驗收條件、限制、風險或需求文字，應交給 refine_requirement，不要更新 scope。
- 只有當會議明確裁定「屬於本系統 / 不屬於本系統 / 第三方負責 / 人工流程負責」時才更新 scope。
- remove 只在既有 scope 明顯被本議題決議推翻時使用；沒有明確依據請留空。
- 每個項目都要是短句，不要放空泛目標；新增後整體 scope 應維持精簡，若只是更細的需求，不要加入。
- source_id 固定使用：{source_id}

# 輸出 JSON
{{
  "scope_updates": {{
    "in_scope_add": [],
    "out_of_scope_add": [],
    "in_scope_remove": [],
    "out_of_scope_remove": []
  }},
  "reason": "一句說明",
  "source_id": "{source_id}"
}}"""
        data = self.invoke_direct_requirements_object_json(
            task,
            context,
            action="requirements.refine_scope",
        )
        updates = self.clean_scope_updates(data.get("scope_updates") if isinstance(data, dict) else {})
        updated_scope = self.apply_scope_updates(current_scope, updates)
        artifact["scope"] = updated_scope
        return {
            "action": "refine_scope",
            "scope_updates": updates,
            "scope": updated_scope,
            "reason": str((data or {}).get("reason") or "").strip(),
            "source_id": source_id,
        }

    @staticmethod
    def clean_scope_updates(raw: Any) -> Dict[str, List[str]]:
        source = raw if isinstance(raw, dict) else {}
        updates: Dict[str, List[str]] = {}
        for key in ("in_scope_add", "out_of_scope_add", "in_scope_remove", "out_of_scope_remove"):
            value = source.get(key)
            if isinstance(value, list):
                rows = [str(item).strip() for item in value if str(item).strip()]
            else:
                text = str(value or "").strip()
                rows = [text] if text else []
            updates[key] = list(dict.fromkeys(rows))
        return updates

    @staticmethod
    def apply_scope_updates(current_scope: Dict[str, Any], updates: Dict[str, List[str]]) -> Dict[str, List[str]]:
        scope = scope_payload(current_scope)

        def remove_items(rows: List[str], removals: List[str]) -> List[str]:
            remove_set = {item.strip().lower() for item in removals if item.strip()}
            return [item for item in rows if item.strip().lower() not in remove_set]

        def add_items(rows: List[str], additions: List[str]) -> List[str]:
            seen = {item.strip().lower() for item in rows if item.strip()}
            out = list(rows)
            for item in additions:
                marker = item.strip().lower()
                if marker and marker not in seen:
                    out.append(item)
                    seen.add(marker)
            return out

        in_scope = remove_items(scope.get("in_scope", []), updates.get("in_scope_remove", []))
        out_scope = remove_items(scope.get("out_of_scope", []), updates.get("out_of_scope_remove", []))
        in_scope = add_items(in_scope, updates.get("in_scope_add", []))
        out_scope = add_items(out_scope, updates.get("out_of_scope_add", []))
        return {"in_scope": in_scope, "out_of_scope": out_scope}

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
            for key in ("id", "text", "source", "source_id"):
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
                "text": text[:800],
            })
        return rows[-8:]

    def system_requirement_source_context(
        self,
        artifact: Dict[str, Any],
        issue: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        # For refine_requirement, always use full URL source list.
        return self.scope_requirement_context(artifact)

    @staticmethod
    def feedback_context(feedback: Any) -> Dict[str, List[Dict[str, Any]]]:
        if not isinstance(feedback, dict):
            return {}
        out: Dict[str, List[Dict[str, Any]]] = {}
        for section in ("findings", "constraints", "risks", "recommendations"):
            rows: List[Dict[str, Any]] = []
            for row in feedback.get(section) or []:
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
        for row in rows or []:
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
    def requirement_context(artifact: Dict[str, Any]) -> List[Dict[str, Any]]:
        rows = artifact.get("REQ") if isinstance(artifact.get("REQ"), list) else []
        return [
            AnalystAgent.requirement_record(row)
            for row in rows
            if isinstance(row, dict)
        ]

    @staticmethod
    def next_requirement_id(rows: List[Dict[str, Any]], req_type: str = "functional") -> str:
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
        sources = ",".join(str(item).strip() for item in row.get("source_ids", []) if str(item).strip())
        return requirement_dedupe_key(f"{description}|{sources}")

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
            "status",
            "category",
            "metric",
            "validation",
        ):
            value = str(source.get(key) or "").strip()
            if key in {"rationale", "category", "metric", "validation"} and value.lower() in placeholder_values:
                value = ""
            if value:
                out[key] = value
        req_type = str(source.get("type") or "").strip()
        if req_type == "constraint":
            req_type = "non_functional"
        if req_type not in {"functional", "non_functional"}:
            req_type = "functional"
        out["type"] = req_type
        priority = str(source.get("priority") or "").strip().lower()
        if priority not in {"must", "should", "could"}:
            priority = "should"
        out["priority"] = priority
        if "status" not in out:
            out["status"] = "proposed"
        for key in (
            "source_ids",
            "source_meeting",
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
        source_ref: str,
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
            if not item.get("description") or not item.get("source_ids"):
                continue
            if source_ref and source_ref not in item.get("source_meeting", []):
                item["source_meeting"].append(source_ref)
            item_id = str(item.get("id") or "").strip()
            if item_id and item_id in existing_ids:
                out.append(item)
                continue
            marker = self.requirement_key(item)
            if not marker or marker in seen:
                continue
            item["id"] = self.next_requirement_id(existing_rows + out, item.get("type", "functional"))
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

    def requirement_coverage_records(
        self,
        artifact: Dict[str, Any],
        raw_coverage: Any,
    ) -> List[Dict[str, Any]]:
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
                if status not in {"covered", "needs_clarification", "assumption", "risk", "excluded"}:
                    status = "needs_clarification"
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
            for source_id in req.get("source_ids") or []:
                sid = str(source_id or "").strip()
                if sid:
                    req_coverage.setdefault(sid, []).append(req_id)

        coverage: List[Dict[str, Any]] = []
        for source_id in url_ids:
            covered_by = list(dict.fromkeys(req_coverage.get(source_id, [])))
            existing = by_source.get(source_id, {})
            status = "covered" if covered_by else str(existing.get("status") or "needs_clarification")
            reason = str(existing.get("reason") or "").strip()
            if not covered_by and not reason:
                reason = "此 User Requirement 尚未被任何 REQ.source_ids 覆蓋。"
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
    def refine_requirement_coverage_gaps(
        coverage: List[Dict[str, Any]],
        current_URL: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        by_id = {
            str(row.get("id") or "").strip(): row
            for row in current_URL or []
            if isinstance(row, dict) and str(row.get("id") or "").strip()
        }
        default_reason = "此 User Requirement 尚未被任何 REQ.source_ids 覆蓋。"
        gaps: List[Dict[str, Any]] = []
        for row in coverage or []:
            if not isinstance(row, dict):
                continue
            source_id = str(row.get("source_id") or "").strip()
            if not source_id or row.get("covered_by"):
                continue
            status = str(row.get("status") or "").strip()
            reason = str(row.get("reason") or "").strip()
            if status in {"excluded", "needs_clarification", "assumption", "risk"} and reason and reason != default_reason:
                continue
            source = by_id.get(source_id, {})
            gaps.append(
                {
                    "source_id": source_id,
                    "text": str(source.get("text") or "").strip(),
                    "stakeholder": source.get("stakeholder"),
                    "reason": reason or default_reason,
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
        if not isinstance(output, dict):
            return
        requirements = output.get("URL")
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
        source_id = str(issue.get("id") or "").strip()
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
            output["URL"] = []
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
        meta["requirements_review_invalidated_by"] = source_id
        meta["requirements_changed"] = True
        meta["requirements_changed_by"] = source_id
        meta["requirements_changed_reason"] = "analyze_requirements"
        output["URL"] = merged[-len(added):]

    def execute_issue_conflict_analysis(
        self,
        *,
        artifact: Dict[str, Any],
        last_result: Optional[Dict[str, Any]] = None,
        force: bool = False,
    ) -> Dict[str, Any]:
        from storage.artifact import conflict_payload, reindex_conflict_report_rows

        previous_action_result = (
            last_result.get("action_result")
            if isinstance(last_result, dict) and isinstance(last_result.get("action_result"), dict)
            else {}
        )
        meta = artifact.get("meta") if isinstance(artifact.get("meta"), dict) else {}
        has_new_requirements = self.has_requirement_candidates(previous_action_result.get("output"))
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
            ("run_pairwise_conflict_detection", "run_pairwise_conflict_detection"),
            ("run_group_conflict_detection", "run_group_conflict_detection"),
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
        if isinstance(current, dict) and isinstance(current.get("conflict"), dict):
            current_report = current["conflict"].get("report")
            if previous_report:
                if isinstance(current_report, list) and current_report:
                    current["conflict"]["report"] = list(previous_report) + list(current_report)
                else:
                    current["conflict"]["report"] = previous_report
            artifact["conflict"] = current["conflict"]
        payload = conflict_payload(current if isinstance(current, dict) else artifact, include_report=True)
        report_rows = [
            row for row in (payload.get("report", []) or [])
            if isinstance(row, dict) and str(row.get("label") or "").strip() == "Conflict"
        ]
        report_rows = reindex_conflict_report_rows(report_rows)
        report_artifact = {
            **(current if isinstance(current, dict) else artifact),
            "conflict": {
                **payload,
                "report": report_rows,
            },
        }
        report_artifact = self.generate_conflict_resolutions(report_artifact)
        steps.append(
            {
                "action": "generate_conflict_resolutions",
                "summary": f"完成 generate_conflict_resolutions：{len(report_rows)} 筆 Conflict",
            }
        )
        report_rows = [
            row for row in ((report_artifact.get("conflict", {}) or {}).get("report", []) or [])
            if isinstance(row, dict) and str(row.get("label") or "").strip() == "Conflict"
        ]
        report_rows = reindex_conflict_report_rows(report_rows)
        artifact["conflict"] = {
            **(artifact.get("conflict") if isinstance(artifact.get("conflict"), dict) else {}),
            **(report_artifact.get("conflict", payload) or {}),
            "report": report_rows,
        }
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
        if not isinstance(output, dict):
            return False
        for key in ("URL",):
            value = output.get(key)
            if isinstance(value, list) and value:
                return True
        return False

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
            speaking_as = response.get("speaking_as") or response.get("target_stakeholders") or []
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
