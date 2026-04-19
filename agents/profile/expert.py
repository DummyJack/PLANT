import json
from typing import Dict, List, Optional, Any
from pathlib import Path

from agents.base import BaseAgent
from utils import (
    current_output_language,
    expert_fallback_viewpoint,
    expert_topic_bullets_task,
    short_reasoning_line,
)

# 與 FileParserTool 支援的副檔名一致（供 flow 組裝工具時判斷）
DOC_SUPPORTED_SUFFIXES = (".txt", ".md", ".json", ".pdf", ".docx", ".doc")


def has_supported_doc_files(doc_dir: Path) -> bool:
    """檢查 doc 目錄下是否至少有一個支援的檔案（含子目錄）。"""
    if not doc_dir.is_dir():
        return False
    for p in doc_dir.rglob("*"):
        if p.is_file() and p.suffix.lower() in DOC_SUPPORTED_SUFFIXES:
            return True
    return False


EXPERT_REVIEW_ACTIONS = [
    "research_topic",
    "update_findings",
    "flag_compliance_risk",
    "done",
]


class ExpertAgent(BaseAgent):
    """領域專家 Agent — 賦予 domain-research skill，可搭配 file_parser 等工具。"""

    name = "expert"

    system_prompt = """你是領域專家，負責把外部法規、標準與安全約束轉成可用的限制與風險資訊。

規則：
1. 你提供的是證據、限制、風險與適用範圍，不負責決定產品 scope、優先級或最終需求 wording。
2. 強制義務、最佳實務與建議必須分開表達；證據不足時要明講。
3. 只有在合規風險、證據缺口或標準衝突明確時，才主張升級討論。"""

    def __init__(
        self,
        model,
        tools: Optional[list] = None,
        registry=None,
        doc_dir: str = "doc",
        project_config=None,
    ):
        self.doc_dir = Path(doc_dir)
        self.doc_dir.mkdir(parents=True, exist_ok=True)
        super().__init__(
            model,
            tools=tools or [],
            registry=registry,
            skill_names=["domain-research"],
            project_config=project_config,
        )

    # ===== Monitor =====

    def run_review_loop(self, artifact, recent_discussions=None, *, max_iterations):
        """Expert review 走共用 OPA loop；研究結果透過 context 傳遞，必要時在單輪內保證寫回 findings。"""
        loop_cap = max(self.self_review_round_cap(), 2)
        effective_max = min(max_iterations, self.self_review_round_cap())
        internal_max = 2 if effective_max == 1 else effective_max
        result = self.run_opa_loop(
            mode="review",
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
        )
        return result

    def build_review_state(
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

    def execute_review_action(
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

    # ===== Plan =====

    def decide_next_review_action(self, state, last_observation=None):
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
                response = self.model.chat_json(messages)
        except Exception as e:
            self.logger.warning(f"Expert review 決策失敗: {e}")
            return {"action": "done", "params": {}, "reasoning": f"fallback: {e}"}
        if not isinstance(response, dict):
            self.logger.warning("Expert review 格式異常（%s）", type(response).__name__)
            return {
                "action": "done",
                "params": {},
                "reasoning": "fallback: invalid response format",
            }

        action = (response.get("action") or "").strip()
        if action not in EXPERT_REVIEW_ACTIONS:
            action = "done"
        out = {
            "action": action,
            "params": response.get("params") or {},
            "reasoning": response.get("reasoning", ""),
        }
        if "max_iterations" in response:
            out["max_iterations"] = response["max_iterations"]
        return out

    # ===== Plan: topic proposal =====

    def propose_topics(
        self,
        artifact: Dict[str, Any],
        *,
        round_num: int,
        max_items: int = 2,
    ) -> List[Dict]:
        proposals: List[Dict] = []
        research = ((artifact.get("feedback") or {}).get("domain_research") or {})
        for dr in research.get("binding_obligations", []) or []:
            text = (dr.get("text") or "").strip()
            if not text:
                continue
            rid = (dr.get("id") or "").strip()
            proposals.append(
                {
                    "title": text,
                    "description": text,
                    "category": "new_requirement",
                    "participants": ["expert", "analyst", "user", "modeler"],
                    "discussion_mode": "sequential",
                    "speaking_order": ["expert", "analyst", "user", "modeler"],
                    "source_ids": [rid] if rid else [],
                    "priority_hint": "high",
                    "impact_level": "high",
                    "why_now": "此議題涉及明確外部義務或具約束力條件，值得由會議確認其適用範圍與需求影響。",
                    "proposed_by": "expert",
                    "round": round_num,
                }
            )

        for oq in artifact.get("open_questions", []):
            if oq.get("status") == "answered":
                continue
            if (oq.get("type") or "") != "compliance_risk":
                continue
            proposals.append(
                {
                    "title": "合規風險開放問題釐清",
                    "description": (oq.get("question") or "").strip(),
                    "category": "open_question",
                    "participants": ["expert", "analyst", "user"],
                    "discussion_mode": "simultaneous",
                    "speaking_order": ["expert", "analyst", "user"],
                    "source_ids": [],
                    "priority_hint": "high",
                    "impact_level": "high",
                    "why_now": "合規風險未釐清會影響需求可行性。",
                    "proposed_by": "expert",
                    "round": round_num,
                }
            )

        return proposals[: max(1, max_items)]

    # ===== Action: domain-research =====

    def provide_domain_knowledge(
        self,
        requirements: List[Dict],
        conflicts: List[Dict],
        project_overview: str = "",
    ) -> Dict:
        """Phase 0: 提供領域知識。依 domain-research skill 的 Research Results 格式產出，結果寫入 artifact.feedback.domain_research，不修改 requirements。"""
        project_overview = (project_overview or "").strip()
        context = {
            "project_overview": project_overview,
            "requirements": requirements,
            "conflicts": conflicts,
        }
        doc_hint = ""
        if self.has_doc_reference_files():
            doc_hint = (
                "工具使用順序：先 artifact_query 查專案內部事實，再用 file_parser 讀 doc/，最後才用 web_search 補外部證據。"
                "若有 file_parser 工具：建議先 action=search_chunks 檢索 doc/，再 action=read_chunks 讀回片段後綜合；只有已知檔名且確實需要全文時才 action=read_full。"
            )
        task = f"""依 `domain-research` skill 執行研究，根據 Context 產出 evidence-first 研究結果。
{doc_hint}

執行邊界：
- 研究結果只作為 evidence 與背景知識，不直接改寫 requirements。
- 只在明確 binding obligation 存在時，才可產生 derived requirement candidates。
- 若僅屬最佳實務、一般建議或風險提醒，應留在 recommendations / risk_notes。

只輸出一個 JSON 物件，鍵名為 `research_session`。"""
        raw = self.invoke_skill("domain-research", task, context=context)
        response = self.parse_first_json(raw or "")
        research_session = response.get("research_session")
        if isinstance(research_session, dict):
            research_session.setdefault("binding_obligations", [])
            research_session.setdefault("risk_notes", [])
            research_session.setdefault("recommendations", [])
            if not isinstance(research_session.get("derived_requirements"), list):
                research_session["derived_requirements"] = []
        elif isinstance(response, dict) and (
            response.get("findings") or response.get("derived_requirements")
        ):
            # skill 有時直接回傳 research 內容於頂層
            research_session = response
        else:
            research_session = {}
        if isinstance(research_session, dict) and research_session:
            research_session.setdefault("binding_obligations", [])
            research_session.setdefault("risk_notes", [])
            research_session.setdefault("recommendations", [])
            if not isinstance(research_session.get("derived_requirements"), list):
                research_session["derived_requirements"] = []
        if not research_session:
            self.logger.warning("domain-research 未產出 research_session")
        return {"feedback": {"domain_research": research_session}}

    # ===== Action: meeting response =====

    def get_optional_skill_context(
        self, topic: Dict, artifact_snapshot: Optional[Dict]
    ) -> Optional[str]:
        """議題涉及 Conflict 協調或 NFR 取捨時，觸發 domain-research 產出簡短要點供發言參考。"""
        if topic.get("category") not in (
            "conflict_discussion", "tradeoff"
        ):
            return None
        if "domain-research" not in self.skill_names:
            return None
        context = {"topic": topic, "artifact_snapshot": artifact_snapshot or {}}
        task = expert_topic_bullets_task()
        try:
            raw = self.invoke_skill("domain-research", task, context=context)
            return (raw or "").strip()
        except Exception as e:
            self.logger.debug("議程中觸發 domain-research 失敗: %s", e)
            return None

    def build_observation(self, *, mode: str, **kwargs: Any) -> Dict[str, Any]:
        if mode == "review":
            return self.build_review_state(
                kwargs["artifact"],
                kwargs.get("recent_discussions"),
                kwargs.get("actions_taken", []),
                kwargs.get("research_results", []),
                kwargs.get("iteration", 0),
                kwargs.get("max_iterations", 1),
            )
        if mode == "topic_response":
            topic = kwargs["topic"]
            previous_responses = kwargs.get("previous_responses") or []
            artifact_snapshot = kwargs.get("artifact_snapshot") or {}
            return {
                "topic": topic,
                "topic_id": str(topic.get("id") or ""),
                "topic_category": str(topic.get("category") or ""),
                "previous_responses": previous_responses,
                "previous_response_count": len(previous_responses),
                "artifact_snapshot": artifact_snapshot,
                "has_artifact_snapshot": bool(artifact_snapshot),
                "recent_ask_history": topic.get("recent_ask_history") or [],
                "collector_mode": bool(topic.get("collector_mode")),
                "asker_agent": str(topic.get("asker_agent") or "").strip(),
                "iteration": kwargs.get("iteration", 0) + 1,
                "max_iterations": kwargs.get("max_iterations", 1),
            }
        return super().build_observation(mode=mode, **kwargs)

    def decide_action(
        self,
        *,
        mode: str,
        observation: Dict[str, Any],
        last_result: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        if mode == "topic_response":
            topic = observation.get("topic") or {}
            topic_id = str(topic.get("id") or "")
            if topic.get("category") == "conflict_discussion":
                action = "respond_conflict_discussion"
            elif topic_id.startswith("ELICIT-") and topic.get("collector_mode"):
                action = "propose_elicitation_question"
            elif topic_id.startswith("ELICIT-") and str(topic.get("asker_agent") or "").strip() == self.name:
                action = "ask_elicitation_question"
            else:
                action = "respond_discussion"
            return {
                "action": action,
                "params": {},
                "reasoning": "根據議題類型選擇對應的單輪專家回應策略。",
            }
        if mode == "review":
            if kwargs.get("force_update_after_research"):
                last = last_result or {}
                if (
                    last.get("action") == "research_topic"
                    and kwargs.get("research_results")
                ):
                    return {
                        "action": "update_findings",
                        "params": {},
                        "reasoning": "單輪 review 已完成研究，補跑 update_findings 寫回結果。",
                    }
            return self.decide_next_review_action(observation, last_result)
        return super().decide_action(
            mode=mode,
            observation=observation,
            last_result=last_result,
            **kwargs,
        )

    def execute_action(
        self,
        *,
        mode: str,
        decision: Dict[str, Any],
        observation: Dict[str, Any],
        **kwargs: Any,
    ) -> Dict[str, Any]:
        if mode == "review":
            return self.execute_review_action(
                decision.get("action", "done"),
                decision.get("params") or {},
                kwargs["artifact"],
                kwargs.get("pending_issues", []),
                kwargs.get("research_results", []),
            )
        return super().execute_action(
            mode=mode,
            decision=decision,
            observation=observation,
            **kwargs,
        )

    def _build_topic_response_prompt(
        self,
        *,
        topic: Dict[str, Any],
        previous_responses: Optional[List[Dict[str, Any]]],
        artifact_snapshot: Optional[Dict[str, Any]],
    ) -> str:
        topic_text = f"議題 [{topic.get('id', '')}]: {topic.get('title', '')}\n描述: {topic.get('description', '')}"
        topic_id = str(topic.get("id") or "")

        prev_text = ""
        if previous_responses:
            parts = [
                f"【{r.get('agent', '?')}】\n{r.get('response', {}).get('statement', '')}"
                for r in previous_responses
            ]
            prev_text = "\n前面的發言:\n" + "\n\n".join(parts)

        snapshot_text = ""
        if artifact_snapshot:
            snapshot_text = f"\n# 當前專案狀態（供參考）\n{json.dumps(artifact_snapshot, ensure_ascii=False, indent=2)}"

        recent_ask_history_text = ""
        recent_ask_history = topic.get("recent_ask_history") or []
        if recent_ask_history:
            recent_ask_history_text = (
                "\n# 最近幾輪正式提問摘要\n"
                + json.dumps(recent_ask_history, ensure_ascii=False, indent=2)
            )

        skill_section = ""
        skill_context = self.get_optional_skill_context(topic, artifact_snapshot)
        if skill_context:
            skill_section = f"\n# Skill 參考（本輪依議題類型觸發）\n{skill_context}\n"
        category = (topic.get("category") or "").strip()
        allow_suggested_next_action = (
            category != "conflict_discussion"
            and not topic_id.startswith("ELICIT-")
        )

        tool_hint = ""
        if self.tools:
            fp_line = ""
            if self.has_doc_reference_files():
                fp_line = (
                    "- file_parser：先 search_chunks → read_chunks 再綜合；只有確實需要全文時才 read_full。\n"
                )
            tool_hint = (
                "\n# 工具使用\n"
                "- 先用 artifact_query 查 requirements、conflicts、decisions、open_questions 等專案內部事實。\n"
                f"{fp_line}"
                "- web_search 只用來補外部法規、標準、最佳實務或官方文件，不可覆蓋 artifact 內已知事實。\n"
                "- 最後**必須**輸出下列 JSON。"
            )

        if category == "conflict_discussion":
            category_hint = """# 本議題特別要求（conflict_discussion）
- 你的任務是逐筆再審查目前這批 Conflict/Neutral pairs，而不是重新定義需求。
- 你必須先根據 requirement_a / requirement_b 原文獨立重判，再與 current_label 比較決定 keep 或 modify。
- statement 必須是單一合法 JSON object 字串；不可輸出 JSON 以外的前後文。
- statement JSON 結構必須為：{"overall_assessment":"...","pair_reviews":[...]}。
- pair_reviews 必須逐筆涵蓋每個 [PAIR-xxx]；每筆都要有：id、independent_label、decision、proposed_label、confidence、reason。
- 只有在外部規範、品質底線、權限或安全限制使兩項需求無法同時成立時，才支持 Conflict。
- 只有在兩項需求可明確判定為不衝突、不重複，且沒有直接語義關係時，才支持 Neutral。
- 若兩項需求描述同一功能範圍、同一流程、同一資料處理或同一輸出行為，即表示存在直接語義關係；不能僅因兩者可共存就判為 Neutral。
- 若一項需求是另一項的子集、細化、補充步驟或同流程的相鄰行為，不能直接判為 Neutral。
- 若只是一般 tradeoff、偏好差異、尚未補齊限制條件，或目前僅缺外部證據，不能因看不出衝突就直接支持 Neutral。
- 請明確指出：是哪一條限制、法規、標準或品質邊界造成互斥；若支持 Neutral，請說明為何兩項需求既不衝突、也不重複，且無直接語義關係。"""
        elif category == "tradeoff":
            category_hint = """# 本議題特別要求（tradeoff）
- 優先說明不可同時滿足的限制、你最重視的評估準則，以及合規前提下可接受的折衷範圍。"""
        elif category == "open_question":
            category_hint = """# 本議題特別要求（open_question）
- 優先回答目前能直接確認的事實與限制；若仍需補資料，明確指出缺口與最適合回答的角色。"""
        elif category == "new_requirement":
            category_hint = """# 本議題特別要求（new_requirement）
- 優先說明此新增需求是否屬於法規義務、最佳實務或風險緩解措施，以及若納入會影響哪些既有邊界。"""
        else:
            category_hint = ""

        statement_contract = """# statement 結構要求
- statement 雖然是自然語句，但內容必須至少涵蓋：立場或暫時結論、依據或情境、風險/限制/邊界、建議下一步。
- statement 不得只表態，必須有依據。
- statement 不得宣告最終決議已成立；你只能提出觀點、依據、風險與建議。"""

        open_question_contract = """# open_questions 規範
- 只有在你無法根據目前資料合理完成判斷，且該問題確實應由其他角色回答時，才產生 open_questions。
- 每一筆 open_question 只能問一件事，問題要具體、可回答。
- 不得把建議、命令或最終結論偽裝成問題。
- 若你自己可根據現有資料回答，就不要丟 open_questions。
- 若沒有真正需要他人回答的問題，open_questions 請輸出空陣列。"""
        next_action_contract = ""
        if allow_suggested_next_action:
            next_action_contract = """# suggested_next_action 規範
- 若你認為本議題討論結束後應由外層流程安排下一步，可額外提供 suggested_next_action。
- suggested_next_action 只是會後建議，不會在會議中直接執行。
- 建議格式：type、reason、target_ids、urgency。若無明確建議可省略或填 null。"""

        elicitation_hint = ""
        task_block = "請以領域專家身分發言，聚焦法規、標準、證據、限制與風險。"
        rules_block = """- statement 需包含：暫時結論、依據、風險/限制、建議下一步。
- 若屬強制義務要明講；若只是最佳實務或待補證據也要明講。
- 可引用 requirement id、conflict id、研究發現或來源線索。
- 若資訊不足，明確指出 evidence gap；不要虛構法規或標準。
- 不決定產品 scope、優先級或最終需求 wording。
- 可用純文字表格或流程輔助；若使用，請放在程式碼區塊。"""
        if topic_id.startswith("ELICIT-") and topic.get("collector_mode"):
            elicitation_hint = """# ELICIT Collector（Expert）
- 你不是本輪正式提問者。
- 你的任務是替 asker 找出現在最值得問 user 的一個限制或品質需求缺口。
- 優先補核心限制與品質要求；若核心功能與範圍仍不清楚，不要先追後段合規細節。
- 若沒有高價值的新限制/品質問題，要明講。"""
            task_block = "請以領域 collector 身分，輸出一段提問建議，供 asker 整合成正式主問題。"
            rules_block = """- 不要直接對 user 正式發問。
- statement 需包含：需求缺口、建議問題句、為何值得問、如何避免重複。
- 建議問題句只能有 1 個主問題，且要能直接轉成 quality requirement 或 constraint。
- open_questions 請輸出空陣列。"""
        elif topic_id.startswith("ELICIT-") and str(topic.get("asker_agent") or "").strip() == self.name:
            stop_phrase = (
                "I have gathered enough information"
                if current_output_language() == "en"
                else "我已蒐集足夠資訊"
            )
            elicitation_hint = """# ELICIT Asker（Expert）
- 你是本輪唯一正式提問者。
- 你的任務是根據前面 collectors 的提問建議，整合成對 user 的唯一主問題。
- 優先補限制、品質要求、外部約束與介面品質偏好等核心缺口。
- 若核心功能與內容範圍仍不清楚，不要優先追問深層合規、稽核、保存、刪除等後段議題。
- 若 collectors 提出的方向過深或過硬，改寫成 user 能直接回答的一題。"""
            task_block = (
                "請以領域 interviewer 身分，只輸出對 user 的一個正式主問題（1-3 句）；"
                "若你判斷目前已蒐集到足夠資訊、可以收束本輪需求挖掘，則 statement 請只輸出以下固定句"
                f"（勿加引號、勿改寫、勿額外說明）：{stop_phrase}"
            )
            rules_block = f"""- 若你判斷目前資訊已足以支撐核心需求理解，且再往下追問的增益有限，可直接輸出停止句：{stop_phrase}
- 若關鍵限制、品質要求、權限/安全邊界、介面品質偏好、外部約束仍未釐清，不可停止。
- 若選擇提問，只能問 1 個主問題，不可合併多題。
- 問題必須可回答、可抽取、可直接轉成 quality requirement 或 constraint。
- open_questions 請輸出空陣列。"""
        suggested_next_action_json = ""
        if allow_suggested_next_action:
            suggested_next_action_json = """,
    "suggested_next_action": {
        "type": "analyst_review | expert_review | modeler_review | direct_clarification | new_topic",
        "reason": "為何建議會後安排這一步",
        "target_ids": ["可選，相關 requirement/conflict/topic id"],
        "urgency": "low | medium | high"
    }"""
        return f"""{topic_text}
{prev_text}
{snapshot_text}
{recent_ask_history_text}
{skill_section}
{tool_hint}
{category_hint}
{elicitation_hint}

{statement_contract}

{open_question_contract}

{next_action_contract}

# 任務
{task_block}

# 規則
{rules_block}

# 輸出 JSON
{{{{
    "statement": "針對此議題的完整發言內容（含法規依據與風險說明）",
    "open_questions": [{{{{"to": "目標 agent 名稱", "question": "問題"}}}}]{suggested_next_action_json}
}}}}"""

    def respond_to_conflict_topic(self, topic, previous_responses=None, artifact_snapshot=None):
        topic_text = f"議題 [{topic.get('id', '')}]: {topic.get('title', '')}\n描述: {topic.get('description', '')}"
        topic_id = str(topic.get("id") or "")

        prev_text = ""
        if previous_responses:
            parts = [
                f"【{r.get('agent', '?')}】\n{r.get('response', {}).get('statement', '')}"
                for r in previous_responses
            ]
            prev_text = "\n前面的發言:\n" + "\n\n".join(parts)

        snapshot_text = ""
        if artifact_snapshot:
            snapshot_text = f"\n# 當前專案狀態（供參考）\n{json.dumps(artifact_snapshot, ensure_ascii=False, indent=2)}"

        recent_ask_history_text = ""
        recent_ask_history = topic.get("recent_ask_history") or []
        if recent_ask_history:
            recent_ask_history_text = (
                "\n# 最近幾輪正式提問摘要\n"
                + json.dumps(recent_ask_history, ensure_ascii=False, indent=2)
            )

        skill_section = ""
        skill_context = self.get_optional_skill_context(topic, artifact_snapshot)
        if skill_context:
            skill_section = f"\n# Skill 參考（本輪依議題類型觸發）\n{skill_context}\n"

        tool_hint = ""
        if self.tools:
            fp_line = ""
            if self.has_doc_reference_files():
                fp_line = (
                    "- file_parser：先 search_chunks → read_chunks 再綜合；只有確實需要全文時才 read_full。\n"
                )
            tool_hint = (
                "\n# 工具使用\n"
                "- 先用 artifact_query 查 requirements、conflicts、decisions、open_questions 等專案內部事實。\n"
                f"{fp_line}"
                "- web_search 只用來補外部法規、標準、最佳實務或官方文件，不可覆蓋 artifact 內已知事實。\n"
                "- 最後**必須**輸出下列 JSON。"
            )

        category = (topic.get("category") or "").strip()
        if category == "conflict_discussion":
            category_hint = """# 本議題特別要求（conflict_discussion）
- 你的任務是逐筆再審查目前這批 Conflict/Neutral pairs，而不是重新定義需求。
- 你必須先根據 requirement_a / requirement_b 原文獨立重判，再與 current_label 比較決定 keep 或 modify。
- statement 必須是單一合法 JSON object 字串；不可輸出 JSON 以外的前後文。
- statement JSON 結構必須為：{"overall_assessment":"...","pair_reviews":[...]}。
- pair_reviews 必須逐筆涵蓋每個 [PAIR-xxx]；每筆都要有：id、independent_label、decision、proposed_label、confidence、reason。
- 只有在外部規範、品質底線、權限或安全限制使兩項需求無法同時成立時，才支持 Conflict。
- 只有在兩項需求可明確判定為不衝突、不重複，且沒有直接語義關係時，才支持 Neutral。
- 若兩項需求描述同一功能範圍、同一流程、同一資料處理或同一輸出行為，即表示存在直接語義關係；不能僅因兩者可共存就判為 Neutral。
- 若一項需求是另一項的子集、細化、補充步驟或同流程的相鄰行為，不能直接判為 Neutral。
- 若只是一般 tradeoff、偏好差異、尚未補齊限制條件，或目前僅缺外部證據，不能因看不出衝突就直接支持 Neutral。
- 請明確指出：是哪一條限制、法規、標準或品質邊界造成互斥；若支持 Neutral，請說明為何兩項需求既不衝突、也不重複，且無直接語義關係。"""
        elif category == "tradeoff":
            category_hint = """# 本議題特別要求（tradeoff）
- 優先說明不可同時滿足的限制、你最重視的評估準則，以及合規前提下可接受的折衷範圍。"""
        elif category == "open_question":
            category_hint = """# 本議題特別要求（open_question）
- 優先回答目前能直接確認的事實與限制；若仍需補資料，明確指出缺口與最適合回答的角色。"""
        elif category == "new_requirement":
            category_hint = """# 本議題特別要求（new_requirement）
- 優先說明此新增需求是否屬於法規義務、最佳實務或風險緩解措施，以及若納入會影響哪些既有邊界。"""
        else:
            category_hint = ""

        statement_contract = """# statement 結構要求
- statement 雖然是自然語句，但內容必須至少涵蓋：立場或暫時結論、依據或情境、風險/限制/邊界、建議下一步。
- statement 不得只表態，必須有依據。
- statement 不得宣告最終決議已成立；你只能提出觀點、依據、風險與建議。"""

        open_question_contract = """# open_questions 規範
- 只有在你無法根據目前資料合理完成判斷，且該問題確實應由其他角色回答時，才產生 open_questions。
- 每一筆 open_question 只能問一件事，問題要具體、可回答。
- 不得把建議、命令或最終結論偽裝成問題。
- 若你自己可根據現有資料回答，就不要丟 open_questions。
- 若沒有真正需要他人回答的問題，open_questions 請輸出空陣列。"""

        elicitation_hint = ""
        task_block = "請以領域專家身分發言，聚焦法規、標準、證據、限制與風險。"
        rules_block = """- statement 需包含：暫時結論、依據、風險/限制、建議下一步。
- 若屬強制義務要明講；若只是最佳實務或待補證據也要明講。
- 可引用 requirement id、conflict id、研究發現或來源線索。
- 若資訊不足，明確指出 evidence gap；不要虛構法規或標準。
- 不決定產品 scope、優先級或最終需求 wording。
- 可用純文字表格或流程輔助；若使用，請放在程式碼區塊。"""
        if topic_id.startswith("ELICIT-") and topic.get("collector_mode"):
            elicitation_hint = """# ELICIT Collector（Expert）
- 你不是本輪正式提問者。
- 你的任務是替 asker 找出現在最值得問 user 的一個限制或品質需求缺口。
- 優先補核心限制與品質要求；若核心功能與範圍仍不清楚，不要先追後段合規細節。
- 若沒有高價值的新限制/品質問題，要明講。"""
            task_block = "請以領域 collector 身分，輸出一段提問建議，供 asker 整合成正式主問題。"
            rules_block = """- 不要直接對 user 正式發問。
- statement 需包含：需求缺口、建議問題句、為何值得問、如何避免重複。
- 建議問題句只能有 1 個主問題，且要能直接轉成 quality requirement 或 constraint。
- open_questions 請輸出空陣列。"""
        elif topic_id.startswith("ELICIT-") and str(topic.get("asker_agent") or "").strip() == self.name:
            stop_phrase = (
                "I have gathered enough information"
                if current_output_language() == "en"
                else "我已蒐集足夠資訊"
            )
            elicitation_hint = """# ELICIT Asker（Expert）
- 你是本輪唯一正式提問者。
- 你的任務是根據前面 collectors 的提問建議，整合成對 user 的唯一主問題。
- 優先補限制、品質要求、外部約束與介面品質偏好等核心缺口。
- 若核心功能與內容範圍仍不清楚，不要優先追問深層合規、稽核、保存、刪除等後段議題。
- 若 collectors 提出的方向過深或過硬，改寫成 user 能直接回答的一題。"""
            task_block = (
                "請以領域 interviewer 身分，只輸出對 user 的一個正式主問題（1-3 句）；"
                "若你判斷目前已蒐集到足夠資訊、可以收束本輪需求挖掘，則 statement 請只輸出以下固定句"
                f"（勿加引號、勿改寫、勿額外說明）：{stop_phrase}"
            )
            rules_block = f"""- 若你判斷目前資訊已足以支撐核心需求理解，且再往下追問的增益有限，可直接輸出停止句：{stop_phrase}
- 若關鍵限制、品質要求、權限/安全邊界、介面品質偏好、外部約束仍未釐清，不可停止。
- 若選擇提問，只能問 1 個主問題，不可合併多題。
- 問題必須可回答、可抽取、可直接轉成 quality requirement 或 constraint。
- open_questions 請輸出空陣列。"""
        user_prompt = f"""{topic_text}
{prev_text}
{snapshot_text}
{recent_ask_history_text}
{skill_section}
{tool_hint}
{category_hint}
{elicitation_hint}

{statement_contract}

{open_question_contract}

# 任務
{task_block}

# 規則
{rules_block}

# 輸出 JSON
{{{{
    "statement": "針對此議題的完整發言內容（含法規依據與風險說明）",
    "open_questions": [{{{{"to": "目標 agent 名稱", "question": "問題"}}}}]
}}}}"""

        messages = self.build_direct_messages(user_prompt)
        response = self.chat_for_conflict_topic_response(messages)
        statement = (response.get("statement") or "").strip()

        # 若仍為空（例如模型只回 JSON 殼、或議題非純法規導致拒答），用簡短重試強制產出內容
        if not statement:
            fallback_prompt = f"{topic_text}\n\n{expert_fallback_viewpoint()}"
            fallback_messages = self.build_direct_messages(fallback_prompt)
            try:
                raw_fallback = self.model.chat(fallback_messages)
                statement = (raw_fallback or "").strip()
            except Exception as e:
                self.logger.warning("expert 簡短重試失敗: %s", e)
                statement = "（依目前資訊暫無法提供具體法規依據，建議會後再查證後補充分享。）"

        return {
            "agent": self.name,
            "statement": statement,
            "open_questions": response.get("open_questions", []),
        }

    def respond_to_topic(self, topic, previous_responses=None, artifact_snapshot=None):
        return self.respond_to_conflict_topic(
            topic,
            previous_responses=previous_responses,
            artifact_snapshot=artifact_snapshot,
        )

    def execute_action(
        self,
        *,
        mode: str,
        decision: Dict[str, Any],
        **kwargs: Any,
    ) -> Dict[str, Any]:
        if mode == "topic_response":
            topic = kwargs["topic"]
            user_prompt = self._build_topic_response_prompt(
                topic=topic,
                previous_responses=kwargs.get("previous_responses"),
                artifact_snapshot=kwargs.get("artifact_snapshot"),
            )
            messages = self.build_direct_messages(user_prompt)
            response = self.chat_for_topic_response(messages)
            statement = (response.get("statement") or "").strip()
            if not statement:
                fallback_prompt = (
                    f"議題 [{topic.get('id', '')}]: {topic.get('title', '')}\n"
                    f"描述: {topic.get('description', '')}\n\n{expert_fallback_viewpoint()}"
                )
                fallback_messages = self.build_direct_messages(fallback_prompt)
                try:
                    raw_fallback = self.model.chat(fallback_messages)
                    statement = (raw_fallback or "").strip()
                except Exception as e:
                    self.logger.warning("expert 簡短重試失敗: %s", e)
                    statement = "（依目前資訊暫無法提供具體法規依據，建議會後再查證後補充分享。）"
            if statement in {"{}", "[]", "```json\n{}\n```", "```json\n[]\n```", "```\n{}\n```", "```\n[]\n```"}:
                statement = "（依目前資訊尚無足夠依據提出具體專業判斷，建議補充更多情境或約束後再審。）"
            return {
                "action": decision.get("action", ""),
                "status": "success",
                "statement": statement,
                "open_questions": response.get("open_questions", []),
                "summary": f"完成 expert topic_response: {decision.get('action', '')}",
            }
        return super().execute_action(mode=mode, decision=decision, **kwargs)

    # ===== Skill helpers =====

    @staticmethod
    def parse_first_json(raw: str) -> Dict:
        """從可能含多個 JSON 或後綴文字的內容中，只解析第一個完整 JSON 物件。"""
        if not raw or not isinstance(raw, str):
            return {}
        raw = raw.strip()
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            pass
        start = raw.find("{")
        if start == -1:
            return {}
        depth = 0
        for i in range(start, len(raw)):
            if raw[i] == "{":
                depth += 1
            elif raw[i] == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(raw[start : i + 1])
                    except json.JSONDecodeError:
                        pass
                    break
        return {}

    def has_doc_reference_files(self) -> bool:
        """與 ToolRegistry 一致：doc/ 下是否有至少一個可給 file_parser 使用的檔案。"""
        return has_supported_doc_files(self.doc_dir)
