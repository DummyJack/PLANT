# Expert domain research: optional skill context plus evidence gathering loop.
import json
from typing import Dict, Optional

from agents.profile.analyst.requirements import requirement_discussion_pool

from .validation import domain_research_payload, research_result_payload


EXPERT_DOMAIN_RESEARCH_ACTIONS = [
    "research_issue",
    "update_findings",
    "flag_compliance_risk",
    "done",
]


class ExpertDomainResearch:
    def get_optional_skill_context(
        self, issue: Dict, artifact_snapshot: Optional[Dict]
    ) -> Optional[str]:
        return super().get_optional_skill_context(issue, artifact_snapshot)

    def run_domain_research_loop(self, artifact, recent_discussions=None):
        """Expert domain research 走共用 OPA loop；研究結果透過 context 傳遞，必要時在單輪內保證寫回 findings。"""
        loop_cap = self.agent_loop_round_cap()
        result = self.run_action_loop(
            name="domain_research",
            max_iterations=3,
            loop_cap=loop_cap,
            context={
                "artifact": artifact,
                "recent_discussions": recent_discussions,
                "research_results": [],
                "pending_issues": [],
                "force_update_after_research": False,
            },
            build_observation=self.build_domain_research_observation,
            decide_action=self.decide_domain_research_action,
            execute_action=self.execute_domain_research_loop_action,
        )
        if (
            isinstance(result, dict)
            and not (artifact.get("feedback", {}) or {}).get("domain_research")
            and result.get("opa_trace")
        ):
            research_results = [
                row.get("result")
                for row in result.get("opa_trace", [])
                if isinstance(row, dict)
                and isinstance(row.get("result"), dict)
                and row.get("result", {}).get("action") == "research_issue"
                and isinstance(row.get("result", {}).get("result"), dict)
            ]
            research_results = [row for row in research_results if isinstance(row, dict)]
            if research_results:
                merged = domain_research_payload(
                    {
                        "findings": [
                            item
                            for row in research_results
                            for item in (row.get("findings") or [])
                        ],
                        "sources": [
                            item
                            for row in research_results
                            for item in (row.get("sources") or [])
                        ],
                        "derived_requirements": [
                            item
                            for row in research_results
                            for item in (row.get("derived_requirements") or [])
                        ],
                        "binding_obligations": [
                            item
                            for row in research_results
                            for item in (row.get("binding_obligations") or [])
                        ],
                        "risk_notes": [
                            item
                            for row in research_results
                            for item in (row.get("risk_notes") or [])
                        ],
                        "recommendations": [
                            item
                            for row in research_results
                            for item in (row.get("recommendations") or [])
                        ],
                    }
                )
                if merged:
                    artifact.setdefault("feedback", {})["domain_research"] = merged
        return result

    def build_domain_research_state(
        self, artifact, recent_discussions, actions_taken,
        research_results, iteration, max_iterations,
    ):
        reqs = requirement_discussion_pool(artifact)
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
            issue = disc.get("issue", {})
            resolution = disc.get("resolution", {})
            disc_summaries.append({
                "issue_id": issue.get("id"),
                "title": issue.get("title"),
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

        if action == "research_issue":
            query = params.get("query", "")
            if not query:
                obs["error"] = "query 參數為空"
                obs["summary"] = "研究失敗：未提供研究問題"
                return obs
            context = {
                "project_overview": (artifact.get("scope") or {}).get(
                    "description", ""
                ),
            }
            task = f"""針對以下問題進行領域研究：{query}

    請依 `domain-research` skill 的最新 evidence-first contract 執行研究並輸出 JSON。

    執行邊界：
    - 需要證據時可使用本輪 Tool Context 中允許的工具。
    - 研究結果預設作為 evidence，不直接形成正式 requirement。
    - 僅當外部來源構成明確、可追溯、具約束力的 obligation 時，才可產生 derived requirement candidates。
    - 不可把最佳實務、一般建議或風險提醒直接升格成 requirement。

    只輸出 skill 規定的 JSON。"""
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
                result = research_result_payload(self.parse_first_json(raw))
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
    - 合併 findings、sources、derived_requirements、compliance_risks、recommendations、gaps_for_further_research。
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
    "compliance_risks": ["..."],
    "recommendations": ["..."],
    "gaps_for_further_research": ["..."]
      }
    }"""
            try:
                raw = self.invoke_skill("domain-research", task, context=context)
                dr = domain_research_payload(self.parse_first_json(raw))
                if dr:
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

        user_prompt = f"""# 任務
    根據當前狀態與上一步結果，選下一個動作。

    # 動作
    - research_issue：{{"query":"具體研究問題"}}
    - update_findings：把已足夠的研究結果寫回 artifact
    - flag_compliance_risk：{{"description":"風險描述"}}
    - done：結束

    # 當前狀態
    {state_text}

    # 上一步結果
    {obs_text}

    # 規則
    - 只有當 artifact 內證據不足，且外部資料會影響 requirement、constraint、risk 或 acceptance boundary 判斷時，才選 research_issue
    - 若只是一般產品需求、一般流程問題、優先級取捨或已可由 artifact 判斷的內容，不要查外部資料
    - 每次 research_issue 只聚焦一個具體問題
    - 工具使用邊界遵守本輪 Tool Context
    - 有足夠材料才 update_findings
    - 有重大合規風險就 flag_compliance_risk
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
                raw = self.chat_with_tools(messages)
                response = self.parse_issue_response_json(raw)
            else:
                response = self.chat_json(messages)
        except Exception as e:
            raise RuntimeError(f"Expert domain research 決策輸出格式不合格: {e}") from e
        if not isinstance(response, dict):
            raise ValueError(f"Expert domain research 決策必須是 JSON object，收到 {type(response).__name__}")

        action = (response.get("action") or "").strip()
        if action not in EXPERT_DOMAIN_RESEARCH_ACTIONS:
            raise ValueError(f"Expert domain research action 不合法: {action or '<empty>'}")
        out = {
            "action": action,
            "params": response.get("params") or {},
            "reasoning": response.get("reasoning", ""),
        }
        return out
