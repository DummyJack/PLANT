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
    for req in artifact.get("requirements") or artifact.get("URL") or []:
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


def research_stakeholders(artifact):
    rows = []
    for stakeholder in artifact.get("stakeholders") or []:
        if not isinstance(stakeholder, dict):
            continue
        name = str(stakeholder.get("name") or "").strip()
        if not name:
            continue
        row = {"name": name}
        stakeholder_type = str(stakeholder.get("type") or "").strip()
        if stakeholder_type:
            row["type"] = stakeholder_type
        rows.append(row)
    return rows


def research_open_questions(artifact):
    rows = []
    for question in artifact.get("open_questions") or []:
        if not isinstance(question, dict):
            continue
        text = str(question.get("question") or "").strip()
        if not text:
            continue
        rows.append(
            {
                "question": text,
                "status": question.get("status"),
                "type": question.get("type"),
            }
        )
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
            "user_requirements": URL,
            "stakeholders": research_stakeholders(artifact),
            "open_questions": research_open_questions(artifact),
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
                "user_requirements": research_requirement_candidates(artifact),
                "stakeholders": research_stakeholders(artifact),
                "open_questions": research_open_questions(artifact),
            }
            task = f"""針對以下問題進行領域研究：{query}

    請使用 `domain-research` skill 的研究方法與證據蒐集準則；若 skill 範例與本任務輸出格式不同，必須以本任務的 feedback JSON 結構為準。

    只輸出本專案 feedback JSON。

    研究邊界：
    - 根據 scenario、scope、stakeholders、open_questions 與 user_requirements 判斷外部領域因素；user_requirements 優先使用正式 requirements，若尚無正式 requirements 才使用 URL 候選需求；URL 是舊欄位名稱，不是網站連結。
    - feedback 只作為領域研究輔助資料，不產生需求。
    - 需要證據時可使用本輪工具使用資料中允許的工具。
    - findings、constraints、risks、recommendations、open_items 的每個 item 請輸出 text 與 related_URL。
    - 每筆 related_URL 必須盡可能對應到受影響的 user_requirements id。
    - related_URL 只能引用 user_requirements 中存在的 id；不得編造不存在的 URL-*。
    - 若內容是整體專案層級或確實無法對應單一需求，related_URL 才可輸出空陣列。
    - 不要為了填欄位硬關聯需求。
    - findings 是領域研究發現或外部事實，只提供背景與依據，不代表系統需求或決策。
    - sources 只放來源名稱、文件名稱、標準名稱或 URL；不要在 sources 中寫長段分析。
    - constraints 是會限制系統行為、資料處理、合規、流程或外部整合的約束；只有具明確約束力或強限制效果的內容才放入 constraints。
    - risks 是若需求未處理或規則未釐清時可能造成的合規、安全、營運、使用者權益或資料風險。
    - recommendations 是設計注意事項或後續確認建議，不是正式需求。
    - recommendations 不得使用「系統必須」「平台必須」「使用者必須」這類定案語氣；除非法律明確適用且 related_URL 對應清楚。
    - open_items 是仍需 stakeholder、analyst、法規範圍或第三方服務條款確認的問題；不得寫成已確認限制或需求。

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
            task = """綜合本輪 research_results 與 existing_research（artifact.feedback 既有領域研究），整理成本專案 feedback 格式。

    合併邊界：
    - 只做合併、去重、保留來源與整理格式。
    - existing_research 只可作為合併與去重依據，不可當成新的外部證據，也不可自行延伸新結論。
    - 不新增 research_results / existing_research 以外的結論。
    - 不得捏造來源、法規、數值門檻或研究結論。
    - feedback 只作為領域研究輔助資料，不產生需求。
    - 若 skill 範例或研究資料包含 requirement_implications，本任務只能將其整理為 constraints、risks、recommendations 或 open_items，不得輸出正式 requirements。
    - findings、constraints、risks、recommendations、open_items 的每個 item 保持 text 與 related_URL。
    - 每筆 related_URL 必須盡可能保留或補上受影響的 user_requirements id；只能引用 research_results 或 existing_research 中已出現的 id，不得編造不存在的 URL-*。
    - 若內容是整體專案層級或確實無法對應單一需求，related_URL 才可輸出空陣列。
    - findings 是領域研究發現或外部事實，只提供背景與依據，不代表系統需求或決策。
    - sources 只放來源名稱、文件名稱、標準名稱或 URL；不要在 sources 中寫長段分析。
    - constraints 是會限制系統行為、資料處理、合規、流程或外部整合的約束；只有具明確約束力或強限制效果的內容才放入 constraints。
    - risks 是若需求未處理或規則未釐清時可能造成的合規、安全、營運、使用者權益或資料風險。
    - recommendations 是設計注意事項或後續確認建議，不是正式需求。
    - recommendations 不得使用「系統必須」「平台必須」「使用者必須」這類定案語氣；除非法律明確適用且 related_URL 對應清楚。
    - open_items 是仍需 stakeholder、analyst、法規範圍或第三方服務條款確認的問題；不得寫成已確認限制或需求。

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
    根據 scenario、scope、stakeholders、open_questions、user_requirements（正式 requirements 優先，URL 候選需求 fallback）與上一步結果，選下一個動作。

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
    - 研究問題必須來自 scenario、scope、stakeholders、open_questions 或 user_requirements 中的具體內容；URL 不是網站連結。
    - 若問題可由利害關係人或既有專案資料回答，不要選 research_issue。
    - 選 done 前，請確認是否已檢查與本專案相關的外部限制面向：
      - 支付/金流安全與退款
      - 個資、隱私、資料保存與稽核
      - 消費者保護、客服與爭議處理
      - 即時定位、外送追蹤與個資遮蔽
      - 高峰流量、可用性與營運連續性
    - 若某面向與 user_requirements 無關，可略過，不需硬研究。
    - 若尚未研究任何面向，且 user_requirements 涉及支付、個資、退款、定位、稽核或高可用，優先選 research_issue。
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
