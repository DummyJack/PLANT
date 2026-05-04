# Expert domain research: optional skill context plus evidence gathering loop.
import json
from typing import Dict, Optional

from agents.base import short_reasoning_line


EXPERT_DOMAIN_RESEARCH_ACTIONS = [
    "research_topic",
    "update_findings",
    "flag_compliance_risk",
    "done",
]


class ExpertDomainResearch:
    def get_optional_skill_context(
        self, topic: Dict, artifact_snapshot: Optional[Dict]
    ) -> Optional[str]:
        return super().get_optional_skill_context(topic, artifact_snapshot)

    def run_domain_research_loop(self, artifact, recent_discussions=None, *, max_iterations):
        """Expert domain research 走共用 OPA loop；研究結果透過 context 傳遞，必要時在單輪內保證寫回 findings。"""
        loop_cap = max(self.self_review_round_cap(), 2)
        effective_max = min(max_iterations, self.self_review_round_cap())
        internal_max = 2 if effective_max == 1 else effective_max
        result = self.run_action_loop(
            name="domain_research",
            max_iterations=internal_max,
            loop_cap=loop_cap,
            context={
                "artifact": artifact,
                "recent_discussions": recent_discussions,
                "research_results": [],
                "pending_issues": [],
                "force_update_after_research": effective_max == 1,
                "requested_max_iterations": effective_max,
            },
            build_observation=self.build_domain_research_observation,
            decide_action=self.decide_domain_research_action,
            execute_action=self.execute_domain_research_loop_action,
        )
        return result

    def build_domain_research_state(
        self, artifact, recent_discussions, actions_taken,
        research_results, iteration, max_iterations,
    ):
        reqs = artifact.get("requirements", [])
        summary_reqs = [
            {"id": r.get("id"), "type": r.get("type"),
             "text": (r.get("text") or "")}
            for r in reqs
        ]
        conflicts = [
            {"id": c.get("id"),
             "description": (c.get("description") or "")}
            for c in artifact.get("conflicts", [])
            if c.get("label") == "Conflict"
        ]
        neutrals = [
            {"id": c.get("id"),
             "description": (c.get("description") or "")}
            for c in artifact.get("conflicts", [])
            if c.get("label") == "Neutral"
        ]
        disc_summaries = []
        for disc in (recent_discussions or []):
            topic = disc.get("topic", {})
            resolution = disc.get("resolution", {})
            disc_summaries.append({
                "topic_id": topic.get("id"),
                "title": topic.get("title"),
                "resolution": resolution.get("resolution"),
                "summary": (resolution.get("summary") or ""),
            })
        existing = artifact.get("feedback", {}).get("domain_research", {})
        return {
            "requirements": summary_reqs,
            "conflicts": conflicts,
            "neutrals": neutrals,
            "scope": artifact.get("scope", {}),
            "has_existing_research": bool(existing),
            "recent_discussions": disc_summaries,
            "actions_taken": actions_taken,
            "research_results_count": len(research_results),
            "available_tools": list(self.tools.keys()),
            "iteration": iteration + 1,
            "max_iterations": max_iterations,
        }

    def execute_domain_research_action(
        self, action, params, artifact, pending_issues, research_results,
    ):
        obs: Dict = {"action": action, "result": None, "error": None, "summary": ""}

        if action == "research_topic":
            query = params.get("query", "")
            if not query:
                obs["error"] = "query 參數為空"
                obs["summary"] = "研究失敗：未提供研究問題"
                return obs
            max_rounds = params.get("max_tool_rounds")
            tmax = self.tool_call_max_rounds
            if max_rounds is not None and isinstance(max_rounds, int) and 1 <= max_rounds <= tmax:
                tool_rounds = max_rounds
            else:
                tool_rounds = self.tool_call_max_rounds
            context = {
                "project_overview": (artifact.get("scope") or {}).get(
                    "description", ""
                ),
            }
            tool_part = "工具使用順序：先 artifact_query 查專案內部狀態，再 file_parser 查 doc/ 內容，最後才用 web_search 補外部證據；web_search 搜尋時可帶 user_question 以利停止條件，且只用來補法規、標準、最佳實務或外部風險依據，不可覆蓋 artifact 內已知事實"
            if self.has_doc_reference_files():
                tool_part += (
                    "；file_parser 請優先 search_chunks 再 read_chunks 讀 doc/，必要時才 read_full"
                )
            task = f"""針對以下問題進行領域研究：{query}

    請依 `domain-research` skill 的最新 evidence-first contract 執行研究並輸出 JSON。

    執行邊界：
    - {tool_part}
    - 研究結果預設作為 evidence，不直接形成正式 requirement。
    - 僅當外部來源構成明確、可追溯、具約束力的 obligation 時，才可產生 derived requirement candidates。
    - 不可把最佳實務、一般建議或風險提醒直接升格成 requirement。

    只輸出 skill 規定的 JSON。"""
            messages = self.build_direct_messages(task, context=context)
            try:
                raw = (
                    self.chat_with_tools(
                        messages,
                        max_rounds=tool_rounds,
                        active_skill="domain-research",
                    )
                    if self.tools
                    else self.model.chat(messages)
                )
                result = self.parse_first_json(raw)
                if not result:
                    result = {"findings": [(raw or "")]}
                result.setdefault("binding_obligations", [])
                result.setdefault("risk_notes", [])
                result.setdefault("recommendations", [])
                if not isinstance(result.get("derived_requirements"), list):
                    result["derived_requirements"] = []
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
            existing = artifact.get("feedback", {}).get("domain_research", {})
            context = {
                "research_results": research_results,
                "existing_research": existing,
            }
            task = """綜合 Context.research_results 與 Context.existing_research，依 `domain-research` skill 輸出合併後的研究資料。

    執行邊界：
    - 合併 findings、sources、derived_requirements、compliance_risks。
    - derived_requirements 可保留來自研究結果中有明確依據的候選 requirement。
    - 不得捏造來源、法規、數值門檻或研究結論。
    - 若 existing_research 與 research_results 有重複內容，請合併去重並保留較完整、較可追溯的版本。

    只輸出一個 JSON，鍵名為 `domain_research`。

    建議 JSON shape：
    {
      "domain_research": {
    "findings": ["..."],
    "sources": ["..."],
    "derived_requirements": [
      {"text": "...", "source": "...", "category": "regulatory|best_practice|safety"}
    ],
    "compliance_risks": ["..."]
      }
    }"""
            try:
                raw = self.invoke_skill("domain-research", task, context=context)
                result = self.parse_first_json(raw)
                dr = result.get("domain_research") or result
                if isinstance(dr, dict) and dr:
                    dr.setdefault("findings", [])
                    dr.setdefault("sources", [])
                    dr.setdefault("derived_requirements", [])
                    dr.setdefault("compliance_risks", [])
                    artifact.setdefault("feedback", {})["domain_research"] = dr
                    obs["summary"] = "已更新領域研究資料"
                else:
                    obs["error"] = "解析失敗"
                    obs["summary"] = "更新失敗：解析錯誤"
            except Exception as e:
                obs["error"] = str(e)
                obs["summary"] = f"更新失敗: {e}"
            return obs

        if action == "flag_compliance_risk":
            desc = (params.get("description") or "").strip()
            if not desc:
                obs["error"] = "description 為空"
                return obs
            pending_issues.append({
                "type": "compliance_risk",
                "description": desc,
                "source": "expert",
            })
            obs["summary"] = f"已標記合規風險: {desc}"
            return obs

        obs["error"] = f"未知動作: {action}"
        return obs

    def decide_next_domain_research_action(self, state, last_observation=None):
        state_text = json.dumps(state, ensure_ascii=False, indent=2)
        obs_text = json.dumps(last_observation or {}, ensure_ascii=False, indent=2)

        tools_hint = ""
        if state.get("available_tools"):
            tools_hint = (
                "\n- research_topic 執行時可自動使用工具："
                + ", ".join(state["available_tools"])
            )

        tool_max = self.tool_call_max_rounds
        web_cap = self.max_web_search_results_cap()
        sr_current = int(state.get("max_iterations") or 1)

        user_prompt = f"""# 任務
    你是領域專家。根據當前狀態與上一步結果，選下一個動作。

    # 動作
    - research_topic：{{"query":"具體研究問題","max_tool_rounds":"選填 1-{tool_max}"}}；web_search 可帶 max_results=1-{web_cap}{tools_hint}
    - update_findings：把已足夠的研究結果寫回 artifact
    - flag_compliance_risk：{{"description":"風險描述"}}
    - done：結束

    # 當前狀態
    {state_text}

    # 上一步結果
    {obs_text}

    # 規則
    - 第一輪可選填 max_iterations=1-{sr_current}；不填就沿用 {sr_current}
    - 有法規、標準、安全、合規議題：優先 research_topic
    - 每次 research_topic 只聚焦一個具體問題
    - 工具使用順序：先 artifact_query 查專案內部狀態；若需讀本地文件再用 file_parser；只有內部狀態與 doc/ 都不足時，才用 web_search 補外部證據
    - 不可用 web_search 覆蓋 artifact 中已存在的 requirements、decisions、conflicts、open_questions 或 scope 事實
    - 需要先看 requirements/conflicts/decisions/open_questions 時，先用 artifact_query
    - artifact_query 例子：
      - {{"mode":"summarize","section":"requirements"}}
      - {{"mode":"get_section","section":"conflicts","compact":true}}
      - {{"mode":"related_context","item_id":"CF-01","compact":true}}
      - {{"mode":"find_items","section":"open_questions","filters":{{"status":"pending"}},"compact":true}}
    - 若有 file_parser：優先 search_chunks → read_chunks；只有已知單一短文件或真的需要全文時才 read_full
    - web_search 只用於補法規、標準、最佳實務、官方文件或外部風險來源；避免廣泛探索式搜尋
    - 有足夠材料才 update_findings
    - 有重大合規風險就 flag_compliance_risk
    - 無需再研究就選 done
    - {short_reasoning_line()}

    # 輸出 JSON
    {{
      "action": "動作名稱",
      "params": {{}},
      "reasoning": "一句說明",
      "max_iterations": "選填；僅第一輪有效，數字 1-{sr_current}"
    }}"""

        messages = self.build_direct_messages(user_prompt)
        try:
            if "artifact_query" in self.tools:
                raw = self.chat_with_tools(messages, max_rounds=self.tool_call_max_rounds)
                response = self.parse_topic_response_json(raw)
            else:
                response = self.chat_json(messages)
        except Exception as e:
            self.logger.warning(f"Expert domain research 決策失敗: {e}")
            return {"action": "done", "params": {}, "reasoning": f"fallback: {e}"}
        if not isinstance(response, dict):
            self.logger.warning("Expert domain research 格式異常（%s）", type(response).__name__)
            return {
                "action": "done",
                "params": {},
                "reasoning": "fallback: invalid response format",
            }

        action = (response.get("action") or "").strip()
        if action not in EXPERT_DOMAIN_RESEARCH_ACTIONS:
            action = "done"
        out = {
            "action": action,
            "params": response.get("params") or {},
            "reasoning": response.get("reasoning", ""),
        }
        if "max_iterations" in response:
            out["max_iterations"] = response["max_iterations"]
        return out
