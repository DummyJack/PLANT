import copy
import json

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
                        "URL": output.get("URL", []) if isinstance(output, dict) else [],
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
                        "summary": "讀取既有衝突報告，針對解決選項與建議解法討論取捨，不重新執行衝突辨識。",
                    }
                elif action == "respond_issue":
                    analyst_action_result = {
                        "action": action,
                        "summary": "只產生會議回答，不更新專案資料。",
                    }
                elif action == "answer_question":
                    analyst_action_result = {
                        "action": action,
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
        return analyst_action_result or {"action": action, "summary": f"完成 analyst action: {action}"}

    def execute_refine_requirement(
        self,
        *,
        artifact: Dict[str, Any],
        issue: Dict[str, Any],
        previous_responses: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        current_REQ = self.requirement_context(artifact)
        current_URL = self.scope_requirement_context(artifact)
        trace = issue.get("trace") if isinstance(issue.get("trace"), dict) else {}
        issue_source_ids = [
            str(item).strip()
            for item in (trace.get("artifact_ids") or [])
            if str(item).strip()
        ]
        if issue_source_ids:
            allowed_sources = set(issue_source_ids)
            current_URL = [
                row
                for row in current_URL
                if str(row.get("id") or row.get("source_id") or "").strip() in allowed_sources
            ]
            if not current_URL:
                current_URL = self.scope_requirement_context(artifact)
        scope = artifact.get("scope") if isinstance(artifact.get("scope"), dict) else {}
        feedback = self.feedback_context(artifact.get("feedback"))
        system_models = self.system_model_context(artifact)
        discussion = self.scope_discussion_context(previous_responses)
        source_id = str(issue.get("meeting_id") or issue.get("id") or "").strip()
        generated_all: List[Dict[str, Any]] = []
        final_coverage: List[Dict[str, Any]] = []
        reasons: List[str] = []
        warnings: List[str] = []
        max_passes = 3
        coverage_gaps: List[Dict[str, Any]] = []
        for pass_index in range(max_passes):
            current_REQ = self.requirement_context(artifact)
            req_source_index = self.requirement_source_index(current_REQ)
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
                "req_source_index": req_source_index,
                "current_req_count": len(current_REQ),
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
            title_issues = self.requirement_title_issues(
                data.get("REQ") if isinstance(data, dict) else []
            )
            if title_issues:
                repair_task = self.refine_requirement_title_repair_task(
                    title_issues=title_issues,
                    output=data,
                )
                data = self.invoke_requirements_analyst_object_json(
                    repair_task,
                    context,
                    mode="refine_requirement",
                )
                title_issues = self.requirement_title_issues(
                    data.get("REQ") if isinstance(data, dict) else []
                )
                if title_issues:
                    warnings.append(
                        "refine_requirement title 修復後仍不符合規則: "
                        + "; ".join(title_issues)
                    )

            nfr_issues = self.requirement_nfr_field_issues(
                data.get("REQ") if isinstance(data, dict) else []
            )
            if nfr_issues:
                data = self.ensure_nfr_fields(data)
                nfr_issues = self.requirement_nfr_field_issues(
                    data.get("REQ") if isinstance(data, dict) else []
                )
                if nfr_issues:
                    repair_task = self.refine_requirement_nfr_field_repair_task(
                        nfr_issues=nfr_issues,
                        output=data,
                    )
                    data = self.invoke_requirements_analyst_object_json(
                        repair_task,
                        context,
                        mode="refine_requirement",
                    )
                    nfr_issues = self.requirement_nfr_field_issues(
                        data.get("REQ") if isinstance(data, dict) else []
                    )
                    if nfr_issues:
                        warnings.append(
                            "refine_requirement non-functional 補欄位後仍不符合規則: "
                            + "; ".join(nfr_issues)
                        )
            mixed_issues = self.requirement_mixed_type_issues(
                data.get("REQ") if isinstance(data, dict) else []
            )
            if mixed_issues:
                repair_task = self.refine_requirement_mixed_type_repair_task(
                    mixed_issues=mixed_issues,
                    output=data,
                )
                data = self.invoke_requirements_analyst_object_json(
                    repair_task,
                    context,
                    mode="refine_requirement",
                )
                mixed_issues = self.requirement_mixed_type_issues(
                    data.get("REQ") if isinstance(data, dict) else []
                )
                if mixed_issues:
                    repair_task = self.refine_requirement_targeted_mixed_type_repair_task(
                        mixed_issues=mixed_issues,
                        output=data,
                    )
                    data = self.invoke_requirements_analyst_object_json(
                        repair_task,
                        context,
                        mode="refine_requirement",
                    )
                    mixed_issues = self.requirement_mixed_type_issues(
                        data.get("REQ") if isinstance(data, dict) else []
                    )
                    if mixed_issues:
                        warnings.append(
                            "refine_requirement mixed requirement targeted 修復後仍不符合規則: "
                            + "; ".join(mixed_issues)
                        )
                reasons.append("已修正 mixed requirement，拆分或改寫功能、非功能與限制需求。")

            candidate_reqs = data.get("REQ") if isinstance(data, dict) else []
            if warnings and not candidate_reqs:
                coverage_gaps = []
                break
            generated = self.clean_requirement_records(
                candidate_reqs,
                existing=artifact.get("REQ", []),
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
            "warnings": warnings,
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
  1. 併入既有 REQ 或新增 REQ，並讓該 URL-* 出現在 REQ.source。
  2. 若需求正式化討論已明確判斷該 URL-* 不需要、超出範圍或只能作為風險/假設，則在 coverage 標為 excluded、risk 或 assumption，並寫清楚 reason。
- 不要重寫已完整覆蓋的 REQ；只補缺口。
- 不要因缺少驗收條件、優先級、量化門檻或細節尚未完整，就把可辨識的需求標成 needs_clarification；先形成 REQ，將不確定內容放入 acceptance_criteria 空欄、assumptions、risks 或 open_questions。
"""
        task = f"""# 任務
依照 requirements-analyst skill，根據最新 current_URL、既有 current_REQ、scope、feedback、system_models 與本議題討論，精煉 requirements.json 中的 REQ-* 需求條目。
目標是把有依據的內容形成可寫入 SRS 的正式需求，而不是重新抽取 User Requirements。

# 模式
- mode={requirement_mode}
- create：根據 current_URL 與相關 artifact 建立初步 REQ-*。
- update：根據 current_URL、current_REQ 與相關 artifact 修正既有 REQ-*；若有明確未覆蓋內容，應新增 REQ。

# 輸入用途
- current_URL 是最新 User Requirements，也是形成正式 REQ 的主要需求來源；每筆 URL 都必須被 REQ.source 覆蓋，或在 coverage 中標示為 excluded、needs_clarification、risk 或 assumption。
- current_REQ 是既有正式需求條目；update 時作為修正基底，仍有效的 REQ 必須保留 id，只更新受 current_URL、會議決議或 artifact 影響的欄位。
- scope 只用來判斷需求是否屬於本系統範圍，不直接轉成 REQ。
- feedback 只作為領域背景、限制候選、風險與建議；可補充 rationale、risks、assumptions、constraint 判斷或 open question，不能單獨創造功能需求。
- system_models 只作為流程、actor、資料、狀態與邊界參考；可用來發現需求缺口、一致性問題、dependencies 或需要釐清的地方，不能單獨創造 stakeholder 未支持的新需求。
- discussion 只使用明確表態、已回答問題、已收斂或人類裁決的內容；可用來更新既有 REQ 欄位、補 acceptance criteria、risks、assumptions，或新增有 current_URL / meeting decision 支持的 REQ。
- previous_draft 只作為閱讀脈絡，不是權威來源；若與 current_URL 或 current_REQ 衝突，以 current_URL / current_REQ 為準。
- req_source_index 預先提供每個 URL-* / R*-M* / Feedback / SM-* 對應的既有 REQ-*；請直接引用這個索引判斷覆蓋狀態，不要額外呼叫 artifact_query 做逐筆比對。

# 規則
- source 是可追蹤來源 ID；優先使用 URL-*。若需求內容來自正式會議決議、feedback 或 system model，可加入 R*-M*、Feedback 或 SM-*。不要只寫 stakeholder 名稱、document、initial 或一般描述。
- update 模式修正既有項目時必須保留該項 REQ-* id；create 模式不要自行編 id。
- type 分類依 requirements-analyst skill；不要重新定義 functional / non-functional / constraint。
- title 是 brief description：用短詞概括需求核心，不寫完整句；完整需求放 description。
- title 不要寫 stakeholder 名稱，除非該角色就是需求概念不可分割的一部分；例如用「訂單申訴與補償時效揭露」，不要用「消費者訂單申訴與補償時效揭露」。
- priority 依 requirements-analyst skill 的 Priority Frameworks 判斷，但本專案只使用 must、should、could；沒有足夠依據就省略，不要輸出 wont，也不要預設成 should。
- description 是正式需求敘述，應以系統可履行的行為、限制或品質要求撰寫；不要寫成 stakeholder 願望或討論摘要。
- description 必須是單一正式需求敘述；若輸入包含多個獨立系統能力、品質要求或限制，應拆成多筆 REQ，或整理成同一能力群下的清楚條件，不要串成一大段。
- acceptance_criteria 必須可驗收，不要只重述 description；若只有待確認條件，放入 risks、assumptions 或 open_questions。
- 明確外部限制、法規、政策、資料保存/刪除、第三方或技術限制用 constraint；品質、安全、隱私、稽核、可靠性或可用性要求用 non-functional；不確定時放入 risks、assumptions 或 open_questions。
- non-functional 可輸出 category、metric、validation：category 依 ISO/IEC 25010 且不用 functional suitability；metric 從 acceptance_criteria 或需求內容萃取可觀察條件，不假造數字；validation 依 skill 的 Requirement Validation 寫成可執行方式。
- 每筆 REQ 只能表達一種主要性質：functional、non-functional 或 constraint。若來源同時包含系統能力、品質要求與限制，且各自可獨立驗收或追蹤，請拆成多筆 REQ；否則保留為同一筆 REQ 的 acceptance_criteria、risks 或 assumptions。
- 相近 URL 可合併成一筆 REQ，但不得無聲略過清楚且尚未覆蓋的 URL。
- 只要 URL 能辨識 stakeholder、need/constraint 與目的或痛點，就應正式化為 REQ 或併入既有 REQ；不需要等待會議逐字確認。
- 不要只正式化討論中被重複提到的角色或消費者需求；餐廳店員、外送員、平台營運主管等來源也必須同等處理。
- 不確定、有爭議、超出範圍或需要裁決的內容，不要硬寫成 REQ；請放入 assumptions、risks、open_questions 或 coverage。
- needs_clarification 只用於無法辨識系統行為、品質要求或限制本體的 URL；缺少驗收細節不是 needs_clarification 的充分理由。
- 每個 current_URL 都必須有去處：被 REQ.source 覆蓋，或在 coverage 中說明為何不能形成 REQ。
- coverage.covered_by 只能引用本次輸出或既有 current_REQ 中的 REQ-*。
- rationale 只寫為什麼需要此需求；risks 只寫可能失敗或不確定處；assumptions 只寫目前採用但尚未完全確認的前提。三者不得重複 description。
- coverage 只作內部檢查，不是正式需求內容；不要把 coverage reason 寫進 description、rationale、risks 或 assumptions。
{gap_rule}

# 依據與輸出性質
- 有依據就填欄位；沒有依據就留空陣列或省略，不要臆測。
- 只回傳本次新增或需要更新的 REQ；已完整且未變更的既有 REQ 不要重複回傳。
- reason 只用一句話說明本次整理結果。

# 輸出 JSON
{{
  "REQ": [
    {{
      "type": "functional | non-functional | constraint",
      "id": "update 模式才填既有 REQ-*；create 模式省略或留空",
      "title": "短標題",
      "description": "系統應...",
      "priority": "must",
      "category": "non-functional 才填 ISO/IEC 25010 品質特性",
      "metric": "non-functional 才填從 acceptance_criteria 或需求內容萃取出的可觀察或可測量條件",
      "validation": "non-functional 才填依 Requirement Validation 判斷的可執行驗證方式",
      "source": ["URL-1", "{source_id}"],
      "acceptance_criteria": [],
      "rationale": "為何由這些 User Requirements 形成此需求條目",
      "dependencies": [],
      "risks": [],
      "assumptions": []
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
    def requirement_source_index(rows: List[Dict[str, Any]]) -> Dict[str, List[str]]:
        """建立 source_id -> REQ-* 的一次性索引，供 refine_requirement 直接做來源覆蓋判斷。"""
        index: Dict[str, List[str]] = {}
        if not isinstance(rows, list):
            return index
        for row in rows:
            if not isinstance(row, dict):
                continue
            req_id = str(row.get("id") or "").strip()
            if not req_id:
                continue
            for source_id in AnalystAgent.requirement_sources(row):
                source = str(source_id).strip()
                if not source:
                    continue
                bucket = index.setdefault(source, [])
                if req_id not in bucket:
                    bucket.append(req_id)
        return index

    @staticmethod
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
    def requirement_key(row: Dict[str, Any]) -> str:
        description = str(row.get("description") or "").strip()
        sources = ",".join(AnalystAgent.requirement_sources(row))
        return requirement_dedupe_key(f"{description}|{sources}")

    @staticmethod
    def requirement_title_issues(rows: Any) -> List[str]:
        if not isinstance(rows, list):
            return []
        stakeholder_prefixes = (
            "平台營運主管",
            "平台營運者",
            "平台營運",
            "餐廳店員",
            "店家管理者",
            "餐廳管理者",
            "外送員",
            "消費者",
            "客服人員",
            "客服",
            "財務人員",
            "財務",
            "使用者",
        )
        issues: List[str] = []
        for idx, row in enumerate(rows, 1):
            if not isinstance(row, dict):
                continue
            req_id = str(row.get("id") or f"row-{idx}").strip()
            title = str(row.get("title") or "").strip()
            if not title:
                continue
            if any(title.startswith(prefix) for prefix in stakeholder_prefixes):
                issues.append(f"{req_id}: title 含 stakeholder 前綴「{title}」")
                continue
            if any(term in title for term in ("系統應", "需要", "必須")):
                issues.append(f"{req_id}: title 像完整需求句「{title}」")
                continue
            if any(mark in title for mark in ("。", "，", "；")):
                issues.append(f"{req_id}: title 含句子標點「{title}」")
        return issues

    @staticmethod
    def refine_requirement_title_repair_task(
        *,
        title_issues: List[str],
        output: Any,
    ) -> str:
        return f"""# 任務
修復 refine_requirement 輸出的 REQ title，使其符合 title 規則。

# title 問題
{json.dumps(title_issues, ensure_ascii=False, indent=2)}

# 原始輸出
{json.dumps(output, ensure_ascii=False, indent=2)}

# 修復規則
- 只修正 REQ[*].title。
- title 是 brief description，只寫需求核心短語，不寫完整句。
- title 不要寫 stakeholder 名稱，除非該角色就是需求概念不可分割的一部分。
- 不得改變 description、type、priority、source、acceptance_criteria、rationale、dependencies、risks、assumptions、coverage 或 reason 的語意。
- 保留原本 JSON 結構與所有欄位。
- 只輸出修復後 JSON。

# 輸出 JSON
{{
  "REQ": [],
  "coverage": [],
  "reason": "一句說明"
}}"""

    @staticmethod
    def refine_requirement_mixed_type_repair_task(
        *,
        mixed_issues: List[str],
        output: Any,
    ) -> str:
        return f"""# 任務
修復 refine_requirement 輸出的 mixed requirement。

# mixed requirement 問題
{json.dumps(mixed_issues, ensure_ascii=False, indent=2)}

# 原始輸出
{json.dumps(output, ensure_ascii=False, indent=2)}

# 修復規則
- 每筆 REQ 只能表達一種主要性質：functional、non-functional 或 constraint。
- 若同一筆 REQ 同時包含系統能力與品質要求，且兩者可獨立驗收或追蹤，請拆成 functional 與 non-functional。
- 若同一筆 REQ 同時包含系統能力與外部限制、法規、政策、資料保存/刪除、第三方或技術限制，請拆成 functional 與 constraint。
- 若品質要求只是該功能的驗收條件，且不能獨立追蹤，可保留在 acceptance_criteria，不必拆。
- 不要自動改成預設 type；請依 requirements-analyst skill 與本專案規則修正。
- 保留原本 source；拆分後的新 REQ 也要保留可追蹤 source。
- update 模式中若修正既有 REQ，保留原 REQ id；拆出新需求時新項目不要填 id。
- 只輸出修復後 JSON。
- 每筆 REQ 只保留一個核心意圖；若能力、品質、限制意圖仍在同一筆中，請拆成多筆。

# 輸出 JSON
{{
  "REQ": [],
  "coverage": [],
  "reason": "一句說明"
}}"""

    @staticmethod
    def refine_requirement_targeted_mixed_type_repair_task(
        *,
        mixed_issues: List[str],
        output: Any,
    ) -> str:
        return f"""# 任務
上一輪 mixed requirement 修復仍失敗。請只針對被點名的 REQ 做定點修復，輸出可直接寫回 requirements.json 的結果。

# 仍不合格的項目
{json.dumps(mixed_issues, ensure_ascii=False, indent=2)}

# 目前輸出
{json.dumps(output, ensure_ascii=False, indent=2)}

# 定點修復規則
- 只修改「仍不合格的項目」中點名的 REQ；其他 REQ 必須原樣保留。
- 被點名為 functional 但混入品質、穩定性或效能語意時，必須拆成：
  1. functional：只保留系統能力本體。
  2. non-functional：只保留品質、穩定性、可用性、可靠性、效能、SLA、錯誤率或高峰負載等要求。
- 被點名為 functional 但混入限制、法規或政策語意時，必須拆成：
  1. functional：只保留系統能力本體。
  2. constraint：只保留系統不能違反或必須遵守的限制。
- 被點名為 non-functional 但內容主要是系統能力時，請改成 functional；若同時有可獨立追蹤的品質要求，再另外拆出 non-functional。
- 拆出的新 REQ 不要填 id；由程式配置新 REQ-*。
- 修正既有 REQ 時保留原 id。
- 每筆新/修正後的 REQ 都必須保留原本可追蹤 source。
- description 必須只描述一種主要性質，不要用「並維持穩定」「且高效」「並符合法規」把不同性質重新串在一起。
- 若某個品質要求只是功能的 acceptance criteria，且不能獨立追蹤，才可留在 acceptance_criteria；否則必須拆出 non-functional。
- 若該筆仍同時出現兩種以上核心意圖（如能力+品質、能力+限制），請先拆分再輸出，不可以合併字句（「同時」「並且」「且」）硬塞在一筆中。
- 只輸出完整修復後 JSON；不要解釋。

# 輸出 JSON
{{
  "REQ": [],
  "coverage": [],
  "reason": "一句說明"
}}"""

    @staticmethod
    def refine_requirement_nfr_field_repair_task(
        *,
        nfr_issues: List[str],
        output: Any,
    ) -> str:
        return f"""# 任務
修復 refine_requirement 輸出的 non-functional 缺欄位問題。

# 非完整欄位問題
{json.dumps(nfr_issues, ensure_ascii=False, indent=2)}

# 原始輸出
{json.dumps(output, ensure_ascii=False, indent=2)}

# 修復規則
- 只補齊被點名 REQ 的 non-functional 欄位：category、metric、validation。
- 僅能使用輸入內容可支持的描述，禁止虛構數值與門檻。
- category 依 ISO/IEC 25010 取值（如 Performance / Reliability / Security / Usability / Maintainability），不使用 functional suitability。
- metric 以 acceptance_criteria 或 description / rationale 中可觀測條件為準；若只有描述字眼，保留可觀測語句，不用空字串。
- validation 用可執行驗證方式（測試、稽核、流程驗證），可直接回應「以 acceptance criteria 驗證」。
- 不能確定時，保留既有欄位，不得新增不實內容。
- 只輸出修復後 JSON，不要說明。

# 輸出 JSON
{{
  "REQ": [],
  "coverage": [],
  "reason": "一句說明"
}}"""

    @staticmethod
    def requirement_mixed_type_issues(rows: Any) -> List[str]:
        quality_terms = (
            "穩定性", "可用性", "可靠性", "效能", "性能", "回應時間",
            "故障率", "服務中斷", "SLA", "吞吐", "高峰", "負載",
            "正確率", "錯誤率",
        )
        constraint_terms = (
            "法規", "主管機關", "保存年限", "資料保存", "刪除限制",
            "第三方", "合規", "隱私", "個資", "稽核", "不能違反",
        )
        capability_terms = (
            "提供", "允許", "支援", "顯示", "查詢", "通知", "建立", "更新",
            "修改", "刪除", "回報", "申訴", "管理", "設定", "記錄", "匯出",
            "偵測", "標示", "提示", "處理",
        )
        multi_intent_markers = ("且", "並且", "以及", "同時", "；", ";")
        issues: List[str] = []
        for idx, row in enumerate(rows or [], 1):
            if not isinstance(row, dict):
                continue
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
            if req_type == "constraint" and has_capability and not has_constraint:
                issues.append(
                    f"{req_id} 是 constraint，但未明確聚焦於外部/技術限制，包含可執行功能描述"
                )
        return issues

    @staticmethod
    def requirement_nfr_field_issues(rows: Any) -> List[str]:
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
    def infer_nfr_category(text: str) -> str:
        lower_text = text.lower()
        if any(k in lower_text for k in ("效能", "性能", "回應時間", "延遲", "吞吐", "負載", "處理時間", "峰值", "高峰")):
            return "Performance"
        if any(k in lower_text for k in ("可用性", "可存取", "持續運作", "故障", "錯誤率", "服務中斷", "穩定")):
            return "Reliability"
        if any(k in lower_text for k in ("安全", "資安", "隱私", "權限", "授權", "稽核", "法規", "資料保護", "加密")):
            return "Security"
        if any(k in lower_text for k in ("可維護", "可擴", "可測", "可配置", "可修改", "可復原")):
            return "Maintainability"
        if any(k in lower_text for k in ("可用", "體驗", "好懂", "可理解", "簡單", "易用")):
            return "Usability"
        return "Reliability"

    @staticmethod
    def infer_nfr_metric(row: Dict[str, Any], fallback: str) -> str:
        for key in ("acceptance_criteria", "description", "rationale"):
            value = row.get(key)
            if isinstance(value, list):
                rows = [str(item).strip() for item in value if str(item).strip()]
                if rows:
                    return rows[0]
            elif str(value or "").strip():
                text = str(value).strip()
                return text.split("。", 1)[0].strip()
        return fallback

    @staticmethod
    def infer_nfr_validation(row: Dict[str, Any], category: str) -> str:
        candidate = str(row.get("validation") or "").strip()
        if candidate:
            return candidate
        if category == "Performance":
            return "執行效能驗證（含高峰或負載情境）"
        if category == "Reliability":
            return "可用性與穩定性驗證（含故障與重試情境）"
        if category == "Security":
            return "安全與合規驗證（含權限、稽核、資料保護流程檢核）"
        if category == "Maintainability":
            return "流程回溯與修改性驗證（含變更追蹤與回滾確認）"
        return "需求驗證測試（以 acceptance criteria 為核準）"

    def ensure_nfr_fields(self, output: Dict[str, Any]) -> Dict[str, Any]:
        reqs = output.get("REQ")
        if not isinstance(reqs, list):
            return output

        updated = []
        for req in reqs:
            if not isinstance(req, dict):
                continue
            req_type = str(req.get("type") or "").strip().lower().replace("_", "-")
            if req_type == "non-functional":
                fields_text = " ".join(
                    str(req.get(k) or "") for k in ("title", "description", "rationale")
                ).strip()
                category = str(req.get("category") or "").strip()
                metric = str(req.get("metric") or "").strip()
                validation = str(req.get("validation") or "").strip()
                if not category:
                    category = self.infer_nfr_category(fields_text)
                if not metric:
                    metric = self.infer_nfr_metric(req, fields_text)
                if not validation:
                    validation = self.infer_nfr_validation(req, category)
                req = dict(req)
                req["category"] = category
                req["metric"] = metric
                req["validation"] = validation
            updated.append(req)
        updated_output = dict(output)
        updated_output["REQ"] = updated
        return updated_output

    @staticmethod
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
        if priority in {"must", "should", "could"}:
            out["priority"] = priority
        sources = AnalystAgent.requirement_sources(source)
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
            for source_id in self.requirement_sources(req):
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
        gaps: List[Dict[str, Any]] = []
        for row in coverage or []:
            if not isinstance(row, dict):
                continue
            source_id = str(row.get("source_id") or "").strip()
            if not source_id or row.get("covered_by"):
                continue
            status = str(row.get("status") or "").strip()
            reason = str(row.get("reason") or "").strip()
            if status in {"excluded", "assumption", "risk"} and reason:
                continue
            source = by_id.get(source_id, {})
            gaps.append(
                {
                    "source_id": source_id,
                    "text": str(source.get("text") or "").strip(),
                    "stakeholder": source.get("stakeholder"),
                    "reason": reason,
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

        previous_action_result = last_result if isinstance(last_result, dict) else {}
        if isinstance(previous_action_result.get("action_result"), dict):
            previous_action_result = previous_action_result.get("action_result") or {}
        meta = artifact.get("meta") if isinstance(artifact.get("meta"), dict) else {}
        candidate_output = (
            previous_action_result.get("output")
            if isinstance(previous_action_result.get("output"), dict)
            else {"URL": previous_action_result.get("URL", [])}
        )
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
