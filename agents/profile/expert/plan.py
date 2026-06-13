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


# ========
# Defines research prompt function for this module workflow.
# ========
def research_prompt(*, state_text: str, obs_text: str) -> str:
    return f"""# 任務
根據目前專案狀態與上一步結果，決定本輪 domain research 要做什麼。

- research_domain 是流程 action，不是單一產物 action。
- 本流程只規劃一次，之後依 action_plan 逐一執行 read_reference_docs、research_issue、update_feedback。
- read_reference_docs 與 research_issue 只取得證據；只有 update_feedback 會寫回正式 feedback artifact。
- 不得把 feedback 直接定案成需求；需求正式化由 Analyst action 處理。

# 目前專案狀態
{state_text}

# 上一步結果
{obs_text}

- read_reference_docs：讀專案內部文件，取得文件證據。
- research_issue：查外部領域知識、法規、標準、官方文件、第三方限制或最佳實務。
- update_feedback：把已取得的研究結果寫回 feedback。
- done：沒有需要研究，或已完成寫回。

- 研究問題必須來自目前 issue、scenario、scope、stakeholders、open_questions、URL 或 REQ。
- 只規劃 high-value research_issue，不為了湊數研究。
- high-value 指會影響需求是否成立、系統邊界、法規/合規/安全、責任歸屬、驗收標準、多個 URL/REQ，或目前 artifact 沒有清楚答案。
- 不研究低價值內容：一般功能偏好、已清楚的 UI 操作、不影響需求條文的背景知識、與 scope 無關的產業介紹。
- 若既有 artifact / feedback 已足夠涵蓋目前高價值問題，選 done，不重複研究。
- 如果 has_existing_research=false 且 research_results_count=0，且內容涉及支付、退款、個資、隱私、安全、法規、合規、第三方、資料保存、稽核、責任歸屬、補償或申訴，必須至少規劃 1 個 research_issue。
- 如果沒有上述外部研究觸發條件、沒有高價值且可取得可靠來源的研究問題，可以選 done，但 reasoning 必須明確說明未觸發外部研究條件。
- 只有存在 high-value research_issue 時，才規劃 research_issue，最後執行 update_feedback。
- 需要專案文件證據時先用 read_reference_docs。
- 若目前專案狀態包含 referenced_files，必須先規劃 read_reference_docs，且 query 應聚焦使用者建議與這些文件。
- 若 referenced_files 為空，不要因為文件庫有檔案就自動規劃 read_reference_docs；只有研究問題明確需要專案文件證據時才使用。
- 需要外部證據時用 research_issue；每個 research_issue 只處理一個明確高價值問題。
- 若多個高價值問題分屬不同面向，可以拆成多個 research_issue；最多 {max_research_issues} 個。
- 不要把法規、安全、責任歸屬、營運限制與驗收標準全部塞進同一個過大的 query。
- 每個 research_issue.params 必須包含 query 與 value_reason。
- 只要有 research_issue 或已有 research_results，最後必須 update_feedback。
- update_feedback 只允許放在 action_plan 最後一次。
- feedback.sources 每筆使用 {{"title": "可讀來源名稱", "url": "完整 URL"}}；title 使用法規、標準、官方文件、組織文章或案例名稱。

# Output JSON
{{
  "research_plan": {{
    "action": "done",
    "params": {{}},
    "reasoning": "一句繁體中文說明",
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
                    "query": str(params.get("query") or "").strip(),
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
                params = {"query": str(params.get("query") or "").strip()}
            clean_steps.append({"action": step_action, "params": params})
        if any(step.get("action") == "research_issue" for step in clean_steps):
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
                "query": str(params.get("query") or "").strip(),
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
