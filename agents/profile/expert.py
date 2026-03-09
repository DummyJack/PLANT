import json
from typing import Dict, List, Optional
from pathlib import Path

from agents.base import BaseAgent

# 與 ReadExternalFileTool 支援的副檔名一致（供 flow 組裝工具時判斷）
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
    "review_neutrals",
    "flag_compliance_risk",
    "done",
]


class ExpertAgent(BaseAgent):
    """領域專家 Agent — 賦予 domain-research skill，可搭配 read_external_file 等工具（由 flow 依 enable_tools 注入）。"""

    name = "expert"

    system_prompt = """你是領域專家，負責提供必須遵守的法規、標準、安全規範。
核心原則：Evidence-first、可追溯來源、無證據不建議；約束須含具體條文、適用範圍、合規要求與風險。"""

    def __init__(
        self,
        model,
        tools: Optional[list] = None,
        registry=None,
        doc_dir: str = "doc",
    ):
        self.doc_dir = Path(doc_dir)
        self.doc_dir.mkdir(parents=True, exist_ok=True)
        super().__init__(
            model,
            tools=tools or [],
            registry=registry,
            skill_names=["domain-research"],
        )

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
        task = """依 domain-research skill 的 **Output Format: Research Results** 執行領域研究並產出結果。
審查 Context 中的需求與專案概述，若有 read_external_file 工具可先讀取 doc/ 參考檔案，依專案範圍識別法規/標準/安全規範與 derived_requirements。
輸出「僅一個」JSON 物件，鍵名 "research_session"，值為物件，須含：
- id（如 RES-{timestamp}）
- domain, topic, timestamp
- findings（domain_context, best_practices, regulatory, competitive 等陣列）
- derived_requirements（陣列，每筆含 id, text, source, source_detail, confidence, needs_validation, category；法規/約束類請產出於此）
- recommendations（選填）
- gaps_in_research（選填）
findings、derived_requirements 的 text/source_detail、recommendations、gaps_in_research 等所有描述與說明文字請使用繁體中文。id、category 等欄位名維持英文。勿輸出 Markdown，只輸出該 JSON。"""
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
            self.logger.warning(
                "domain-research skill 未產出 research_session（可能為 JSON 解析失敗或 skill 回傳格式不符）"
            )
        return {"feedback": {"domain_research": research_session}}

    def cross_review_neutrals(self, artifact: Dict) -> List[Dict]:
        """從領域專業角度複審 Neutral 項目，找出可能遺漏的衝突。"""
        neutrals = [
            c for c in artifact.get("conflicts", [])
            if c.get("label") == "Neutral"
        ]
        if not neutrals:
            return []

        domain_research = artifact.get("feedback", {}).get("domain_research", {})
        context = {
            "neutrals": neutrals,
            "requirements": artifact.get("requirements", []),
            "domain_research": domain_research,
        }
        task = """你是領域專家。以下是 Analyst 判定為「無衝突（Neutral）」的項目。
請從法規、技術限制、行業標準的角度複審，判斷是否有被遺漏的衝突。

常見盲點：
- 兩條需求從文字看無衝突，但某法規實際上禁止同時實現
- 兩條技術需求看似相容，但在特定架構或部署環境下會互相衝突
- 需求描述模糊導致 Analyst 無法判斷，但領域知識能指出實質衝突

輸出 JSON：
{
    "upgraded_conflicts": [
        {
            "original_neutral_id": "NF-XX",
            "description": "為什麼這其實是衝突",
            "conflict_type": "Logical/Technical/Resource/Temporal/Data/State/Priority/Scope",
            "requirement_ids": ["R-XX", "R-YY"],
            "domain_evidence": "領域依據（法規條文、技術限制等）"
        }
    ],
    "review_summary": "複審摘要"
}
若所有 Neutral 確實無衝突，upgraded_conflicts 為空陣列。
文字請使用繁體中文。只輸出 JSON。"""

        messages = self.build_direct_messages(task, context=context)
        try:
            result = self.model.chat_json(messages)
        except Exception as e:
            self.logger.warning(f"Expert Neutral 複審失敗: {e}")
            return []

        upgraded = result.get("upgraded_conflicts", [])
        if not isinstance(upgraded, list):
            return []

        if upgraded:
            self.logger.info(
                f"Expert 複審發現 {len(upgraded)} 個 Neutral 可能有衝突"
            )
        return upgraded

    def get_optional_skill_context(
        self, topic: Dict, artifact_snapshot: Optional[Dict]
    ) -> Optional[str]:
        """議題涉及衝突協調、需求釐清或 NFR 取捨時，觸發 domain-research 產出簡短要點供發言參考。"""
        if topic.get("category") not in (
            "conflict_resolution", "requirement_clarification", "tradeoff"
        ):
            return None
        if "domain-research" not in self.skill_names:
            return None
        context = {"topic": topic, "artifact_snapshot": artifact_snapshot or {}}
        task = """針對 Context 中的議題與專案狀態，簡要列出 1～3 點法規/合規/安全相關要點（可含適用範圍與風險），供會議發言參考。請使用繁體中文。只輸出簡短條列文字，勿 JSON。"""
        try:
            raw = self.invoke_skill("domain-research", task, context=context)
            return (raw or "").strip()[:1500]
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
            tool_hint = "\n# 工具使用\n- 可先使用 read_external_file 讀取 doc/ 參考檔案，再根據結果撰寫發言。\n- 最後**必須**輸出下列 JSON。"

        user_prompt = f"""{topic_text}
{prev_text}
{snapshot_text}
{skill_section}
{tool_hint}

# 思考與發言流程
1. 先思考：(1) 此議題相關的法規、標準或技術限制 (2) 不可讓步的要點（須附法規/標準依據）(3) 可接受調整或折衷的要點
2. 再根據思考結果，撰寫一段完整的發言（statement），針對議題提出你的專業見解與法規依據
3. 若有需要請其他角色回答的問題，列入 open_questions（to 填寫目標 agent 名稱，如 "user"、"analyst"、"modeler"）

# 發言風格
- 以領域專家在會議中的口吻：引用法規/標準時註明來源或條文，說明不合規風險與適用範圍
- 資訊不足時可明確說「這部分需要再查證」或「依目前查到的資料…」，不捏造

# 約束
- statement 必須包含具體的法規依據和不合規風險，禁止虛構法規或標準名稱
- 論點必須有客觀依據，無依據則標註「資訊不足」
- 若此議題與法規/標準無直接對應，仍請以領域專家角度簡要說明最佳實務、業界常見做法或技術/風險建議；切勿留空或僅輸出 JSON 結構
- 依你的立場投票（vote）：agreed 表示可達成共識；unresolved 表示仍有衝突需升級
- statement、open_questions 的 question 請使用繁體中文

輸出 JSON:
{{{{
    "statement": "針對此議題的完整發言內容（含法規依據與風險說明）",
    "vote": "agreed 或 unresolved",
    "open_questions": [{{{{"to": "目標 agent 名稱", "question": "問題"}}}}]
}}}}"""

        messages = self.build_direct_messages(user_prompt)
        response = self.chat_for_topic_response(messages)
        statement = (response.get("statement") or "").strip()

        # 若仍為空（例如模型只回 JSON 殼、或議題非純法規導致拒答），用簡短重試強制產出內容
        if not statement:
            fallback_prompt = (
                f"{topic_text}\n\n"
                "請以領域專家身份，用 2～4 句話簡要說明你對上述議題的專業看法（可含法規、最佳實務、技術建議或風險提醒）。勿留空，直接輸出繁體中文內容。"
            )
            fallback_messages = self.build_direct_messages(fallback_prompt)
            try:
                raw_fallback = self.model.chat(fallback_messages)
                statement = (raw_fallback or "").strip()
                if len(statement) > 2000:
                    statement = statement[:2000] + "…"
            except Exception as e:
                self.logger.warning("expert 簡短重試失敗: %s", e)
                statement = "（依目前資訊暫無法提供具體法規依據，建議會後再查證後補充分享。）"

        return {
            "agent": self.name,
            "statement": statement,
            "vote": response.get("vote", "unresolved"),
            "open_questions": response.get("open_questions", []),
        }

    # ===== 子 OODA 循環 =====

    def run_review_loop(self, artifact, recent_discussions=None, max_iterations=5):
        """Expert 子 OODA：自主研究 → 更新發現 → 標記風險。"""
        observation = None
        actions_taken = []
        pending_issues = []
        research_results = []

        for i in range(max_iterations):
            state = self._build_review_state(
                artifact, recent_discussions, actions_taken,
                research_results, i, max_iterations,
            )
            decision = self.decide_next_review_action(state, observation)
            action = decision.get("action", "done")
            self.logger.info(
                f"  Expert review [{i + 1}/{max_iterations}]: {action}"
                f" — {decision.get('reasoning', '')}"
            )
            if action == "done" or action not in EXPERT_REVIEW_ACTIONS:
                break

            params = decision.get("params") or {}
            observation = self._execute_review_action(
                action, params, artifact, pending_issues, research_results,
            )
            actions_taken.append({
                "action": action,
                "params": params,
                "result_summary": observation.get("summary", ""),
            })
            if observation.get("error"):
                self.logger.warning(f"  Expert review error: {observation['error']}")

        return {
            "agent": self.name,
            "actions_taken": actions_taken,
            "pending_issues": pending_issues,
        }

    def decide_next_review_action(self, state, last_observation=None):
        state_text = json.dumps(state, ensure_ascii=False, indent=2)
        obs_text = json.dumps(last_observation or {}, ensure_ascii=False, indent=2)

        tools_hint = ""
        if state.get("available_tools"):
            tools_hint = (
                "\n- research_topic 執行時可自動使用工具："
                + ", ".join(state["available_tools"])
            )

        user_prompt = f"""# 任務
你是領域專家，正在對當前專案進行自主領域研究與合規分析。根據「當前狀態」與「上一步結果」，決定下一步行動。

# 可用動作
- research_topic：針對特定問題進行領域研究（搜尋法規、讀取文件）。params: {{ "query": "具體研究問題" }}{tools_hint}
- update_findings：綜合已有研究結果更新至專案領域研究資料。無參數。（研究完畢後呼叫）
- review_neutrals：從領域角度複審被標為 Neutral（無衝突）的項目，找出 Analyst 可能遺漏的衝突。無參數。
- flag_compliance_risk：標記合規風險供主持人參考。params: {{ "description": "風險描述" }}
- done：分析完成，交還控制權。無參數。

# 當前狀態
{state_text}

# 上一步結果
{obs_text}

# 決策指引
- 若有近期討論涉及法規、標準、安全、合規問題，優先研究
- 若需求涉及受管制領域（用戶資料、支付、醫療、教育等），研究對應法規
- research_topic 可多次呼叫，每次聚焦一個具體問題
- 研究到足夠深度後呼叫 update_findings 寫入
- 若有 Neutral 項目且已有領域研究結果，呼叫 review_neutrals 複審
- 發現重大合規風險時呼叫 flag_compliance_risk
- 無需進一步研究時呼叫 done
- reasoning 請使用繁體中文

輸出 JSON:
{{
    "action": "動作名稱",
    "params": {{}},
    "reasoning": "一句說明"
}}"""

        messages = self.build_direct_messages(user_prompt)
        try:
            response = self.model.chat_json(messages)
        except Exception as e:
            self.logger.warning(f"Expert review 決策失敗: {e}")
            return {"action": "done", "params": {}, "reasoning": f"fallback: {e}"}

        action = (response.get("action") or "").strip()
        if action not in EXPERT_REVIEW_ACTIONS:
            action = "done"
        return {
            "action": action,
            "params": response.get("params") or {},
            "reasoning": response.get("reasoning", ""),
        }

    def _build_review_state(
        self, artifact, recent_discussions, actions_taken,
        research_results, iteration, max_iterations,
    ):
        reqs = artifact.get("requirements", [])
        summary_reqs = [
            {"id": r.get("id"), "type": r.get("type"),
             "text": (r.get("text") or "")[:120]}
            for r in reqs
        ]
        conflicts = [
            {"id": c.get("id"),
             "description": (c.get("description") or "")[:120]}
            for c in artifact.get("conflicts", [])
            if c.get("label") == "Conflict"
        ]
        neutrals = [
            {"id": c.get("id"),
             "confidence": c.get("confidence"),
             "description": (c.get("description") or "")[:120]}
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
                "summary": (resolution.get("summary") or "")[:200],
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

    def _execute_review_action(
        self, action, params, artifact, pending_issues, research_results,
    ):
        obs: Dict = {"action": action, "result": None, "error": None, "summary": ""}

        if action == "research_topic":
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

請使用可用工具搜尋相關法規標準或讀取 doc/ 參考文件，然後整理研究發現。
輸出「僅一個」JSON：
{{
    "findings": ["發現1", "發現2"],
    "sources": ["來源1"],
    "derived_requirements": [
        {{"text": "建議需求", "source": "來源", "category": "regulatory/best_practice/safety"}}
    ],
    "compliance_risks": ["風險描述"]
}}
文字請使用繁體中文。只輸出 JSON。"""
            messages = self.build_direct_messages(task, context=context)
            try:
                raw = (
                    self.chat_with_tools(
                        messages, max_rounds=self.tool_call_max_rounds,
                    )
                    if self.tools
                    else self.model.chat(messages)
                )
                result = self.parse_first_json(raw)
                if not result:
                    result = {"findings": [(raw or "")[:500]]}
                research_results.append({"query": query, **result})
                obs["result"] = result
                obs["summary"] = (
                    f"研究 '{query[:40]}': "
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
文字使用繁體中文。只輸出 JSON。"""
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

        if action == "review_neutrals":
            try:
                upgraded = self.cross_review_neutrals(artifact)
                if upgraded:
                    for up in upgraded:
                        pending_issues.append({
                            "type": "upgraded_neutral",
                            "description": up.get("description", ""),
                            "source": "expert",
                            "original_neutral_id": up.get("original_neutral_id"),
                            "conflict_type": up.get("conflict_type", ""),
                            "requirement_ids": up.get("requirement_ids", []),
                            "domain_evidence": up.get("domain_evidence", ""),
                        })
                    obs["result"] = {"upgraded_count": len(upgraded)}
                    obs["summary"] = (
                        f"複審發現 {len(upgraded)} 個 Neutral 可能有衝突"
                    )
                else:
                    obs["summary"] = "所有 Neutral 項目確認無衝突"
            except Exception as e:
                obs["error"] = str(e)
                obs["summary"] = f"Neutral 複審失敗: {e}"
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
            obs["summary"] = f"已標記合規風險: {desc[:80]}"
            return obs

        obs["error"] = f"未知動作: {action}"
        return obs
