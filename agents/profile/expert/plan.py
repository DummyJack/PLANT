# Plans the next action for the agent.
import json
import re
from typing import Optional

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


def target_keywords(text: str) -> set[str]:
    normalized = str(text or "").lower()
    keywords = set(re.findall(r"[A-Za-z0-9_]+", normalized))
    compact = re.sub(r"[\s　,，。；;:：、/\\|()（）【】「」『』［］\\[\\]{}<>《》\"'`~!！?？.-]+", "", normalized)
    for size in (2, 3, 4):
        if len(compact) < size:
            continue
        for index in range(0, len(compact) - size + 1):
            token = compact[index:index + size]
            if len(set(token)) > 1:
                keywords.add(token)
    return keywords


# ========
# Defines state URL ids function for this module workflow.
# ========
def state_url_ids(state) -> list[str]:
    return [
        str(row.get("id") or "").strip()
        for row in (state.get("URL") or [])
        if isinstance(row, dict) and str(row.get("id") or "").strip()
    ]


# ========
# Defines default research target function for this module workflow.
# ========
def default_research_target(state, query: str = "") -> dict:
    if not isinstance(state, dict):
        return {"target_type": "issue", "target_ids": []}
    issue = state.get("issue") if isinstance(state.get("issue"), dict) else {}
    trace = issue.get("trace") if isinstance(issue.get("trace"), dict) else {}
    issue_url_ids = [
        str(value).strip()
        for value in (trace.get("artifact_ids") or [])
        if str(value).strip().startswith("URL-")
    ]
    if issue_url_ids:
        return {"target_type": "URL", "target_ids": list(dict.fromkeys(issue_url_ids))}
    query_terms = target_keywords(query)
    best: Optional[tuple[int, str]] = None
    for row in state.get("URL") or []:
        if not isinstance(row, dict):
            continue
        req_id = str(row.get("id") or "").strip()
        text = str(row.get("text") or "").lower()
        if not req_id:
            continue
        row_terms = target_keywords(text)
        score = len(query_terms & row_terms)
        if best is None or score > best[0]:
            best = (score, req_id)
    if best and best[0] > 0:
        return {"target_type": "URL", "target_ids": [best[1]]}
    ids = state_url_ids(state)
    if ids:
        return {"target_type": "URL", "target_ids": [ids[0]]}
    if issue:
        issue_id = str(issue.get("id") or issue.get("meeting_id") or "").strip()
        return {"target_type": "issue", "target_ids": [issue_id] if issue_id else []}
    return {"target_type": "issue", "target_ids": []}


# ========
# Defines normalize research target params function for this module workflow.
# ========
def normalize_research_target_params(params: dict, state: dict) -> dict:
    params = params if isinstance(params, dict) else {}
    target_type = str(params.get("target_type") or "").strip()
    target_ids = [
        str(value).strip()
        for value in (params.get("target_ids") or [])
        if str(value).strip()
    ]
    if target_type not in research_target_types or not target_ids:
        fallback = default_research_target(state, str(params.get("query") or ""))
        target_type = fallback["target_type"]
        target_ids = fallback["target_ids"]
    if target_type == "URL":
        valid = set(state_url_ids(state))
        target_ids = [target_id for target_id in target_ids if target_id in valid]
        if not target_ids:
            fallback = default_research_target(state, str(params.get("query") or ""))
            target_type = fallback["target_type"]
            target_ids = fallback["target_ids"]
    return {
        "target_type": target_type,
        "target_ids": list(dict.fromkeys(target_ids)),
    }


# ========
# Defines external research required function for this module workflow.
# ========
def external_research_required(state) -> bool:
    if not isinstance(state, dict):
        return False
    if state.get("has_existing_research") or int(state.get("research_results_count") or 0) > 0:
        return False
    if state.get("baseline_research_needed"):
        return True
    if state.get("user_guidance") or state.get("referenced_files"):
        return True
    coverage_flags = (
        "not_found_in_documents",
        "document_conflict",
        "needs_external_validation",
        "gaps",
    )
    if any(bool(state.get(flag)) for flag in coverage_flags):
        return True
    for row in state.get("document_coverage") or []:
        if not isinstance(row, dict):
            continue
        if str(row.get("status") or "").strip() in coverage_flags:
            return True
    return False


# ========
# Defines default research query function for this module workflow.
# ========
def default_research_query(state) -> str:
    if not isinstance(state, dict):
        return "確認目前需求在此情境下是否有適用的外部規範、主管機關指引、標準或可信公開證據需要補充"
    issue = state.get("issue") if isinstance(state.get("issue"), dict) else {}
    title = str(issue.get("title") or "").strip()
    description = str(issue.get("description") or issue.get("discussion_context") or "").strip()
    scenario = str(state.get("scenario") or "").strip()
    source = "；".join(part for part in (title, description, scenario) if part)
    if not source:
        source = "目前候選需求、scope 與 open questions"
    return f"針對「{source}」確認此情境下是否有適用的外部規範、主管機關指引、標準或可信公開證據需要補充"


def default_research_issue_step(state) -> dict:
    query = compact_research_query(default_research_query(state))
    target = normalize_research_target_params({"query": query}, state)
    return {
        "action": "research_issue",
        "params": {
            "query": query,
            "value_reason": "領域研究階段必須取得至少一個外部或公開來源研究切面，用來檢查目前需求是否有法規、主管機關指引、產業標準或可信公開證據影響。",
            **target,
        },
    }


def ensure_research_issue_step(steps: list[dict], state: dict) -> list[dict]:
    if any(step.get("action") == "research_issue" for step in steps or []):
        return steps
    return [*(steps or []), default_research_issue_step(state)]


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


# ========
# Defines research prompt function for this module workflow.
# ========
def research_prompt(*, state_text: str, obs_text: str) -> str:
    return f"""# 任務
根據目前專案狀態與上一步結果，決定本輪 domain research 要做什麼。

# Action Boundary
- action=expert.plan_research_domain
- 本 action 規劃 domain research 的 action_plan。
- action_plan 可安排 read_reference_docs、research_issue、update_feedback 或 done。
- 只要進入 domain research，本輪 action_plan 必須至少包含 1 個 research_issue；若有 referenced_files，先 read_reference_docs，再 research_issue，最後 update_feedback。
- read_reference_docs 與 research_issue 取得證據；update_feedback 寫回正式 feedback artifact。
- 即使 has_existing_research=true，也必須先做一次全面 coverage/gap audit：檢查既有 feedback 是否已覆蓋目前 scenario、scope、URL、REQ、stakeholders、open_questions、coverage、gaps、user_guidance 與 referenced_files 指出的外部證據缺口與驗收風險。
- 若全面檢查後沒有缺口、沒有外部證據缺口、也沒有 user_guidance / referenced_files 需要查證，才選 done，reasoning 必須明確說明已檢查既有 feedback 足夠。
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
- done：沒有需要研究，或已完成寫回。

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
- 若 resume_checkpoint 存在且 stage_id=research_domain，表示本輪是失敗後繼續；已存在的 document_evidence、document_coverage、research_results 或 feedback 不要重做，只針對 checkpoint.step_id / action 之後尚未完成的缺口繼續。
- referenced_files 或使用者上傳文件存在時，採「文件優先、外部補證」：必須先規劃 read_reference_docs，不能直接用 research_issue 取代文件查證。
- read_reference_docs 必須對相關 URL / REQ / open_questions 做 coverage 分類：document_supported、not_found_in_documents、document_conflict、needs_external_validation。
- domain research 必須規劃至少 1 個 research_issue；文件 coverage 顯示 not_found_in_documents、document_conflict、needs_external_validation，或 issue / user_guidance / referenced_files / gaps 明確標記需要外部查證時，research_issue 必須聚焦那些缺口。
- 若 baseline_research_needed=true，代表本輪研究階段尚未建立任何 feedback，但已有 scenario / URL / REQ / open_questions 與 web_search 可用；此時規劃 1 個中性的 research_issue，優先確認目前 scenario 與 target requirement 是否涉及適用的法規、主管機關指引、產業標準、平台政策或可信公開證據。
- baseline research 應以「情境專屬適用」優先：先找能說明為何適用目前 scenario + target 的來源；若只有通用規範，也必須說明它如何套用到目前 target，否則不要寫入 feedback。
- 如果 has_existing_research=false 且 research_results_count=0，只有在 baseline_research_needed、user_guidance、referenced_files、coverage、gaps 或 issue 明確標記需要外部查證時，才至少取得 1 個外部證據；但若 referenced_files 存在，必須先 read_reference_docs，再針對文件缺口或仍需外部查證的議題規劃 research_issue。
- 即使沒有上述外部研究觸發條件，也要規劃 1 個情境專屬的 baseline research_issue；只有在 action_plan 已完成後才可 done。
- 只有存在 high-value research_issue 時，才規劃 research_issue；若已讀取引用文件或取得研究結果，最後執行 update_feedback。
- 需要專案文件證據時先用 read_reference_docs。
- 若目前專案狀態包含 referenced_files，必須先規劃 read_reference_docs，且 query 應聚焦使用者建議與這些文件。
- 若 referenced_files 為空，不要因為文件庫有檔案就自動規劃 read_reference_docs；只有研究問題明確需要專案文件證據時才使用。
- 需要外部證據時用 research_issue；每個 research_issue 只處理一個明確高價值問題，且 query / value_reason 必須說明它是文件缺口、文件衝突、外部證據缺口或時效性驗證。
- value_reason 必須連回目前 artifact context，說明此查證會影響哪個需求品質面向；不能只說「查標準」或「查最佳實務」。
- 若多個高價值問題分屬不同面向，可以拆成多個 research_issue；最多 {max_research_issues} 個。
- 不要把多個互不相干的外部查證問題塞進同一個過大的 query。
- 每個 research_issue.params 必須包含 query 與 value_reason。
- 每個 research_issue 只能處理 target_ids 指定的目標；若有多個互不相干 target，拆成多個 research_issue。
- 只要有 read_reference_docs、research_issue 或已有 research_results，最後必須 update_feedback。
- update_feedback 只允許放在 action_plan 最後一次。
- feedback.sources 集中列出來源；web 來源使用 {{"title": "web_search 或官方頁面提供的人可讀頁面/文件標題，不可填 URL", "url": "完整 URL"}}，專案引用文件使用 {{"title": "檔名", "url": "專案文件路徑", "type": "file"}}。
- 若 user_guidance 沒有足夠證據支持，feedback 不得把它寫成確定限制；只能記錄為風險、不確定性或後續待釐清方向。
- feedback 只寫入被 document_evidence / research_results 支持且能對應到相關 artifact 的內容；不要把 user_guidance 原文逐項轉成 findings、constraints、risks 或 recommendations。

# Output JSON
{{
  "research_plan": {{
    "action": "done",
    "params": {{}},
    "reasoning": "使用目前輸出語系的一句說明",
    "action_plan": {{
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
  }}
}}"""


# ========
# Defines ExpertResearchPlan class for this module workflow.
# ========
class ExpertResearchPlan:
    # Defines plan research function for this module workflow.
    def plan_research(self, state, last_observation=None):
        if state.get("actions_taken"):
            return {
                "action": "done",
                "params": {},
                "reasoning": "已依 research_domain 規劃完成本輪研究，不重新規劃。",
            }
        state_text = json.dumps(state, ensure_ascii=False, indent=2)
        obs_text = json.dumps(last_observation or {}, ensure_ascii=False, indent=2)

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
                except Exception as parse_error:
                    repair_task = repair_plan_output(
                        raw=raw,
                        error=f"上一輪輸出不是合法 JSON object: {parse_error}",
                    )
                    response = self.chat_json(self.build_direct_messages(repair_task))
            else:
                response = self.chat_json(messages)
        except Exception as e:
            raise RuntimeError(f"Expert domain research 決策輸出格式不合格: {e}") from e
        if not isinstance(response, dict):
            raise ValueError(f"Expert domain research 決策必須是 JSON object，收到 {type(response).__name__}")

        return self.normalize_research_plan(response, state=state)

    # Defines normalize research plan function for this module workflow.
    def normalize_research_plan(self, response, *, state=None, repaired: bool = False):
        state = state if isinstance(state, dict) else {}
        if not isinstance(response, dict) or not isinstance(response.get("research_plan"), dict):
            raise ValueError("Expert domain research plan output must contain research_plan object")
        response = response["research_plan"]
        action_plan = response.get("action_plan") if isinstance(response.get("action_plan"), dict) else {}
        steps = action_plan.get("steps") if isinstance(action_plan.get("steps"), list) else []
        clean_steps = []
        research_count = 0
        for step in steps:
            if not isinstance(step, dict):
                continue
            step_action = str(step.get("action") or "").strip()
            if step_action not in {"read_reference_docs", "research_issue", "update_feedback"}:
                continue
            if step_action == "update_feedback":
                continue
            params = step.get("params") if isinstance(step.get("params"), dict) else {}
            if step_action in {"read_reference_docs", "research_issue"} and not str(params.get("query") or "").strip():
                continue
            if step_action == "research_issue":
                if research_count >= max_research_issues:
                    continue
                target = normalize_research_target_params(params, state)
                params = {
                    "query": compact_research_query(str(params.get("query") or "").strip()),
                    "value_reason": str(params.get("value_reason") or "").strip(),
                    **target,
                }
                if not params["value_reason"] and not repaired:
                    repair_task = repair_plan_output(
                        raw=response,
                        error="research_issue 必須包含 params.value_reason，說明為什麼此問題值得研究",
                    )
                    repaired_response = self.chat_json(self.build_direct_messages(repair_task))
                    if not isinstance(repaired_response, dict):
                        raise ValueError(
                            f"Expert domain research repair 必須是 JSON object，收到 {type(repaired_response).__name__}"
                        )
                    return self.normalize_research_plan(
                        repaired_response,
                        state=state,
                        repaired=True,
                    )
                research_count += 1
            elif step_action == "read_reference_docs":
                params = {"query": compact_research_query(str(params.get("query") or "").strip())}
            clean_steps.append({"action": step_action, "params": params})
        if clean_steps:
            clean_steps = ensure_research_issue_step(clean_steps, state)
        if any(step.get("action") in {"read_reference_docs", "research_issue"} for step in clean_steps):
            clean_steps.append({"action": "update_feedback", "params": {}})
        if clean_steps:
            return {
                "action": "done",
                "params": {},
                "reasoning": response.get("reasoning", ""),
                "action_plan": {
                    "goal": str(action_plan.get("goal") or "").strip(),
                    "steps": clean_steps,
                },
            }

        action = (response.get("action") or "").strip()
        if action not in research_actions:
            if not repaired:
                repair_task = repair_plan_output(
                    raw=response,
                    error=f"action 不合法: {action or '<empty>'}",
                )
                repaired_response = self.chat_json(self.build_direct_messages(repair_task))
                if not isinstance(repaired_response, dict):
                    raise ValueError(
                        f"Expert domain research repair 必須是 JSON object，收到 {type(repaired_response).__name__}"
                    )
                return self.normalize_research_plan(
                    repaired_response,
                    state=state,
                    repaired=True,
                )
            raise ValueError(f"Expert domain research action 不合法: {action or '<empty>'}")
        if action in {"done", "update_feedback"}:
            return {
                "action": "done",
                "params": {},
                "reasoning": response.get("reasoning", "")
                or "領域研究階段必須先執行 research_issue，再更新 feedback。",
                "action_plan": {
                    "goal": "確認外部證據是否影響需求定稿",
                    "steps": [
                        default_research_issue_step(state),
                        {"action": "update_feedback", "params": {}},
                    ],
                },
            }
        if action == "read_reference_docs":
            params = response.get("params") if isinstance(response.get("params"), dict) else {}
            query = compact_research_query(str(params.get("query") or params.get("topic") or "").strip())
            if not query:
                query = compact_research_query(default_research_query(state))
            steps = ensure_research_issue_step(
                [{"action": "read_reference_docs", "params": {"query": query}}],
                state,
            )
            steps.append({"action": "update_feedback", "params": {}})
            return {
                "action": "done",
                "params": {},
                "reasoning": response.get("reasoning", ""),
                "action_plan": {
                    "goal": "先讀取參考文件，再執行情境專屬領域研究並更新 feedback",
                    "steps": steps,
                },
            }
        if action == "research_issue":
            params = response.get("params") if isinstance(response.get("params"), dict) else {}
            target = normalize_research_target_params(params, state)
            clean_params = {
                "query": compact_research_query(str(params.get("query") or "").strip()),
                "value_reason": str(params.get("value_reason") or "").strip(),
                **target,
            }
            if not clean_params["query"]:
                raise ValueError("Expert domain research research_issue 必須包含 params.query")
            if not clean_params["value_reason"] and not repaired:
                repair_task = repair_plan_output(
                    raw=response,
                    error="research_issue 必須包含 params.value_reason，說明為什麼此問題值得研究",
                )
                repaired_response = self.chat_json(self.build_direct_messages(repair_task))
                if not isinstance(repaired_response, dict):
                    raise ValueError(
                        f"Expert domain research repair 必須是 JSON object，收到 {type(repaired_response).__name__}"
                    )
                return self.normalize_research_plan(
                    repaired_response,
                    state=state,
                    repaired=True,
                )
            return {
                "action": "done",
                "params": {},
                "reasoning": response.get("reasoning", ""),
                "action_plan": {
                    "goal": "",
                    "steps": [
                        {"action": "research_issue", "params": clean_params},
                        {"action": "update_feedback", "params": {}},
                    ],
                },
            }
        return {
            "action": action,
            "params": response.get("params") or {},
            "reasoning": response.get("reasoning", ""),
        }
