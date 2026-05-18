# Expert domain research: optional skill context plus evidence gathering loop.
import json

from agents.profile.scenario import scenario_prompt_value

from .validation import clean_domain_research, clean_research_result


ACTIONS = [
    "research_issue",
    "update_findings",
    "done",
]


def research_requirement_candidates(artifact):
    rows = []
    for req in artifact.get("URL") or []:
        if not isinstance(req, dict) or not str(req.get("text") or "").strip():
            continue
        row = {
            "id": req.get("id"),
            "text": req.get("text"),
            "priority": req.get("priority"),
            "source": req.get("source", ""),
        }
        rows.append(row)
    return rows


class ExpertDomainResearch:
    def run_domain_research_loop(self, artifact):
        """Expert domain research 走共用 agent loop，研究結果寫回 feedback。"""
        result = self.run_action_loop(
            name="domain_research",
            context={
                "artifact": artifact,
                "research_results": [],
            },
            build_observation=self.build_domain_research_observation,
            decide_action=self.decide_domain_research_action,
            execute_action=self.execute_domain_research_loop_action,
        )
        return result

    def build_research_observation(
        self, artifact,
        research_results, iteration, max_iterations,
    ):
        URL = research_requirement_candidates(artifact)
        existing = artifact.get("feedback") if isinstance(artifact.get("feedback"), dict) else {}
        scenario_source = artifact.get("scenario") or artifact.get("rough_idea")
        return {
            "scenario": scenario_prompt_value(scenario_source),
            "scope": artifact.get("scope", {}),
            "URL": URL,
            "has_existing_research": bool(existing),
            "research_results_count": len(research_results),
            "iteration": iteration + 1,
            "max_iterations": max_iterations,
        }

    def execute_domain_research_action(
        self, action, params, artifact, research_results,
    ):
        obs: dict = {"action": action, "result": None, "error": None, "summary": ""}

        if action == "research_issue":
            query = params.get("query", "")
            if not query:
                obs["error"] = "query 參數為空"
                obs["summary"] = "研究失敗：未提供研究問題"
                return obs
            scenario_source = artifact.get("scenario") or artifact.get("rough_idea")
            context = {
                "scenario": scenario_prompt_value(scenario_source),
                "scope": artifact.get("scope", {}),
                "URL": research_requirement_candidates(artifact),
            }
            task = f"""針對以下問題進行領域研究：{query}

    請依 `domain-research` skill 執行研究。

    只輸出本專案 feedback JSON。

    研究邊界：
    - 根據產品情境、需求範圍與 User Requirements 判斷外部領域因素。
    - feedback 只作為研究輔助資料，不產生需求。
    - 需要證據時可使用本輪工具使用資料中允許的工具。
    - findings、constraints、risks、recommendations、open_items 的每個 item 請輸出 text 與 related_URL。
    - related_URL 只能引用 User Requirements 中存在的 id；整體專案層級請輸出空陣列。
    - 不要為了填欄位硬關聯需求。

    輸出 JSON：
    {{
      "findings": [{{"text": "", "related_URL": []}}],
      "sources": [],
      "constraints": [{{"text": "", "related_URL": []}}],
      "risks": [{{"text": "", "related_URL": []}}],
      "recommendations": [{{"text": "", "related_URL": []}}],
      "open_items": [{{"text": "", "related_URL": []}}]
    }}"""
            messages = self.build_direct_messages(task, context=context)
            try:
                raw = (
                    self.chat_with_tools(
                        messages,
                        active_skill="domain-research",
                    )
                    if self.tools
                    else self.model.chat(messages)
                )
                result = clean_research_result(self.parse_first_json(raw))
                research_results.append({"query": query, **result})
                obs["result"] = result
                obs["summary"] = (
                    f"研究 '{query}': "
                    f"{len(result.get('findings', []))} 項發現"
                )
            except Exception as e:
                obs["error"] = str(e)
                obs["summary"] = f"研究失敗: {e}"
            return obs

        if action == "update_findings":
            if not research_results:
                obs["summary"] = "無研究結果可更新"
                return obs
            existing = artifact.get("feedback") if isinstance(artifact.get("feedback"), dict) else {}
            context = {
                "research_results": research_results,
                "existing_research": existing,
            }
            task = """綜合本輪研究結果與既有 feedback，整理成本專案 feedback 格式。

    合併邊界：
    - 只做合併、去重、保留來源與整理格式。
    - 不新增 research_results / existing_research 以外的結論。
    - 不得捏造來源、法規、數值門檻或研究結論。
    - feedback 只作為研究輔助資料，不產生需求。
    - findings、constraints、risks、recommendations、open_items 的每個 item 保持 text 與 related_URL。

    輸出 JSON：
    {
      "findings": [{"text": "", "related_URL": []}],
      "sources": [],
      "constraints": [{"text": "", "related_URL": []}],
      "risks": [{"text": "", "related_URL": []}],
      "recommendations": [{"text": "", "related_URL": []}],
      "open_items": [{"text": "", "related_URL": []}]
    }"""
            try:
                raw = self.invoke_skill("domain-research", task, context=context)
                dr = clean_domain_research(self.parse_first_json(raw))
                if dr:
                    artifact["feedback"] = dr
                    obs["summary"] = "已更新領域研究資料"
                else:
                    obs["error"] = "解析失敗"
                    obs["summary"] = "更新失敗：解析錯誤"
            except Exception as e:
                obs["error"] = str(e)
                obs["summary"] = f"更新失敗: {e}"
            return obs

        obs["error"] = f"未知動作: {action}"
        return obs

    def decide_research_action(self, state, last_observation=None):
        state_text = json.dumps(state, ensure_ascii=False, indent=2)
        obs_text = json.dumps(last_observation or {}, ensure_ascii=False, indent=2)

        user_prompt = f"""# 任務
    根據 scenario、scope、URL 與上一步結果，選下一個動作。

    # 動作
    - research_issue：{{"query":"具體研究問題"}}
    - update_findings：把已足夠的研究結果寫回 artifact
    - done：結束

    # 當前狀態
    {state_text}

    # 上一步結果
    {obs_text}

    # 規則
    - 只有當外部領域知識可能影響候選需求理解、限制、風險或證據依據時，才選 research_issue。
    - 研究問題必須來自 scenario、scope 或 URL 中的具體內容。
    - 若問題可由利害關係人或既有專案資料回答，不要選 research_issue。
    - 每次 research_issue 只聚焦一個具體問題
    - 工具使用邊界遵守本輪工具使用資料
    - 有足夠材料才 update_findings
    - 無需再研究就選 done
    - reasoning 請使用一句繁體中文簡述。

    # 輸出 JSON
    {{
      "action": "動作名稱",
      "params": {{}},
      "reasoning": "一句說明"
    }}"""

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

        action = (response.get("action") or "").strip()
        if action not in ACTIONS:
            raise ValueError(f"Expert domain research action 不合法: {action or '<empty>'}")
        out = {
            "action": action,
            "params": response.get("params") or {},
            "reasoning": response.get("reasoning", ""),
        }
        return out
