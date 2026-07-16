# Plans the next action for the agent.
import json
from typing import Any, Dict

from agents.json_schema import EXPERT_RESEARCH_PLAN_SCHEMA, validate_json_schema
from .repair import repair_plan_output


research_actions = [
    "read_reference_docs",
    "research_issue",
    "update_feedback",
    "done",
]

max_research_issues = 4
max_research_query_chars = 360
research_target_types = {"URL", "REQ", "scope", "open_question", "issue"}


def state_row_ids(state, field: str, *id_fields: str) -> list[str]:
    keys = id_fields or ("id",)
    return [
        value
        for row in (state.get(field) or [])
        if isinstance(row, dict)
        for value in [next(
            (str(row.get(key) or "").strip() for key in keys if str(row.get(key) or "").strip()),
            "",
        )]
        if value
    ]


def state_url_ids(state) -> list[str]:
    return state_row_ids(state, "URL")


def state_req_ids(state) -> list[str]:
    return state_row_ids(state, "REQ")


def state_open_question_ids(state) -> list[str]:
    return state_row_ids(state, "open_questions", "id", "question_id")


def state_issue_ids(state) -> list[str]:
    issue = state.get("issue") or {}
    if not isinstance(issue, dict):
        return []
    return sorted(
        {
            str(issue.get(key) or "").strip()
            for key in ("id", "issue_id", "meeting_id")
            if str(issue.get(key) or "").strip()
        }
    )


def state_scope_ids(state) -> list[str]:
    scope = state.get("scope") or {}
    if not isinstance(scope, dict):
        return []
    ids: set[str] = set()
    for section in ("in_scope", "out_of_scope"):
        values = scope.get(section) or []
        if values:
            ids.add(section)
        for row in values:
            if isinstance(row, dict):
                value = str(row.get("id") or row.get("scope_id") or "").strip()
                if value:
                    ids.add(value)
    return sorted(ids)


def research_target_ids(state) -> dict[str, list[str]]:
    return {
        "URL": state_url_ids(state),
        "REQ": state_req_ids(state),
        "scope": state_scope_ids(state),
        "open_question": state_open_question_ids(state),
        "issue": state_issue_ids(state),
    }


def research_repair_context(state) -> dict:
    return {
        "valid_target_ids": research_target_ids(state),
        "referenced_files": state.get("referenced_files") or [],
    }


def normalize_research_target_params(params: dict, state: dict) -> dict:
    params = params if isinstance(params, dict) else {}
    target_type = str(params.get("target_type") or "").strip()
    target_ids = list(dict.fromkeys(
        str(value).strip()
        for value in (params.get("target_ids") or [])
        if str(value).strip()
    ))
    if target_type not in research_target_types:
        raise ValueError(f"research target_type 不合法: {target_type or '<empty>'}")
    if not target_ids:
        raise ValueError("research target_ids 不可為空")
    valid_ids = set(research_target_ids(state)[target_type])
    if not valid_ids:
        raise ValueError(
            f"research target_type={target_type} currently has no addressable ids"
        )
    invalid_ids = [target_id for target_id in target_ids if target_id not in valid_ids]
    if invalid_ids:
        raise ValueError(
            "research target_ids 不在目前 artifact context: "
            + ", ".join(invalid_ids)
        )
    return {
        "target_type": target_type,
        "target_ids": target_ids,
    }

def research_plan_mode(state) -> str:
    if not isinstance(state, dict):
        return "done"
    checkpoint = state.get("resume_checkpoint") if isinstance(state.get("resume_checkpoint"), dict) else {}
    checkpoint_action = str(checkpoint.get("action") or "").strip()
    checkpoint_step = str(checkpoint.get("step_id") or "").strip()
    research_results_count = int(state.get("research_results_count") or 0)
    if (
        research_results_count > 0
        and (checkpoint_action == "update_feedback" or checkpoint_step.endswith("update_feedback"))
    ):
        return "feedback_only"
    if state.get("user_guidance"):
        return "research"
    if state.get("research_source_invalidated"):
        return "feedback_only"
    if state.get("referenced_files") and state.get("has_read_file"):
        return "research"
    if state.get("has_existing_research"):
        return "done"
    if research_results_count > 0 or int(state.get("document_evidence_count") or 0) > 0:
        return "feedback_only"
    if state.get("baseline_research_needed"):
        return "research"
    coverage_flags = (
        "not_found_in_documents",
        "document_conflict",
        "needs_external_validation",
        "gaps",
    )
    if any(bool(state.get(flag)) for flag in coverage_flags):
        return "research"
    for row in state.get("document_coverage") or []:
        if not isinstance(row, dict):
            continue
        if str(row.get("status") or "").strip() in coverage_flags:
            return "research"
    return "done"


def external_research_required(state) -> bool:
    return research_plan_mode(state) == "research"


def compact_research_query(value: str, *, max_chars: int = max_research_query_chars) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= max_chars:
        return text
    separators = "，。；、,;|｜"
    for sep in separators:
        text = text.replace(sep, "\n")
    parts = [part.strip(" -:：") for part in text.splitlines() if part.strip(" -:：")]
    kept = []
    for part in parts:
        candidate = " ".join([*kept, part]).strip()
        if len(candidate) > max_chars:
            continue
        kept.append(part)
    if kept:
        return " ".join(kept)[:max_chars].strip()
    return text[:max_chars].strip()


def research_prompt(*, state_text: str, obs_text: str) -> str:
    return f"""# 任務
根據目前專案狀態與上一步結果，決定本輪 domain research 要做什麼。

# Action Boundary
- action=expert.plan_research_domain
- 本 action 規劃 domain research 的 steps。
- action 固定使用 done 作為計畫 wrapper；沒有新研究工作時 steps 可為空。
- 只有目前狀態需要新研究時才安排 research_issue；若有本輪 referenced_files，先 read_reference_docs，再 research_issue，最後 update_feedback。
- read_reference_docs 與 research_issue 取得證據；update_feedback 寫回正式 feedback artifact。
- has_existing_research=true 且沒有新文件、新人類建議或失敗 checkpoint 時直接 done，不重複研究。
- 若有 referenced_files 並執行 read_reference_docs，最後必須 update_feedback，把文件證據整理成 feedback。
- 不得把 feedback 直接定案成需求；需求正式化由 Analyst action 處理。
- user_guidance 若存在，是人類審查建議與查證方向，不是已確認需求或強制結論；必須納入研究規劃，但只有取得文件、外部來源或既有 artifact 支持時才能寫入 feedback。
- user_guidance 是全局研究提醒，不代表每個 URL / REQ / stakeholder 都受影響；不得把同一建議套用到所有需求或整份 feedback。
- 若 user_guidance 指向特定主題，只規劃與該主題有明確關聯且高價值的查證；沒有 artifact 或證據關聯的部分只能視為待釐清方向。

# 目前專案狀態
{state_text}

# 上一步結果
{obs_text}

- read_reference_docs：讀專案內部文件，取得文件證據。
- research_issue：針對文件缺口、文件衝突、外部驗證需求或需要查證的公開來源取得證據。
- update_feedback：把已取得的研究結果寫回 feedback。
- done：僅作為計畫 wrapper；steps 仍必須包含 research_issue 與 update_feedback。

- 研究問題必須來自目前 issue、scenario、scope、stakeholders、open_questions、URL 或 REQ。
- research_issue.query 必須指出要查證的 artifact 切面，例如特定 URL/REQ、scope 條目、open question 或 issue；不得只寫泛用主題詞。
- 每個 research_issue.params 必須包含 target_type 與 target_ids；target_type 只能是 URL、REQ、scope、open_question、issue。
- 若查證對象是使用者需求，優先使用 target_type="URL" 並填入具體 URL-*；不得用空泛 issue 取代可定位的 URL/REQ。
- 不要把 scenario 從研究問題中拿掉；若 query 聚焦某個子議題，仍須讓 runtime 能看出它是目前專案情境下的子議題。
- 若 user_guidance 指出特定方向，優先判斷它是否對需求成立、系統邊界、驗收標準或外部證據缺口有影響；有影響才規劃 read_reference_docs 或 research_issue 查證。
- 不要因為 user_guidance 提到某方向，就把所有研究問題都改成該方向；只在目前 artifact 明確相關的研究問題中反映。
- 只規劃 high-value research_issue，不為了湊數研究。
- high-value 指會影響需求是否成立、系統邊界、驗收標準、多個 URL/REQ，或目前 artifact 沒有清楚答案。
- 不研究低價值內容：一般功能偏好、已清楚的 UI 操作、不影響需求條文的背景知識、與 scope 無關的產業介紹。
- 若既有 artifact / feedback 已足夠涵蓋目前高價值問題，選 done，不重複研究；但 reasoning 必須說明檢查了哪些面向且為何沒有漏掉需要新增研究的部分。
- 若 resume_checkpoint 存在且 stage_id=research_domain，表示本輪是失敗後繼續；已存在的 document_evidence、document_coverage 或 feedback 不要重做，只針對 checkpoint.step_id / action 之後尚未完成的缺口繼續；未寫入 feedback 的研究中間結果不跨執行保留。
- referenced_files 或使用者上傳文件存在時，採「文件優先、外部補證」：必須先規劃 read_reference_docs，不能直接用 research_issue 取代文件查證。
- read_reference_docs 必須對相關 URL / REQ / open_questions 做 coverage 分類：document_supported、not_found_in_documents、document_conflict、needs_external_validation。
- 文件 coverage 顯示 not_found_in_documents、document_conflict、needs_external_validation，或新 user_guidance / referenced_files 明確標記需要外部查證時，research_issue 必須聚焦那些缺口。
- 若 baseline_research_needed=true，代表本輪研究階段尚未建立任何 feedback，但已有 scenario / URL / REQ / open_questions 與 web_search 可用；此時規劃 1 個中性的 research_issue，優先確認目前 scenario 與 target requirement 是否涉及適用的法規、主管機關指引、產業標準、平台政策或可信公開證據。
- baseline research 應以「情境專屬適用」優先：先找能說明為何適用目前 scenario + target 的來源；若只有通用規範，也必須說明它如何套用到目前 target，否則不要寫入 feedback。
- 如果 has_existing_research=false 且 research_results_count=0，只有在 baseline_research_needed、user_guidance、referenced_files、coverage、gaps 或 issue 明確標記需要外部查證時，才至少取得 1 個外部證據；但若 referenced_files 存在，必須先 read_reference_docs，再針對文件缺口或仍需外部查證的議題規劃 research_issue。
- 沒有外部研究觸發條件且已有有效 feedback 時直接 done。
- 只有存在 high-value research_issue 時，才規劃 research_issue；若已讀取引用文件或取得研究結果，最後執行 update_feedback。
- 需要專案文件證據時先用 read_reference_docs。
- 若目前專案狀態包含 referenced_files，必須先規劃 read_reference_docs，且 query 應聚焦使用者建議與這些文件。
- 若 referenced_files 為空，不要因為文件庫有檔案就自動規劃 read_reference_docs；只有研究問題明確需要專案文件證據時才使用。
- 需要外部證據時用 research_issue；每個 research_issue 只處理一個明確高價值問題，且 query / value_reason 必須說明它是文件缺口、文件衝突、外部證據缺口或時效性驗證。
- value_reason 必須連回目前 artifact context，說明此查證會影響哪個需求品質面向；不能只說「查標準」或「查最佳實務」。
- 若多個高價值問題分屬不同面向，可以拆成多個 research_issue；最多 {max_research_issues} 個。
- 不同外部查證主題必須拆成不同 research_issue；例如個資法、消費者保護、廣告/促銷規範與服務品質標準不可合併成同一個 query。
- 每個 research_issue 只查證一個法規、主管機關要求、產業標準或其他單一證據主題；若同一 target 涉及多個主題，使用多個 steps。
- 每個 research_issue 必須能由一類來源回答並形成一個獨立結論；若 query 同時要求多個獨立查證結果，即使 target 相同也必須拆成多個 steps。
- 不要把多個互不相干的外部查證問題塞進同一個過大的 query。
- 每個 research_issue.params 必須包含 query 與 value_reason。
- 每個 research_issue 只能處理 target_ids 指定的目標；若有多個互不相干 target，拆成多個 research_issue。
- 只要有 read_reference_docs、research_issue 或已有 research_results，最後必須 update_feedback。
- update_feedback 只允許放在 steps 最後一次。
- feedback.sources 集中列出來源；web 來源使用 {{"title": "web_search 或官方頁面提供的人可讀頁面/文件標題，不可填 URL", "url": "完整 URL"}}，專案引用文件使用 {{"title": "檔名", "url": "專案文件路徑", "type": "file"}}。
- 若 user_guidance 沒有足夠證據支持，feedback 不得把它寫成確定限制；只能記錄為風險、不確定性或後續待釐清方向。
- feedback 只寫入被 document_evidence / research_results 支持且能對應到相關 artifact 的內容；不要把 user_guidance 原文逐項轉成 findings、constraints、risks 或 recommendations。

# Output JSON
{{
  "research_plan": {{
    "action": "done",
    "params": {{}},
    "reasoning": "使用目前輸出語系的一句說明",
    "goal": "本輪 domain research 目標",
    "steps": [
        {{"action": "read_reference_docs", "params": {{"query": "具體文件查詢問題"}}}},
        {{
          "action": "research_issue",
          "params": {{
            "target_type": "URL",
            "target_ids": ["URL-1"],
            "query": "具體高價值研究問題",
            "value_reason": "為什麼此問題會影響需求品質"
          }}
        }},
        {{"action": "update_feedback", "params": {{}}}}
    ]
  }}
}}"""


class ExpertResearchPlan:
    def research_plan_json(self, messages: list[dict[str, Any]]) -> Dict[str, Any]:
        return self.chat_json(messages, schema=EXPERT_RESEARCH_PLAN_SCHEMA)

    @staticmethod
    def validate_research_plan_payload(response: Dict[str, Any]) -> None:
        validate_json_schema(response, EXPERT_RESEARCH_PLAN_SCHEMA)

    def plan_research(self, state, last_observation=None):
        if state.get("actions_taken"):
            return {
                "action": "done",
                "params": {},
                "reasoning": "已依 research_domain 規劃完成本輪研究，不重新規劃。",
            }
        state_text = json.dumps(state, ensure_ascii=False, separators=(",", ":"))
        obs_text = json.dumps(
            last_observation or {}, ensure_ascii=False, separators=(",", ":")
        )

        user_prompt = research_prompt(state_text=state_text, obs_text=obs_text)

        messages = self.build_direct_messages(user_prompt)
        try:
            if "artifact_query" in self.tools:
                raw = self.chat_with_tools(
                    messages,
                    active_skill="domain-research",
                )
                try:
                    response = self.parse_issue_response_json(raw)
                    self.validate_research_plan_payload(response)
                except Exception as parse_error:
                    repair_task = repair_plan_output(
                        raw=raw,
                        error=f"上一輪輸出不是合法 JSON object: {parse_error}",
                        context=research_repair_context(state),
                    )
                    response = self.research_plan_json(self.build_direct_messages(repair_task))
            else:
                response = self.research_plan_json(messages)
        except Exception as e:
            raise RuntimeError(f"Expert domain research 決策輸出格式不合格: {e}") from e
        if not isinstance(response, dict):
            raise ValueError(f"Expert domain research 決策必須是 JSON object，收到 {type(response).__name__}")

        return self.normalize_research_plan(response, state=state)

    @staticmethod
    def research_work_mode(state) -> str:
        return research_plan_mode(state)

    def normalize_research_plan(self, response, *, state=None, repaired: bool = False):
        state = state if isinstance(state, dict) else {}

        def normalize_once(payload):
            if not isinstance(payload, dict) or not isinstance(payload.get("research_plan"), dict):
                raise ValueError("Expert domain research plan output must contain research_plan object")
            plan = payload["research_plan"]
            goal = str(plan.get("goal") or "").strip()
            reasoning = str(plan.get("reasoning") or "").strip()
            if not goal:
                raise ValueError("Expert domain research plan 必須包含 goal")
            if not reasoning:
                raise ValueError("Expert domain research plan 必須包含 reasoning")

            mode = research_plan_mode(state)
            if mode == "done":
                return {
                    "action": "done",
                    "params": {},
                    "reasoning": reasoning,
                }
            if mode == "feedback_only":
                return {
                    "action": "done",
                    "params": {},
                    "reasoning": reasoning,
                    "action_plan": {
                        "goal": goal,
                        "steps": [{"action": "update_feedback", "params": {}}],
                    },
                }

            source_steps = plan.get("steps")
            if not isinstance(source_steps, list) or not source_steps:
                nested_plan = plan.get("action_plan")
                if isinstance(nested_plan, dict):
                    source_steps = nested_plan.get("steps")
            if not isinstance(source_steps, list) or not source_steps:
                nested_plan = payload.get("action_plan")
                if isinstance(nested_plan, dict):
                    source_steps = nested_plan.get("steps")
            if not isinstance(source_steps, list) or not source_steps:
                direct_action = str(plan.get("action") or "").strip()
                direct_params = plan.get("params")
                if direct_action in {
                    "read_reference_docs",
                    "research_issue",
                    "update_feedback",
                }:
                    source_steps = [{
                        "action": direct_action,
                        "params": direct_params if isinstance(direct_params, dict) else {},
                    }]
            if not isinstance(source_steps, list) or not source_steps:
                raise ValueError("Expert domain research plan 必須包含 steps")

            clean_steps = []
            research_count = 0
            reference_read_count = 0
            for index, step in enumerate(source_steps, start=1):
                if not isinstance(step, dict):
                    raise ValueError(f"Expert domain research steps[{index}] 必須是 object")
                action = str(step.get("action") or "").strip()
                params = step.get("params") if isinstance(step.get("params"), dict) else {}
                if action == "update_feedback":
                    continue
                if action == "read_reference_docs":
                    if not state.get("referenced_files") or not state.get("has_read_file"):
                        continue
                    if research_count:
                        raise ValueError(
                            "read_reference_docs must appear before research_issue"
                        )
                    reference_read_count += 1
                    query = compact_research_query(str(params.get("query") or "").strip())
                    if not query:
                        raise ValueError(f"Expert domain research steps[{index}] read_reference_docs 缺少 query")
                    clean_steps.append({"action": action, "params": {"query": query}})
                    continue
                if action != "research_issue":
                    raise ValueError(f"Expert domain research steps[{index}] action 不合法: {action or '<empty>'}")

                research_count += 1
                if research_count > max_research_issues:
                    raise ValueError(f"Expert domain research research_issue 超過上限 {max_research_issues}")
                query = compact_research_query(str(params.get("query") or "").strip())
                value_reason = str(params.get("value_reason") or "").strip()
                target_type = str(params.get("target_type") or "").strip()
                raw_target_ids = params.get("target_ids")
                if not query:
                    raise ValueError(f"Expert domain research steps[{index}] research_issue 缺少 query")
                if not value_reason:
                    raise ValueError(f"Expert domain research steps[{index}] research_issue 缺少 value_reason")
                if target_type not in research_target_types:
                    raise ValueError(f"Expert domain research steps[{index}] target_type 不合法")
                if not isinstance(raw_target_ids, list):
                    raise ValueError(f"Expert domain research steps[{index}] target_ids 必須是 array")
                target_ids = list(dict.fromkeys(
                    str(value).strip() for value in raw_target_ids if str(value).strip()
                ))
                if not target_ids:
                    raise ValueError(f"Expert domain research steps[{index}] target_ids 不可為空")

                normalized_target = normalize_research_target_params(
                    {"target_type": target_type, "target_ids": target_ids},
                    state,
                )
                if (
                    normalized_target.get("target_type") != target_type
                    or normalized_target.get("target_ids") != target_ids
                ):
                    raise ValueError(f"Expert domain research steps[{index}] target_ids 不在目前 artifact context")

                clean_steps.append({
                    "action": "research_issue",
                    "params": {
                        "query": query,
                        "value_reason": value_reason,
                        "target_type": target_type,
                        "target_ids": target_ids,
                    },
                })

            if research_count < 1:
                raise ValueError("Expert domain research plan 必須包含 research_issue")
            if (
                state.get("referenced_files")
                and state.get("has_read_file")
                and reference_read_count == 0
            ):
                raise ValueError(
                    "Expert domain research plan 必須先讀取 referenced_files"
                )
            clean_steps.append({"action": "update_feedback", "params": {}})
            return {
                "action": "done",
                "params": {},
                "reasoning": reasoning,
                "action_plan": {
                    "goal": goal,
                    "steps": clean_steps,
                },
            }

        try:
            return normalize_once(response)
        except Exception as error:
            if repaired:
                raise ValueError(f"Expert domain research repair 後仍不合格: {error}") from error
            repair_task = repair_plan_output(
                raw=response,
                error=str(error),
                context=research_repair_context(state),
            )
            repaired_response = self.research_plan_json(self.build_direct_messages(repair_task))
            return self.normalize_research_plan(
                repaired_response,
                state=state,
                repaired=True,
            )
