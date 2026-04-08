import json
from typing import Dict, List, Optional, Any
from pathlib import Path

from agents.base import BaseAgent
from utils import (
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
        """Expert 子 OODA：自主研究 → 更新發現 → 標記風險。輪數上限為 min(caller, self_review_round_cap)；第一輪可縮短為 1…effective_max。"""
        observation = None
        actions_taken = []
        pending_issues = []
        research_results = []
        loop_cap = self.self_review_round_cap()
        effective_max = min(max_iterations, loop_cap)
        i = 0

        # 單輪策略：在同一輪內完成「研究 + 寫回」，而非事後保底補跑。
        if effective_max == 1:
            state = self.build_review_state(
                artifact, recent_discussions, actions_taken,
                research_results, i, effective_max,
            )
            decision = self.decide_next_review_action(state, observation)
            if not isinstance(decision, dict):
                decision = {"action": "done", "params": {}, "reasoning": "fallback: invalid decision format"}
            action = decision.get("action", "done")
            params = decision.get("params") or {}

            if action not in EXPERT_REVIEW_ACTIONS or action == "done":
                action = "research_topic"
                params = {
                    "query": "請針對本專案核心需求進行法規、合規與安全面向的初步研究",
                }

            self.logger.info(
                "  Expert review [1/1]: %s — %s",
                action,
                decision.get("reasoning", ""),
            )
            observation = self.execute_review_action(
                action, params, artifact, pending_issues, research_results,
            )
            actions_taken.append(
                {
                    "action": action,
                    "params": params,
                    "result_summary": observation.get("summary", ""),
                }
            )
            if observation.get("error"):
                self.logger.warning(f"  Expert review error: {observation['error']}")

            update_obs = self.execute_review_action(
                "update_findings",
                {},
                artifact,
                pending_issues,
                research_results,
            )
            actions_taken.append(
                {
                    "action": "update_findings",
                    "params": {},
                    "result_summary": update_obs.get("summary", ""),
                }
            )
            if update_obs.get("error"):
                self.logger.warning("  Expert update_findings 失敗: %s", update_obs.get("error"))

            return {
                "agent": self.name,
                "actions_taken": actions_taken,
                "pending_issues": pending_issues,
            }

        while i < effective_max:
            state = self.build_review_state(
                artifact, recent_discussions, actions_taken,
                research_results, i, effective_max,
            )
            decision = self.decide_next_review_action(state, observation)
            if not isinstance(decision, dict):
                self.logger.warning("  Expert review 格式異常（%s），fallback done", type(decision).__name__)
                decision = {
                    "action": "done",
                    "params": {},
                    "reasoning": "fallback: invalid decision format",
                }
            if i == 0:
                n = decision.get("max_iterations")
                if n is not None and isinstance(n, int) and 1 <= n <= effective_max:
                    effective_max = n
                    self.logger.info("  Expert review 輪數: %s/%s", effective_max, loop_cap)
            action = decision.get("action", "done")
            self.logger.info(f"  Expert review [{i + 1}/{effective_max}]: {action}")
            if action == "done" or action not in EXPERT_REVIEW_ACTIONS:
                break

            params = decision.get("params") or {}
            observation = self.execute_review_action(
                action, params, artifact, pending_issues, research_results,
            )
            actions_taken.append({
                "action": action,
                "params": params,
                "result_summary": observation.get("summary", ""),
            })
            if observation.get("error"):
                self.logger.warning(f"  Expert review error: {observation['error']}")
            i += 1

        return {
            "agent": self.name,
            "actions_taken": actions_taken,
            "pending_issues": pending_issues,
        }

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
            tool_part = "web_search 搜尋時可帶 user_question 以利停止條件"
            if self.has_doc_reference_files():
                tool_part += (
                    "；file_parser 請優先 search_chunks 再 read_chunks 讀 doc/，"
                    "必要時 read_full"
                )
            task = f"""針對以下問題進行領域研究：{query}

請使用可用工具（{tool_part}）蒐集相關法規標準或參考文件，然後整理研究發現。
輸出「僅一個」JSON：
{{
    "findings": ["發現1", "發現2"],
    "sources": ["來源1"],
    "derived_requirements": [
        {{"text": "建議需求", "source": "來源", "category": "regulatory/best_practice/safety"}}
    ],
    "compliance_risks": ["風險描述"]
}}
只輸出 JSON。"""
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
            task = """綜合 Context.research_results 與 Context.existing_research，依 domain-research skill 格式產出合併後的領域研究資料。
輸出「僅一個」JSON，鍵名 "domain_research"，值含：
- findings（合併新舊研究發現）
- derived_requirements（合併新舊，勿重複）
- recommendations（選填）
只輸出 JSON。"""
            try:
                raw = self.invoke_skill("domain-research", task, context=context)
                result = self.parse_first_json(raw)
                dr = result.get("domain_research") or result
                if isinstance(dr, dict) and dr:
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
- 需要先看 requirements/conflicts/decisions/open_questions 時，先用 artifact_query
- artifact_query 例子：
  - {{"mode":"summarize","section":"requirements"}}
  - {{"mode":"get_section","section":"conflicts","compact":true}}
  - {{"mode":"related_context","item_id":"CF-01","compact":true}}
  - {{"mode":"find_items","section":"open_questions","filters":{{"status":"pending"}},"compact":true}}
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
        for dr in research.get("derived_requirements", []) or []:
            text = (dr.get("text") or "").strip()
            if not text:
                continue
            rid = (dr.get("id") or "").strip()
            needs_validation = bool(dr.get("needs_validation"))
            confidence = str(dr.get("confidence") or "").strip().lower()
            routing_preference = (
                "direct_clarification" if needs_validation or confidence == "low" else "formal_meeting"
            )
            requires_multi_party = routing_preference == "formal_meeting"
            blocks_decision = True
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
                    "why_now": "此需求屬法規/合規/安全約束，需先確認是否可直接採納或進一步協調。",
                    "requires_multi_party": requires_multi_party,
                    "blocks_decision": blocks_decision,
                    "routing_preference": routing_preference,
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
                    "requires_multi_party": False,
                    "blocks_decision": True,
                    "routing_preference": "direct_clarification",
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
                "若有 file_parser 工具：建議先 action=search_chunks 檢索 doc/，"
                "再 action=read_chunks 讀回片段後綜合；若已知檔名且需全文可 action=read_full。"
            )
        task = f"""依 domain-research skill 執行研究，根據 Context 產出研究結果。
{doc_hint}

只輸出一個 JSON 物件，鍵名為 "research_session"。
research_session 至少需含：
- id, domain, topic, timestamp
- findings
- derived_requirements
- recommendations（選填）
- gaps_in_research（選填）

若 derived_requirements 屬法規/約束類，請保留 source、source_detail、confidence、needs_validation、category。勿輸出 Markdown。"""
        raw = self.invoke_skill("domain-research", task, context=context)
        response = self.parse_first_json(raw or "")
        research_session = response.get("research_session")
        if isinstance(research_session, dict):
            pass
        elif isinstance(response, dict) and (
            response.get("findings") or response.get("derived_requirements")
        ):
            # skill 有時直接回傳 research 內容於頂層
            research_session = response
        else:
            research_session = {}
        if not research_session:
            self.logger.warning("domain-research 未產出 research_session")
        return {"feedback": {"domain_research": research_session}}

    # ===== Action: meeting response =====

    def get_optional_skill_context(
        self, topic: Dict, artifact_snapshot: Optional[Dict]
    ) -> Optional[str]:
        """議題涉及 Conflict 協調或 NFR 取捨時，觸發 domain-research 產出簡短要點供發言參考。"""
        if topic.get("category") not in (
            "conflict_resolution", "tradeoff"
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

    def respond_to_topic(self, topic, previous_responses=None, artifact_snapshot=None):
        topic_text = f"議題 [{topic.get('id', '')}]: {topic.get('title', '')}\n描述: {topic.get('description', '')}"

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

        skill_section = ""
        skill_context = self.get_optional_skill_context(topic, artifact_snapshot)
        if skill_context:
            skill_section = f"\n# Skill 參考（本輪依議題類型觸發）\n{skill_context}\n"

        tool_hint = ""
        if self.tools:
            fp_line = ""
            if self.has_doc_reference_files():
                fp_line = (
                    "- file_parser：建議 search_chunks → read_chunks 再綜合；"
                    "或 read_full 讀單檔（text / json_summary）。\n"
                )
            tool_hint = (
                "\n# 工具使用\n"
                f"{fp_line}"
                "- 最後**必須**輸出下列 JSON。"
            )

        category = (topic.get("category") or "").strip()
        if category == "conflict_resolution":
            category_hint = """# 本議題特別要求（conflict_resolution）
- 優先說明衝突核心點、法規或標準底線、不同方向的合規風險與可接受折衷邊界。"""
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

        user_prompt = f"""{topic_text}
{prev_text}
{snapshot_text}
{skill_section}
{tool_hint}
{category_hint}

{statement_contract}

{open_question_contract}

# 任務
請以領域專家身分發言，聚焦法規、標準、證據、限制與風險。

# 規則
- statement 需包含：暫時結論、依據、風險/限制、建議下一步。
- 若屬強制義務要明講；若只是最佳實務或待補證據也要明講。
- 可引用 requirement id、conflict id、研究發現或來源線索。
- 若資訊不足，明確指出 evidence gap；不要虛構法規或標準。
- 不決定產品 scope、優先級或最終需求 wording。
- 可用純文字表格或流程輔助；若使用，請放在程式碼區塊。

# 輸出 JSON
{{{{
    "statement": "針對此議題的完整發言內容（含法規依據與風險說明）",
    "open_questions": [{{{{"to": "目標 agent 名稱", "question": "問題"}}}}]
}}}}"""

        messages = self.build_direct_messages(user_prompt)
        response = self.chat_for_topic_response(messages)
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
