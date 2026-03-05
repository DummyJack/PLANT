import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Dict, List, Any, Optional
from agents.base import BaseAgent

_TYPE_DIR = Path(__file__).resolve().parent.parent / "type"
with open(_TYPE_DIR / "agenda_types.json", "r", encoding="utf-8") as _f:
    AGENDA_TYPES = tuple(json.load(_f))
AGENDA_TYPE_IDS = [t["id"] for t in AGENDA_TYPES]

AGENDA_ACTIONS = [
    "generate_agenda",
    "start_discussion",
    "resolve_topic",
    "escalate_to_human",
    "save_topic",
    "finish_round",
]


class MediatorAgent(BaseAgent):
    name = "mediator"

    system_prompt = """你是一個專業的需求調解主持人，負責主持需求討論會議。

核心職責：
1. 議程安排 — 分析需求與衝突，自行判斷應開哪些議程並排定優先順序
2. 討論主持 — 決定討論模式（逐一發言/同時發言），維持討論秩序
3. 共識促成 — 綜合各方的不可讓步項與可讓步項，嘗試達成共識
4. 決策彙整 — 彙整每輪討論的決策並更新衝突標記

核心原則：
- 中立客觀 — 不偏袒任何利害關係人，不提出自己的技術觀點
- 忠於資料 — 只根據已有的分析結果和討論內容做出綜合判斷
- 無法共識時升級 — 無法達成共識時直接升級至人類裁決"""

    def __init__(self, model, tools: Optional[list] = None, registry=None):
        super().__init__(model, tools=tools, registry=registry)

    def generate_agenda(
        self,
        artifact: Dict[str, Any],
        registry=None,
        max_items: Optional[int] = None,
        skip_source_ids: Optional[set] = None,
        draft_markdown: Optional[str] = None,
    ) -> List[Dict]:
        """由 Mediator LLM 根據最新草稿與專案狀態自行決定要開哪些議程。"""
        limit = max_items or 5
        exclude = {"mediator", "documentor"}
        if registry:
            registered = [n for n in registry.get_names() if n not in exclude]
        else:
            registered = ["user", "analyst", "expert", "modeler"]

        skip = skip_source_ids or set()
        context = self.build_agenda_context(artifact, skip)
        if draft_markdown and draft_markdown.strip():
            context = (
                "## 最新需求草稿（本輪開會依據）\n\n"
                + draft_markdown.strip()
                + "\n\n---\n\n"
                + context
            )
        if not context.strip():
            self.logger.info("無足夠專案內容或草稿可供判斷議程")
            return []

        types_text = json.dumps(AGENDA_TYPES, ensure_ascii=False, indent=2)
        user_prompt = f"""# 任務
你是需求調解主持人。請根據「最新需求草稿」與「當前專案狀態」、以及「已討論過項目」，自行判斷本輪應開哪些議程。
議程類型必須從下方「議程類型定義」中選擇，每項議程需決定：標題、描述、類型、參與者、討論模式、發言順序。

# 議程類型定義（category 必須為以下 id 之一）
{types_text}

# 最新需求草稿與專案狀態
{context}

# 已在本輪或前輪討論過的項目（可略過或合併，勿重複開相同議題）
已討論 source_ids: {json.dumps(list(skip), ensure_ascii=False)}

# 可用 agent（participants 與 speaking_order 僅能使用此清單內名稱）
{json.dumps(registered, ensure_ascii=False)}

# 討論模式（discussion_mode）情境說明
- **sequential（逐一發言）**：適合需要「依序陳述並回應前一位」的議題。例如：衝突協調、決策取捨、開放問題釐清、需求取捨（NFR 競合）。後發言者會看到前面所有人的發言，可針對性回應，討論感較強。
- **simultaneous（同時發言）**：適合「先各自表態、再比較差異」的議題。例如：腦力激盪、多方案並列、各自提出對某議題的立場或建議，不需即時回應前一位。每人只看到議題與專案狀態，不看同輪其他人的發言。
請依議題性質選擇其一。

# 標題與描述撰寫要求（重要）
- **title（標題）**：一句話、具體、讓人一眼知道「要討論什麼」。要與本專案內容掛鉤，例如寫出涉及的對象、需求或衝突重點，勿只寫類型名稱（如勿只寫「衝突討論」「需求取捨」）。
- **description（描述）**：簡短說明「為什麼要開這個議題、要解決什麼」。可提及相關需求 id 或衝突 id，並用一兩句話說明討論重點。
- 範例：標題可為「管理員權限與一般使用者隱私的衝突如何取捨」而非「衝突討論」；描述可為「CF-01 涉及 R-01 與 R-03，需協調兩方立場」。

# 約束
- 最多開 {limit} 個議程，依你判斷的優先順序排列
- 若無需討論的議題，請回傳空陣列
- category 只能是上述類型定義中的 id
- discussion_mode 依上表情境選擇 "sequential" 或 "simultaneous"
- 若有對應的衝突/需求/問題 id，請填在 source_ids 方便追蹤

# 輸出 JSON
{{
    "items": [
        {{
            "title": "具體議程標題（與本專案內容掛鉤的一句話）",
            "description": "簡短說明為何要討論、要解決什麼",
            "category": "類型 id",
            "participants": ["agent1", "agent2"],
            "discussion_mode": "sequential 或 simultaneous",
            "speaking_order": ["agent1", "agent2"],
            "source_ids": ["id1", "id2"]
        }}
    ]
}}"""

        messages = self.build_direct_messages(user_prompt)
        try:
            response = self.model.chat_json(messages)
        except Exception as e:
            self.logger.warning(f"議程生成 LLM 失敗: {e}")
            return []

        raw_items = response.get("items", [])
        if not raw_items:
            self.logger.info("Mediator 判斷本輪無需新增議程")
            return []

        agenda_items = []
        for idx, item in enumerate(raw_items[:limit], 1):
            category = item.get("category", "")
            if category not in AGENDA_TYPE_IDS:
                category = AGENDA_TYPE_IDS[0]
            participants = [p for p in item.get("participants", []) if p in registered]
            if not participants:
                participants = list(registered)
            mode = item.get("discussion_mode", "sequential")
            if mode not in ("sequential", "simultaneous"):
                mode = "sequential"
            order = [
                p for p in item.get("speaking_order", participants) if p in participants
            ]
            if set(order) != set(participants):
                order = participants

            title = (item.get("title") or "待討論議題").strip()
            agenda_items.append(
                {
                    "id": f"T-{idx:02d}",
                    "title": title,
                    "description": item.get("description", ""),
                    "category": category,
                    "participants": participants,
                    "discussion_mode": mode,
                    "speaking_order": order,
                    "source_ids": item.get("source_ids", []),
                }
            )

        return agenda_items

    def build_agenda_context(
        self, artifact: Dict[str, Any], skip_source_ids: set
    ) -> str:
        """組裝 artifact 摘要供 Mediator 判斷議程用，不含演算法邏輯。"""
        parts = []
        scope = artifact.get("scope") or {}
        if (
            scope.get("description")
            or scope.get("in_scope")
            or scope.get("out_of_scope")
        ):
            parts.append(
                "## 專案範圍\n" + json.dumps(scope, ensure_ascii=False, indent=2)
            )
        if artifact.get("stakeholders"):
            parts.append(
                "## 利害關係人\n"
                + json.dumps(artifact["stakeholders"], ensure_ascii=False, indent=2)
            )
        if artifact.get("requirements"):
            reqs = [
                {
                    "id": r.get("id"),
                    "type": r.get("type"),
                    "text": (r.get("text") or ""),
                }
                for r in artifact["requirements"]
            ]
            parts.append(
                "## 需求摘要\n" + json.dumps(reqs, ensure_ascii=False, indent=2)
            )
        conflicts = [
            c
            for c in artifact.get("conflicts", [])
            if c.get("id", "") not in skip_source_ids
        ]
        if conflicts:
            parts.append(
                "## 衝突\n" + json.dumps(conflicts, ensure_ascii=False, indent=2)
            )
        oqs = [
            q
            for q in artifact.get("open_questions", [])
            if q.get("status") != "answered"
        ]
        if oqs:
            parts.append(
                "## 未回答的開放問題\n" + json.dumps(oqs, ensure_ascii=False, indent=2)
            )
        models = artifact.get("system_models", {}).get("models", [])
        if models:
            refs = []
            for m in models:
                refs.extend(m.get("requirement_refs", []))
            parts.append(
                "## 系統模型已參照需求 id\n"
                + json.dumps(list(set(refs)), ensure_ascii=False)
            )
        return "\n\n".join(parts) if parts else ""

    # ===== 議程 Agent 決策（供執行層迴圈呼叫）=====

    def decide_next_agenda_action(
        self,
        state_summary: Dict[str, Any],
        last_observation: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """根據當前狀態與上一動觀察，回傳下一個動作與參數。"""
        last_observation = last_observation or {}
        state_text = json.dumps(state_summary, ensure_ascii=False, indent=2)
        obs_text = json.dumps(last_observation, ensure_ascii=False, indent=2)

        user_prompt = f"""# 任務
你是需求調解主持人，正在主持本輪議程。請根據「當前狀態」與「上一動執行結果」，決定下一步要執行的動作。

# 可用動作與參數
- generate_agenda：產生本輪議程（無參數）。若 topics 已存在則勿重複呼叫。
- start_discussion：對某議題開始討論。params: {{ "topic_id": "T-01" }}（須為 state.topics 中存在的 id）
- resolve_topic：綜合某議題討論結果。params: {{ "topic_id": "T-01" }}（須已 start_discussion）
- escalate_to_human：某議題交由人類裁決。params: {{ "topic_id": "T-01" }}（須已 start_discussion）
- save_topic：儲存某議題的討論與決議。params: {{ "topic_id": "T-01" }}（須已 resolve 或 escalate）
- finish_round：結束本輪議程。無參數。僅在已處理完所有要討論的議題並 save 後才可呼叫。

# 當前狀態
{state_text}

# 上一動執行結果（若為首輪則為空）
{obs_text}

# 規則
- 若 topics 為空，先呼叫 generate_agenda
- 對每個要討論的 topic 依序：start_discussion → resolve_topic（若共識則直接 save_topic；若未共識可選 escalate_to_human 再 save_topic）→ save_topic
- 全部處理完後呼叫 finish_round
- 一次只回傳一個動作

# 輸出 JSON
{{
    "action": "動作名稱",
    "params": {{}} or {{ "topic_id": "T-01" }},
    "reasoning": "一句說明"
}}"""

        messages = self.build_direct_messages(user_prompt)
        try:
            response = self.model.chat_json(messages)
        except Exception as e:
            self.logger.warning(f"議程決策 LLM 失敗: {e}")
            return {
                "action": "finish_round",
                "params": {},
                "reasoning": f"fallback: {e}",
            }

        action = (response.get("action") or "").strip()
        if action not in AGENDA_ACTIONS:
            action = "finish_round"
        params = response.get("params") or {}
        return {
            "action": action,
            "params": params,
            "reasoning": response.get("reasoning", ""),
        }

    # ===== 討論主持 =====

    @staticmethod
    def build_artifact_snapshot(artifact: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """產出專案狀態摘要，供 respond_to_topic 的 artifact_snapshot 使用"""
        if not artifact:
            return {}
        reqs = artifact.get("requirements", [])
        summary_reqs = [
            {"id": r.get("id"), "type": r.get("type"), "text": (r.get("text") or "")}
            for r in reqs
        ]
        conflicts = [
            {"id": c.get("id"), "description": (c.get("description") or "")}
            for c in artifact.get("conflicts", [])
            if c.get("label") == "Conflict"
        ]
        oqs = [
            {"from_agent": q.get("from_agent"), "question": (q.get("question") or "")}
            for q in artifact.get("open_questions", [])
            if q.get("status") != "answered"
        ]
        return {
            "requirements": summary_reqs,
            "conflicts": conflicts,
            "open_questions": oqs,
        }

    def moderate_sequential(
        self, topic: Dict, registry, artifact: Optional[Dict[str, Any]] = None
    ) -> List[Dict]:
        contributions = []
        speaking_order = topic.get("speaking_order", topic.get("participants", []))
        self.logger.info(f"[{topic['id']}] 逐一發言: {' → '.join(speaking_order)}")

        snapshot = self.build_artifact_snapshot(artifact)
        for agent_name in speaking_order:
            agent = registry.get(agent_name)
            if not agent:
                self.logger.warning(f"Agent '{agent_name}' 未註冊，跳過")
                continue
            try:
                response = agent.respond_to_topic(
                    topic, previous_responses=contributions, artifact_snapshot=snapshot
                )
                contributions.append(
                    {
                        "agent": agent_name,
                        "response": (
                            response
                            if isinstance(response, dict)
                            else {"content": str(response)}
                        ),
                    }
                )
            except Exception as e:
                self.logger.warning(f"  {agent_name} 發言失敗: {e}")
                contributions.append(
                    {"agent": agent_name, "response": {"content": f"（發言失敗: {e}）"}}
                )

        return contributions

    def _respond_one_simultaneous(
        self,
        agent_name: str,
        topic: Dict,
        registry,
        artifact: Optional[Dict[str, Any]],
        snapshot: Dict[str, Any],
    ) -> Dict[str, Any]:
        """單一 agent 發言，供 moderate_simultaneous 並行呼叫。"""
        agent = registry.get(agent_name)
        if not agent:
            self.logger.warning(f"Agent '{agent_name}' 未註冊，跳過")
            return {"agent": agent_name, "response": {"content": "（未註冊，跳過）"}}
        try:
            response = agent.respond_to_topic(
                topic, previous_responses=None, artifact_snapshot=snapshot
            )
            return {
                "agent": agent_name,
                "response": (
                    response
                    if isinstance(response, dict)
                    else {"content": str(response)}
                ),
            }
        except Exception as e:
            self.logger.warning(f"  {agent_name} 發言失敗: {e}")
            return {"agent": agent_name, "response": {"content": f"（發言失敗: {e}）"}}

    def moderate_simultaneous(
        self, topic: Dict, registry, artifact: Optional[Dict[str, Any]] = None
    ) -> List[Dict]:
        participants = topic.get("participants", [])
        self.logger.info(f"[{topic['id']}] 同時發言: {', '.join(participants)}")

        snapshot = self.build_artifact_snapshot(artifact)
        max_workers = min(len(participants), 6)
        contributions_by_agent = {}

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(
                    self._respond_one_simultaneous,
                    agent_name,
                    topic,
                    registry,
                    artifact,
                    snapshot,
                ): agent_name
                for agent_name in participants
            }
            for future in as_completed(futures):
                agent_name = futures[future]
                try:
                    contrib = future.result()
                    contributions_by_agent[contrib["agent"]] = contrib
                except Exception as e:
                    self.logger.warning(f"  {agent_name} 發言失敗: {e}")
                    contributions_by_agent[agent_name] = {
                        "agent": agent_name,
                        "response": {"content": f"（發言失敗: {e}）"},
                    }

        contributions = [
            contributions_by_agent[name]
            for name in participants
            if name in contributions_by_agent
        ]
        return contributions

    # ===== Open Question 處理 =====

    def handle_open_questions(
        self,
        contributions: List[Dict],
        registry,
        stakeholders: List[Dict],
        artifact: Optional[Dict[str, Any]] = None,
    ) -> List[Dict]:
        """將 open_questions 依 to 欄位路由到對應 agent 回答"""
        oq_records = []
        snapshot = self.build_artifact_snapshot(artifact)

        all_questions = []
        for c in contributions:
            agent_name = c.get("agent", "")
            resp = c.get("response", {}) if isinstance(c.get("response"), dict) else {}
            for q in resp.get("open_questions", []):
                if isinstance(q, str):
                    q = {"question": q, "to": "user"}
                elif not isinstance(q, dict):
                    continue
                to_agent = q.get("to", "user")
                if to_agent == agent_name:
                    continue
                all_questions.append(
                    {
                        "from_agent": agent_name,
                        "to_agent": to_agent,
                        "question": q.get("question", ""),
                    }
                )

        valid_questions = [q for q in all_questions if q.get("question")]
        if not valid_questions:
            return oq_records

        def answer_one(q_record: Dict) -> tuple:
            """回答單一問題，回傳 (q_record, contribution_entry or None, oq_record)。"""
            target_name = q_record["to_agent"]
            target_agent = registry.get(target_name) if registry else None
            if not target_agent:
                return (q_record, None, {**q_record, "status": "deferred"})
            try:
                q_topic = {
                    "id": "OQ",
                    "title": f"回答 {q_record['from_agent']} 的問題",
                    "description": (
                        f"{q_record['question']}\n\n"
                        "（請簡要針對此問題回答，若前面發言已涵蓋可寫「如前述」或只補充重點，勿整段重複相同內容。）"
                    ),
                }
                response = target_agent.respond_to_topic(
                    q_topic,
                    previous_responses=contributions,
                    artifact_snapshot=snapshot,
                )
                resp = (
                    response
                    if isinstance(response, dict)
                    else {"content": str(response)}
                )
                resp = dict(resp)
                resp["reply_to_question"] = q_record["question"]
                resp["reply_to_agent"] = q_record["from_agent"]
                answer = resp.get("statement") or resp.get("content", "")
                contrib = {
                    "agent": target_name,
                    "response": resp,
                    "is_reply": True,
                }
                return (
                    q_record,
                    contrib,
                    {**q_record, "status": "answered", "answer": answer},
                )
            except Exception:
                return (q_record, None, {**q_record, "status": "deferred"})

        max_workers = min(len(valid_questions), 6)
        results_by_idx = {}

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(answer_one, q_record): i
                for i, q_record in enumerate(valid_questions)
            }
            for future in as_completed(futures):
                idx = futures[future]
                try:
                    _q, contrib, oq = future.result()
                    results_by_idx[idx] = (contrib, oq)
                except Exception as e:
                    self.logger.warning(f"開放問題回答失敗: {e}")
                    results_by_idx[idx] = (
                        None,
                        {**valid_questions[idx], "status": "deferred"},
                    )

        for i in range(len(valid_questions)):
            contrib, oq = results_by_idx.get(
                i, (None, {**valid_questions[i], "status": "deferred"})
            )
            oq_records.append(oq)
            if contrib:
                contributions.append(contrib)

        return oq_records

    def generate_meeting_markdown(
        self,
        topic: Dict,
        contributions: List[Dict],
        resolution: Dict,
        round_num: int = 0,
    ) -> str:
        mode = topic.get("discussion_mode", "sequential")
        participants = topic.get("participants", [])

        md = f"# {topic.get('title', '')}\n\n"
        md += f"- **Round**: {round_num}\n"
        summary = resolution.get("summary", "")
        decision = resolution.get("decision", "")
        md += f"- **Summary**: {summary}\n"
        if decision:
            md += f"- **Decision**: {decision}\n"
        md += f"- **Participants**: {', '.join(participants)}\n"
        md += f"- **Discussion mode**: {mode}\n"
        # 多數決投票結果
        votes_line = []
        for c in contributions:
            if c.get("is_reply", False):
                continue
            resp = c.get("response", {})
            v = resp.get("vote", "unresolved")
            votes_line.append(f"{c.get('agent', '?')}: {v}")
        if votes_line:
            md += f"- **Votes (多數決)**: {', '.join(votes_line)}\n"
        md += "\n"

        md += "## Participants content\n\n"
        for c in contributions:
            if c.get("is_reply", False):
                continue
            agent = c.get("agent", "?")
            resp = c.get("response", {})
            statement = resp.get("statement", "")
            md += f"### {agent}\n\n"
            if statement:
                md += f"{statement}\n\n"

        # ## Open Questions：以「提出者: 問題」與「回答者: 回答」格式列出
        oq_pairs = []
        for c in contributions:
            if not c.get("is_reply"):
                continue
            resp = c.get("response", {})
            question = resp.get("reply_to_question", "")
            from_agent = resp.get("reply_to_agent", "?")
            reply_agent = c.get("agent", "?")
            answer = resp.get("statement", "") or resp.get("content", "")
            if question or answer:
                oq_pairs.append((from_agent, question, reply_agent, answer))
        if oq_pairs:
            md += "## Open Questions\n\n"
            for from_agent, question, reply_agent, answer in oq_pairs:
                md += f"**{from_agent}**: {question}\n\n"
                md += f"**{reply_agent}**: {answer}\n\n"

        return md

    def synthesize_and_resolve(self, topic: Dict, contributions: List[Dict]) -> Dict:
        """依各 agent 的投票（vote）以多數決決定是否達成共識；agreed 時由 LLM 產出 summary 與 decision。"""
        # 只計入主要發言（排除開放問題的回覆），收集每人一票
        main_contributions = [c for c in contributions if not c.get("is_reply", False)]
        votes = []
        for c in main_contributions:
            resp = c.get("response", {}) if isinstance(c.get("response"), dict) else {}
            v = (resp.get("vote") or "unresolved").strip().lower()
            votes.append("agreed" if v == "agreed" else "unresolved")

        agreed_count = sum(1 for v in votes if v == "agreed")
        n = len(votes)
        # 多數決：同意數過半才為 agreed，否則 unresolved
        resolution = (
            "agreed" if n > 0 and agreed_count > (n - agreed_count) else "unresolved"
        )

        discussion_text = ""
        for c in contributions:
            agent = c.get("agent", "?")
            resp = c.get("response", {})
            statement = resp.get("statement", "")
            discussion_text += f"\n【{agent}】\n{statement}\n"

        # 僅用 LLM 產出 summary 與 decision（不再由 LLM 判斷 resolution）
        if resolution == "agreed":
            user_prompt = f"""# 任務
以下議題經討論後以多數決判定為「達成共識」。請根據各方發言整理出摘要與具體決策內容。

# 議題資訊
標題: {topic.get('title', '')}
描述: {topic.get('description', '')}

# 各方討論內容
{discussion_text}

# 要求
- summary：總結討論內容與共識要點
- decision：具體可執行的決策內容

# 輸出 JSON
{{{{
    "summary": "總結討論內容與結論",
    "decision": "具體決策內容"
}}}}"""
        else:
            user_prompt = f"""# 任務
以下議題經討論後以多數決判定為「未達成共識」。請簡要總結各方討論重點（summary 即可，decision 留空）。

# 議題資訊
標題: {topic.get('title', '')}
描述: {topic.get('description', '')}

# 各方討論內容
{discussion_text}

# 輸出 JSON
{{{{
    "summary": "總結討論內容與各方立場",
    "decision": ""
}}}}"""

        messages = self.build_direct_messages(user_prompt)
        try:
            response = self.model.chat_json(messages)
            summary = response.get("summary", "")
            decision = response.get("decision", "") if resolution == "agreed" else ""
        except Exception as e:
            self.logger.warning(f"共識摘要 LLM 失敗: {e}")
            summary = "（多數決結果：%s；摘要產生失敗）" % resolution
            decision = ""

        return {
            "resolution": resolution,
            "summary": summary,
            "decision": decision,
        }

    # ===== 人類裁決 =====

    def prepare_human_options(self, topic: Dict, contributions: List[Dict]) -> Dict:
        discussion_text = ""
        for c in contributions:
            agent = c.get("agent", "?")
            resp = c.get("response", {})
            statement = resp.get("statement", "")
            discussion_text += f"\n【{agent}】\n{statement}\n"

        user_prompt = f"""# 任務
從以下議題討論中，篩選出 3 個最佳方案和 1 個折衷方案，供人類做最終裁決。

# 議題資訊
標題: {topic.get('title', '')}
描述: {topic.get('description', '')}

# 各方討論內容
{discussion_text}

# 要求
1. 從討論中提取 3 個最具體、可行性最高的方案
2. 另外設計 1 個折衷方案，結合各方可讓步的部分

# 輸出 JSON
{{{{
    "best_options": [
        {{{{
            "id": 1,
            "title": "方案標題",
            "description": "方案內容",
            "source": "提出此方案的 agent 名稱"
        }}}},
        {{{{
            "id": 2,
            "title": "方案標題",
            "description": "方案內容",
            "source": "提出此方案的 agent 名稱"
        }}}},
        {{{{
            "id": 3,
            "title": "方案標題",
            "description": "方案內容",
            "source": "提出此方案的 agent 名稱"
        }}}}
    ],
    "compromise": {{{{
        "id": 4,
        "title": "折衷方案標題",
        "description": "折衷方案內容",
        "rationale": "為何此方案能平衡各方需求"
    }}}}
}}}}"""

        messages = self.build_direct_messages(user_prompt)
        response = self.model.chat_json(messages)

        best = response.get("best_options", [])
        compromise = response.get("compromise", {})
        if compromise:
            compromise.setdefault("id", 4)

        return {"best_options": best, "compromise": compromise}

    # ===== 更新決策與衝突 =====

    def update_decisions(
        self, artifact: Dict[str, Any], round_discussions: List[Dict]
    ) -> Dict:
        discussions_text = json.dumps(round_discussions, ensure_ascii=False, indent=2)
        conflicts_text = json.dumps(
            artifact.get("conflicts", []), ensure_ascii=False, indent=2
        )

        user_prompt = f"""# 任務
彙整本輪所有議程的討論決策，並更新衝突的 label。

# 本輪討論結果
{discussions_text}

# 當前衝突列表
{conflicts_text}

# 規則
- 若衝突已在本輪解決，將 label 改為 Neutral
- 未解決的衝突保持 label 為 Conflict
- 輸出 conflicts 時請保留每個衝突原有的所有欄位（id、description、conflict_type、requirement_ids、stakeholder_names 等，依衝突類型保留），僅依討論結果更新 label
- 每個 new_decisions 項目請填寫 resolved_conflict_ids：此決策所解決的衝突 id 列表（若該議題討論解決了某個衝突則填其 CF-xx id，否則空陣列）
- 若本輪討論中有人指出「尚未列在當前衝突列表中的需求/立場衝突」（辨識漏報），請將該筆填入 new_conflicts，格式見下方。id 留空由系統指派。

# 輸出 JSON
{{{{
    "new_decisions": [...],
    "conflicts": [...],
    "new_conflicts": [
        {{{{
            "description": "衝突描述",
            "conflict_type": "Logical | Technical | Resource | Temporal | Data | State | Priority | Scope",
            "requirement_ids": ["R-01", "R-02"]
        }}}}
    ]
}}}}"""

        messages = self.build_direct_messages(user_prompt)
        response = self.model.chat_json(messages)

        return {
            "new_decisions": response.get("new_decisions", []),
            "conflicts": response.get("conflicts", artifact.get("conflicts", [])),
            "new_conflicts": response.get("new_conflicts", []),
        }


# ===== 議程執行層：依 action 呼叫 Mediator / store / Collect，維護本輪狀態 =====


class AgendaRunner:
    """執行議程相關動作，維護本輪 topics、topic_status、round_discussions、all_open_questions。"""

    def __init__(
        self,
        mediator_agent,
        registry,
        artifact: Dict[str, Any],
        round_num: int,
        config: Dict[str, Any],
        store,
        collect_module,
        logger,
    ):
        self.mediator = mediator_agent
        self.registry = registry
        self.artifact = artifact
        self.round_num = round_num
        self.config = config
        self.store = store
        self.collect = collect_module
        self.logger = logger

        self.topics: List[Dict] = []
        self.topic_status: Dict[str, Dict] = {}
        self.round_discussions: List[Dict] = []
        self.all_open_questions: List[Dict] = []
        self._topic_idx = 0

    def run(self, action: str, params: Optional[Dict] = None) -> Dict[str, Any]:
        params = params or {}
        obs = {"action": action, "result": None, "error": None}

        if action == "generate_agenda":
            skip = set()
            for disc in self.artifact.get("discussions", []):
                for td in disc.get("topics", []):
                    for sid in td.get("source_ids", []):
                        skip.add(sid)
            max_items = self.config.get("agenda_items", 5)
            latest_version = self.store.get_draft_version()
            draft_md = self.store.load_draft(latest_version) if latest_version >= 0 else None
            self.topics = self.mediator.generate_agenda(
                self.artifact,
                registry=self.registry,
                max_items=max_items,
                skip_source_ids=skip if skip else None,
                draft_markdown=draft_md,
            )
            self.topic_status = {
                t["id"]: {
                    "discussed": False,
                    "contributions": None,
                    "resolution": None,
                    "saved": False,
                }
                for t in self.topics
            }
            obs["result"] = {
                "topics": [
                    {
                        "id": t["id"],
                        "title": t["title"],
                        "category": t.get("category", ""),
                    }
                    for t in self.topics
                ],
                "count": len(self.topics),
            }
            return obs

        if action == "start_discussion":
            topic_id = params.get("topic_id")
            topic = self.get_topic(topic_id)
            if not topic:
                obs["error"] = f"topic_id 不存在: {topic_id}"
                return obs
            mode = topic.get("discussion_mode", "sequential")
            if mode == "simultaneous":
                contributions = self.mediator.moderate_simultaneous(
                    topic, self.registry, artifact=self.artifact
                )
            else:
                contributions = self.mediator.moderate_sequential(
                    topic, self.registry, artifact=self.artifact
                )
            stakeholders = self.artifact.get("stakeholders", [])
            oq_records = self.mediator.handle_open_questions(
                contributions, self.registry, stakeholders, artifact=self.artifact
            )
            for oq in oq_records:
                oq["topic_id"] = topic_id
            self.all_open_questions.extend(oq_records)
            self.topic_status[topic_id]["discussed"] = True
            self.topic_status[topic_id]["contributions"] = contributions
            obs["result"] = {
                "topic_id": topic_id,
                "contributions_count": len(contributions),
                "oq_count": len(oq_records),
            }
            return obs

        if action == "resolve_topic":
            topic_id = params.get("topic_id")
            topic = self.get_topic(topic_id)
            contributions = self.topic_status.get(topic_id, {}).get("contributions")
            if not topic or not contributions:
                obs["error"] = f"請先對 {topic_id} 執行 start_discussion"
                return obs
            resolution = self.mediator.synthesize_and_resolve(topic, contributions)
            self.topic_status[topic_id]["resolution"] = resolution
            obs["result"] = {
                "topic_id": topic_id,
                "resolution": resolution.get("resolution"),
                "summary": resolution.get("summary", ""),
            }
            return obs

        if action == "escalate_to_human":
            topic_id = params.get("topic_id")
            topic = self.get_topic(topic_id)
            contributions = self.topic_status.get(topic_id, {}).get("contributions")
            if not topic or not contributions:
                obs["error"] = f"請先對 {topic_id} 執行 start_discussion"
                return obs
            options = self.mediator.prepare_human_options(topic, contributions)
            resolution = self.collect.human_decision_on_topic(topic, options)
            self.topic_status[topic_id]["resolution"] = resolution
            obs["result"] = {
                "topic_id": topic_id,
                "resolution": "human_decision",
                "summary": str(resolution.get("decision", "")),
            }
            return obs

        if action == "save_topic":
            topic_id = params.get("topic_id")
            topic = self.get_topic(topic_id)
            st = self.topic_status.get(topic_id, {})
            contributions = st.get("contributions")
            resolution = st.get("resolution")
            if not topic or not contributions:
                obs["error"] = f"請先對 {topic_id} 執行 start_discussion"
                return obs
            if not resolution:
                resolution = self.mediator.synthesize_and_resolve(topic, contributions)
                self.topic_status[topic_id]["resolution"] = resolution
            self._topic_idx += 1
            meeting_md = self.mediator.generate_meeting_markdown(
                topic, contributions, resolution, round_num=self.round_num
            )
            meeting_filename = f"R{self.round_num}-M{self._topic_idx:02d}.md"
            self.store.save_markdown(meeting_md, meeting_filename)
            topic_record = {
                "id": topic.get("id"),
                "title": topic.get("title"),
                "description": topic.get("description", ""),
                "category": topic.get("category", ""),
                "participants": topic.get("participants", []),
                "discussion_mode": topic.get("discussion_mode", "sequential"),
                "speaking_order": topic.get("speaking_order", []),
                "source_ids": topic.get("source_ids", []),
            }
            self.round_discussions.append(
                {
                    "topic": topic_record,
                    "source_ids": topic.get("source_ids", []),
                    "contributions": [
                        {"agent": c.get("agent"), "response": c.get("response", {})}
                        for c in contributions
                    ],
                    "resolution": resolution,
                }
            )
            self.topic_status[topic_id]["saved"] = True
            obs["result"] = {"topic_id": topic_id, "filename": meeting_filename}
            return obs

        if action == "finish_round":
            obs["result"] = "round_complete"
            return obs

        obs["error"] = f"未知動作: {action}，可用: {AGENDA_ACTIONS}"
        return obs

    def get_topic(self, topic_id: Optional[str]) -> Optional[Dict]:
        if not topic_id:
            return None
        for t in self.topics:
            if t.get("id") == topic_id:
                return t
        return None

    def get_state_summary(self) -> Dict[str, Any]:
        status_list = []
        for tid, st in self.topic_status.items():
            status_list.append(
                {
                    "topic_id": tid,
                    "discussed": st.get("discussed", False),
                    "resolved": st.get("resolution") is not None,
                    "resolution": (st.get("resolution") or {}).get("resolution"),
                    "saved": st.get("saved", False),
                }
            )
        return {
            "round_num": self.round_num,
            "topics": [
                {"id": t["id"], "title": t["title"], "category": t.get("category", "")}
                for t in self.topics
            ],
            "topic_status": status_list,
            "round_discussions_length": len(self.round_discussions),
        }

    def get_round_discussions(self) -> List[Dict]:
        return self.round_discussions

    def get_all_open_questions(self) -> List[Dict]:
        return self.all_open_questions

    def get_agenda_snapshot(self) -> List[Dict]:
        return list(self.topics)
