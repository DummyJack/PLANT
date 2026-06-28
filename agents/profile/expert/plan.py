# Plans the next action for the agent.
import json

from .repair import repair_plan_output


research_actions = [
    "read_reference_docs",
    "research_issue",
    "update_feedback",
    "done",
]

max_research_issues = 4
max_research_query_chars = 360

research_trigger_terms = (
    "法規",
    "法律",
    "條例",
    "規範",
    "標準",
    "合規",
    "稽核",
    "認證",
    "個資",
    "隱私",
    "安全",
    "支付",
    "付款",
    "退款",
    "信用卡",
    "第三方",
    "資料保存",
    "資料保留",
    "責任歸屬",
    "補償",
    "申訴",
    "PDPA",
    "PCI",
    "ISO",
    "GDPR",
    "privacy",
    "security",
    "compliance",
    "payment",
    "refund",
    "audit",
    "third-party",
)


# ========
# Defines external research required function for this module workflow.
# ========
def external_research_required(state) -> bool:
    if not isinstance(state, dict):
        return False
    if state.get("has_existing_research") or int(state.get("research_results_count") or 0) > 0:
        return False
    text = json.dumps(
        {
            "issue": state.get("issue", {}),
            "scenario": state.get("scenario", ""),
            "scope": state.get("scope", {}),
            "URL": state.get("URL", []),
            "REQ": state.get("REQ", []),
            "open_questions": state.get("open_questions", []),
        },
        ensure_ascii=False,
    ).lower()
    return any(term.lower() in text for term in research_trigger_terms)


# ========
# Defines default research query function for this module workflow.
# ========
def default_research_query(state) -> str:
    if not isinstance(state, dict):
        return "確認目前需求是否涉及外部法規、標準、合規、安全、支付、隱私或第三方限制"
    issue = state.get("issue") if isinstance(state.get("issue"), dict) else {}
    title = str(issue.get("title") or "").strip()
    description = str(issue.get("description") or issue.get("discussion_context") or "").strip()
    scenario = str(state.get("scenario") or "").strip()
    source = "；".join(part for part in (title, description, scenario) if part)
    if not source:
        source = "目前候選需求、scope 與 open questions"
    return f"針對「{source}」確認是否存在外部法規、標準、合規、安全、支付、隱私或第三方限制"


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
- read_reference_docs 與 research_issue 取得證據；update_feedback 寫回正式 feedback artifact。
- 即使 has_existing_research=true，也必須先做一次全面 coverage/gap audit：檢查既有 feedback 是否已覆蓋目前 scenario、scope、URL、REQ、stakeholders 與 open_questions 的高風險外部限制、法規/合規、安全、隱私、第三方、責任歸屬與驗收風險。
- 若全面檢查後沒有缺口、沒有高風險外部議題、也沒有 user_guidance / referenced_files 需要查證，才選 done，reasoning 必須明確說明已檢查既有 feedback 足夠。
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
- research_issue：查外部領域知識、法規、標準、官方文件、第三方限制或最佳實務。
- update_feedback：把已取得的研究結果寫回 feedback。
- done：沒有需要研究，或已完成寫回。

- 研究問題必須來自目前 issue、scenario、scope、stakeholders、open_questions、URL 或 REQ。
- 若 user_guidance 指出特定方向，優先判斷它是否對需求成立、系統邊界、法規/合規/安全、責任歸屬或驗收標準有影響；有影響才規劃 read_reference_docs 或 research_issue 查證。
- 不要因為 user_guidance 提到某方向，就把所有研究問題都改成該方向；只在目前 artifact 明確相關的研究問題中反映。
- 只規劃 high-value research_issue，不為了湊數研究。
- high-value 指會影響需求是否成立、系統邊界、法規/合規/安全、責任歸屬、驗收標準、多個 URL/REQ，或目前 artifact 沒有清楚答案。
- 不研究低價值內容：一般功能偏好、已清楚的 UI 操作、不影響需求條文的背景知識、與 scope 無關的產業介紹。
- 若既有 artifact / feedback 已足夠涵蓋目前高價值問題，選 done，不重複研究；但 reasoning 必須說明檢查了哪些面向且為何沒有漏掉需要新增研究的部分。
- 若 resume_checkpoint 存在且 stage_id=research_domain，表示本輪是失敗後繼續；已存在的 document_evidence、document_coverage、research_results 或 feedback 不要重做，只針對 checkpoint.step_id / action 之後尚未完成的缺口繼續。
- referenced_files 或使用者上傳文件存在時，採「文件優先、外部補證」：必須先規劃 read_reference_docs，不能直接用 research_issue 取代文件查證。
- read_reference_docs 必須對相關 URL / REQ / open_questions 做 coverage 分類：document_supported、not_found_in_documents、document_conflict、needs_external_validation。
- 只有文件 coverage 顯示 not_found_in_documents、document_conflict、needs_external_validation，或議題本身涉及可能變動的外部法規/標準/第三方條款/官方政策時，才規劃 research_issue。
- 如果 has_existing_research=false 且 research_results_count=0，且內容涉及支付、退款、個資、隱私、安全、法規、合規、第三方、資料保存、稽核、責任歸屬、補償或申訴，必須至少取得 1 個外部證據；但若 referenced_files 存在，必須先 read_reference_docs，再針對文件缺口或高風險外部議題規劃 research_issue。
- 如果沒有上述外部研究觸發條件、沒有高價值且可取得可靠來源的研究問題，可以選 done，但 reasoning 必須明確說明未觸發外部研究條件。
- 只有存在 high-value research_issue 時，才規劃 research_issue；若已讀取引用文件或取得研究結果，最後執行 update_feedback。
- 需要專案文件證據時先用 read_reference_docs。
- 若目前專案狀態包含 referenced_files，必須先規劃 read_reference_docs，且 query 應聚焦使用者建議與這些文件。
- 若 referenced_files 為空，不要因為文件庫有檔案就自動規劃 read_reference_docs；只有研究問題明確需要專案文件證據時才使用。
- 需要外部證據時用 research_issue；每個 research_issue 只處理一個明確高價值問題，且 query / value_reason 必須說明它是文件缺口、文件衝突、外部高風險或時效性驗證。
- 若多個高價值問題分屬不同面向，可以拆成多個 research_issue；最多 {max_research_issues} 個。
- 不要把法規、安全、責任歸屬、營運限制與驗收標準全部塞進同一個過大的 query。
- 每個 research_issue.params 必須包含 query 與 value_reason。
- 只要有 read_reference_docs、research_issue 或已有 research_results，最後必須 update_feedback。
- update_feedback 只允許放在 action_plan 最後一次。
- feedback.sources 集中列出來源；web 來源使用 {{"title": "可讀來源名稱", "url": "完整 URL"}}，專案引用文件使用 {{"title": "檔名", "url": "專案文件路徑", "type": "file"}}。
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
                response = self.parse_issue_response_json(raw)
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
                params = {
                    "query": compact_research_query(str(params.get("query") or "").strip()),
                    "value_reason": str(params.get("value_reason") or "").strip(),
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
        if action == "done" and external_research_required(state):
            query = default_research_query(state)
            query = compact_research_query(query)
            return {
                "action": "done",
                "params": {},
                "reasoning": "偵測到外部法規、合規、安全、支付或第三方限制訊號，先執行高價值領域研究。",
                "action_plan": {
                    "goal": "確認外部限制是否影響需求定稿",
                    "steps": [
                        {
                            "action": "research_issue",
                            "params": {
                                "query": query,
                                "value_reason": "此問題可能影響需求是否成立、驗收標準、風險、責任邊界或系統限制。",
                            },
                        },
                        {"action": "update_feedback", "params": {}},
                    ],
                },
            }
        if action == "research_issue":
            params = response.get("params") if isinstance(response.get("params"), dict) else {}
            clean_params = {
                "query": compact_research_query(str(params.get("query") or "").strip()),
                "value_reason": str(params.get("value_reason") or "").strip(),
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
        if action == "done" and state.get("research_results_count", 0) > 0:
            action = "update_feedback"
        return {
            "action": action,
            "params": response.get("params") or {},
            "reasoning": response.get("reasoning", ""),
        }
