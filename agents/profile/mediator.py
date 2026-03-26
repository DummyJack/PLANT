import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any, Optional
from agents.base import BaseAgent
from utils import (
    OUTPUT_LANG_EN,
    mediator_agenda_language_line,
    mediator_collect_line,
    mediator_human_options_line,
    mediator_prose_line,
    mediator_reasoning_line,
    mediator_summary_decision_line,
    mediator_unresolved_vote_task_line,
)

_AGENTS_DIR = Path(__file__).resolve().parent.parent
with open(_AGENTS_DIR / "agenda" / "agenda_types.json", "r", encoding="utf-8") as f:
    AGENDA_TYPES = tuple(json.load(f))
AGENDA_TYPE_IDS = [t["id"] for t in AGENDA_TYPES]
AGENDA_CATEGORY_LABEL = {t["id"]: t["label"] for t in AGENDA_TYPES}

AGENDA_ACTIONS = [
    "generate_agenda",
    "expand_agenda",
    "start_discussion",
    "resolve_topic",
    "escalate_to_human",
    "save_topic",
    "expert_review",
    "analyst_review",
    "modeler_review",
    "finish_round",
]


class MediatorAgent(BaseAgent):
    name = "mediator"

    system_prompt = """你是一個專業的需求調解主持人，負責主持需求討論會議。

核心職責：
1. 議程安排 — 分析需求與 Conflict，自行判斷應開哪些議程並排定優先順序
2. 討論主持 — 決定討論模式（逐一發言/同時發言），維持討論秩序
3. 共識促成 — 內部可辨識各方核心堅持與可協調空間；**表決前**須形成單一「主持人折衷方案」供投票；各參與者表決的是**是否採納該方案**，而非互評他人發言
4. 決策彙整 — 彙整每輪討論的決策並更新 Conflict 標記

核心原則：
- 中立客觀 — 不偏袒任何利害關係人，不提出自己的技術觀點
- 忠於資料 — 只根據已有的分析結果和討論內容做出綜合判斷
- 可追蹤性 — 每次主持決策都要能說明「為何現在做這一步」
- 無法共識時升級 — 無法達成共識時直接升級至人類裁決"""

    enabled_agenda_type_ids: Optional[List[str]] = None
    enable_human_escalation: bool = True

    def __init__(self, model, tools: Optional[list] = None, registry=None):
        super().__init__(model, tools=tools, registry=registry)

    def get_active_agenda_types(self):
        """回傳啟用的議程類型（tuple of dicts）和 id 列表。"""
        if self.enabled_agenda_type_ids is None:
            return AGENDA_TYPES, AGENDA_TYPE_IDS
        active = tuple(
            t for t in AGENDA_TYPES
            if t["id"] in self.enabled_agenda_type_ids
        )
        active_ids = [t["id"] for t in active]
        return active, active_ids

    def generate_agenda(
        self,
        artifact: Dict[str, Any],
        registry=None,
        max_items: Optional[int] = None,
        skip_source_ids: Optional[set] = None,
        draft_markdown: Optional[str] = None,
    ) -> List[Dict]:
        """由 Mediator LLM 根據最新需求草稿（優先）或專案摘要與已討論項目自行決定要開哪些議程。"""
        limit = max_items or 5
        exclude = {"mediator", "documentor"}
        if registry:
            registered = [n for n in registry.get_names() if n not in exclude]
        else:
            registered = ["user", "analyst", "expert", "modeler"]

        skip = skip_source_ids or set()
        context = self.build_agenda_context(
            artifact, skip, draft_markdown=draft_markdown
        )
        if not context.strip():
            self.logger.info("無足夠專案內容或草稿可供判斷議程")
            return []

        active_types, active_ids = self.get_active_agenda_types()
        types_text = json.dumps(active_types, ensure_ascii=False, indent=2)
        user_prompt = f"""# 任務
你是需求調解主持人。請根據下方「議程排程依據」與「已討論過項目」，自行判斷本輪應開哪些議程。
若有提供**最新需求草稿**，該草稿為**唯一依據**（含其中的需求表、Conflict、開放問題等章節——開放問題應已寫在草稿內）；請依草稿內文與 id 撰寫議程標題與描述。若僅有專案摘要（無草稿檔），則依該摘要判斷。
議程類型必須從下方「議程類型定義」中選擇，每項議程需決定：標題、描述、類型、參與者、討論模式、發言順序。

# 議程類型定義（category 必須為以下 id 之一）
{types_text}

# 議程排程依據
{context}

# 已在本輪或前輪討論過的項目（可略過或合併，勿重複開相同議題）
已討論 source_ids: {json.dumps(list(skip), ensure_ascii=False)}

# 可用 agent（participants 與 speaking_order 僅能使用此清單內名稱）
{json.dumps(registered, ensure_ascii=False)}

# 討論模式（discussion_mode）情境說明
- **sequential（逐一發言）**：適合需要「依序陳述並回應前一位」的議題。例如：Conflict 協調、決策取捨、開放問題釐清、需求取捨（NFR 競合）。後發言者會看到前面所有人的發言，可針對性回應，討論感較強。
- **simultaneous（同時發言）**：適合「先各自表態、再比較差異」的議題。例如：腦力激盪、多方案並列、各自提出對某議題的立場或建議，不需即時回應前一位。每人只看到議題與專案狀態，不看同輪其他人的發言。
請依議題性質選擇其一。

# 標題與描述撰寫要求（重要）
- **title（標題）**：一句話、具體、讓人一眼知道「要討論什麼」。要與本專案內容掛鉤，例如寫出涉及的對象、需求或 Conflict 重點，勿只寫類型名稱（如勿只寫「Conflict 討論」「需求取捨」）。
- **description（描述）**：簡短說明「為什麼要開這個議題、要解決什麼」。可提及相關需求 id 或 Conflict id，並用一兩句話說明討論重點。
- 範例：標題可為「管理員權限與一般使用者隱私的 Conflict 如何取捨」而非「Conflict 討論」；描述可為「CF-01 涉及 R-01 與 R-03，需協調兩方立場」。

# 議程類型與開題
- **conflict_resolution**：當有 label 為 Conflict 且未解決的項目時，應考慮開此類協調立場。
- **requirement_clarification**：當草稿（或摘要）中**開放問題**涉及需求模糊、須釐清含義時，可開此類；優先排最前。
- **open_question**：當草稿（或摘要）中有待處理開放問題時，可開此類或與 requirement_clarification 合併，依內容判斷。
- **new_requirement**：當草稿（或摘要）中出現「提出新功能、新限制、新例外情境、新需求」時，**應考慮開此類**，勿忽略；例如合規建議、討論中有人提議新功能等。
- **tradeoff**：當需求摘要中有多個 NFR（NFR-1、NFR-2…）或 Conflict 涉及效能、可用性、成本等非功能需求之間的競合取捨時，**應考慮開此類**。
- 其餘依專案狀態與優先順序判斷，無強制對應。

# 約束
- 最多開 {limit} 個議程。**需求釐清（requirement_clarification）類議題優先順序排最高**，請排在最前；其餘依你判斷的優先順序排列。
- 若無需討論的議題，請回傳空陣列
- category 只能是上述類型定義中的 id
- discussion_mode 依上表情境選擇 "sequential" 或 "simultaneous"
- 若有對應的 Conflict/需求/問題 id，請填在 source_ids 方便追蹤
- {mediator_agenda_language_line(self.output_language)}

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

        # requirement_clarification 一律置頂，確保最優先進入討論。
        prioritized_items = []
        normal_items = []
        for item in raw_items:
            if (item.get("category") or "").strip() == "requirement_clarification":
                prioritized_items.append(item)
            else:
                normal_items.append(item)
        ordered_items = (prioritized_items + normal_items)[:limit]

        agenda_items = []
        for idx, item in enumerate(ordered_items, 1):
            category = item.get("category", "")
            if category not in active_ids:
                category = active_ids[0] if active_ids else AGENDA_TYPE_IDS[0]
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
        self,
        artifact: Dict[str, Any],
        skip_source_ids: set,
        draft_markdown: Optional[str] = None,
    ) -> str:
        """有最新草稿時僅回傳該份 Markdown（開放問題等皆應已寫在草稿內）；否則回傳 artifact 結構化摘要作為後備。"""
        dm = (draft_markdown or "").strip()
        if dm:
            return "## 最新需求草稿（Markdown，議程唯一依據）\n" + dm

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
        requirements = artifact.get("requirements", [])
        if requirements:
            req_summary = [
                {"id": r.get("id"), "type": r.get("type", "FR")}
                for r in requirements
                if r.get("id")
            ]
            parts.append(
                "## 需求摘要（id 與 type，供判斷 NFR 競合等）\n"
                + json.dumps(req_summary, ensure_ascii=False, indent=2)
            )
        conflicts = [
            c
            for c in artifact.get("conflicts", [])
            if c.get("id", "") not in skip_source_ids
        ]
        if conflicts:
            parts.append(
                "## Conflict\n" + json.dumps(conflicts, ensure_ascii=False, indent=2)
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
        domain_research = artifact.get("feedback", {}).get("domain_research")
        if domain_research:
            parts.append(
                "## 領域研究（Phase 0）\n"
                + json.dumps(domain_research, ensure_ascii=False, indent=2)
            )

        if parts:
            return (
                "## 專案狀態摘要（無可用需求草稿檔時之後備依據）\n"
                + "\n\n".join(parts)
            )
        return ""

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

        escalate_hint = ""
        escalate_action = ""
        if self.enable_human_escalation:
            escalate_action = (
                "- escalate_to_human：某議題交由人類裁決。"
                "params: {{ \"topic_id\": \"T-01\" }}（須已 start_discussion）\n"
            )
            escalate_hint = "；若未共識可選 escalate_to_human 再 save_topic"

        user_prompt = f"""# 任務
你是需求調解主持人，正在主持本輪議程。請根據「當前狀態」與「上一動執行結果」，決定下一步要執行的動作。

# 可用動作與參數
- generate_agenda：產生本輪議程（無參數）。若 topics 已存在則勿重複呼叫。
- expand_agenda：擴充議程（無參數）。僅當 state.can_expand_agenda 為 true 時可選（本輪議題數未達上限且全部已 save）。**僅在確實有新增待討論項目**（如新開放問題、討論後新衝突、新需求）時才選擇擴充，勿為湊滿上限而開題。
- start_discussion：對某議題開始討論。params: {{ "topic_id": "T-01" }}（須為 state.topics 中存在的 id）
- resolve_topic：綜合某議題討論結果。params: {{ "topic_id": "T-01" }}（須已 start_discussion）
{escalate_action}- save_topic：儲存某議題的討論與決議。params: {{ "topic_id": "T-01" }}（須已 resolve 或 escalate）
- expert_review：讓領域專家進行自主研究與合規分析。params 選填：{{ "max_iterations": 1–5（此次複審最多幾輪） }}。適合在討論涉及法規/標準/安全後觸發。
- analyst_review：讓需求分析師進行自主分析（掃描討論、偵測 Conflict、更新需求）。params 選填：{{ "max_iterations": 1–5 }}。
- modeler_review：讓系統建模師進行自主模型更新與驗證。params 選填：{{ "max_iterations": 1–5 }}。
- finish_round：結束本輪議程。無參數。僅在已處理完所有要討論的議題並 save 後才可呼叫。

# 當前狀態
{state_text}

# 上一動執行結果（若為首輪則為空）
{obs_text}

# 規則
- 若 topics 為空，先呼叫 generate_agenda
- 對每個要討論的 topic 依序：start_discussion → resolve_topic（若共識則直接 save_topic{escalate_hint}）→ save_topic
- 當 **can_expand_agenda 為 true**（本輪議題數 < agenda_limit 且全部已 save）時，可選 **expand_agenda** 擴充議程至上限，或直接 **finish_round**。僅在確實有新增待討論項目時才選 expand_agenda，勿為湊滿上限而開題。
- 在 save_topic 後，可視討論內容觸發 expert_review / analyst_review / modeler_review（非每次必要，視需要決定）
- 若 pending_review_issues 有項目，可考慮為其開新議題或升級處理
- 全部處理完後呼叫 finish_round
- 一次只回傳一個動作
- {mediator_reasoning_line(self.output_language)}

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
            {
                "id": c.get("id"),
                "label": c.get("label"),
                "description": (c.get("description") or ""),
            }
            for c in artifact.get("conflicts", [])
        ]
        oqs = [
            {"from_agent": q.get("from_agent"), "question": (q.get("question") or "")}
            for q in artifact.get("open_questions", [])
            if q.get("status") != "answered"
        ]
        out = {
            "requirements": summary_reqs,
            "conflicts": conflicts,
            "open_questions": oqs,
        }
        feedback = artifact.get("feedback", {})
        if feedback:
            out["feedback"] = feedback
        models = artifact.get("system_models", {}).get("models", [])
        if models:
            out["system_models"] = [
                {"name": m.get("name"), "type": m.get("type")}
                for m in models
            ]
        return out

    def moderate_sequential(
        self, topic: Dict, registry, artifact: Optional[Dict[str, Any]] = None
    ) -> tuple:
        """逐一發言；輪到某人前先讓他即時回答指向他的問題，再發言（可依問答調整立場）。回傳 (contributions, oq_records)。"""
        contributions = []
        oq_records = []
        speaking_order = topic.get("speaking_order") or topic.get("participants") or []
        if not speaking_order:
            self.logger.warning(
                f"[{topic['id']}] speaking_order 與 participants 皆為空，無人可發言"
            )
            return (contributions, oq_records)
        title = topic.get("title", "") or "（無標題）"
        cat_label = AGENDA_CATEGORY_LABEL.get(topic.get("category", ""), topic.get("category", ""))
        self.logger.info(f"[{topic['id']}] {title} [{cat_label}] — 逐一發言: {' → '.join(speaking_order)}")

        snapshot = self.build_artifact_snapshot(artifact)
        for agent_name in speaking_order:
            agent = registry.get(agent_name)
            if not agent:
                self.logger.warning(f"Agent '{agent_name}' 未註冊，跳過")
                continue
            # 有人提問給此 agent 時，先即時回答，再發言（發言時可依問答調整）
            answer_contribs, answer_oq = self.answer_questions_for_agent(
                contributions, agent_name, registry, snapshot, artifact
            )
            contributions.extend(answer_contribs)
            oq_records.extend(answer_oq)
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
            # 提問者依回答可補充或調整發言
            follow_ups = self.get_follow_ups_after_answers(
                contributions, answer_contribs, registry, snapshot, artifact
            )
            contributions.extend(follow_ups)

        return (contributions, oq_records)

    def respond_one_simultaneous(
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
        participants = topic.get("participants") or []
        if not participants:
            self.logger.warning(
                f"[{topic.get('id', '?')}] participants 為空，無人可發言"
            )
            return []
        title = topic.get("title", "") or "（無標題）"
        cat_label = AGENDA_CATEGORY_LABEL.get(topic.get("category", ""), topic.get("category", ""))
        self.logger.info(f"[{topic['id']}] {title} [{cat_label}] — 同時發言: {', '.join(participants)}")

        snapshot = self.build_artifact_snapshot(artifact)
        max_workers = min(len(participants), 6)
        contributions_by_agent = {}

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(
                    self.respond_one_simultaneous,
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

    def get_questions_to_agent(
        self, contributions: List[Dict], to_agent_name: str
    ) -> List[Dict]:
        """從 contributions 中蒐集所有指向 to_agent_name 的 open_questions。"""
        out = []
        for c in contributions:
            agent_name = c.get("agent", "")
            resp = c.get("response", {}) if isinstance(c.get("response"), dict) else {}
            for q in resp.get("open_questions", []):
                if isinstance(q, str):
                    q = {"question": q, "to": "user"}
                elif not isinstance(q, dict):
                    continue
                to_agent = q.get("to", "user")
                if to_agent != to_agent_name:
                    continue
                out.append({
                    "from_agent": agent_name,
                    "to_agent": to_agent,
                    "question": q.get("question", ""),
                })
        return [q for q in out if q.get("question")]

    def answer_questions_for_agent(
        self,
        contributions: List[Dict],
        agent_name: str,
        registry,
        snapshot: Dict,
        artifact: Optional[Dict[str, Any]],
    ) -> tuple:
        """讓 agent_name 即時回答目前 contributions 中指向他的問題。回傳 (要 append 的 contributions, oq_records)。"""
        questions = self.get_questions_to_agent(contributions, agent_name)
        if not questions:
            return ([], [])
        target_agent = registry.get(agent_name) if registry else None
        if not target_agent:
            return ([], [{**q, "status": "deferred"} for q in questions])
        added = []
        oq_records = []
        current_contributions = list(contributions)
        for q_record in questions:
            try:
                q_topic = {
                    "id": "OQ",
                    "title": f"回答 {q_record['from_agent']} 的問題",
                    "description": (
                        f"{q_record['question']}\n\n"
                        "（請簡要針對此問題回答；若前面發言已涵蓋可寫「如前述」或只補充重點。"
                        "回答後若尚未發言，可在輪到你發言時依此問答補充或微調立場。）"
                    ),
                }
                response = target_agent.respond_to_topic(
                    q_topic,
                    previous_responses=current_contributions,
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
                    "agent": agent_name,
                    "response": resp,
                    "is_reply": True,
                }
                added.append(contrib)
                current_contributions.append(contrib)
                oq_records.append({**q_record, "status": "answered", "answer": answer})
            except Exception:
                oq_records.append({**q_record, "status": "deferred"})
        return (added, oq_records)

    def get_follow_ups_after_answers(
        self,
        contributions: List[Dict],
        answer_contribs: List[Dict],
        registry,
        snapshot: Dict,
        artifact: Optional[Dict[str, Any]],
    ) -> List[Dict]:
        """回答完成後，讓提問者依回答簡要補充或調整發言。"""
        if not answer_contribs:
            return []
        asker_qa: Dict[str, List[tuple]] = {}
        for c in answer_contribs:
            resp = c.get("response", {}) if isinstance(c.get("response"), dict) else {}
            from_agent = resp.get("reply_to_agent")
            if not from_agent:
                continue
            q = resp.get("reply_to_question", "")
            ans = resp.get("statement") or resp.get("content", "")
            asker_qa.setdefault(from_agent, []).append((q, ans))
        result = []
        for asker_name, qa_list in asker_qa.items():
            agent = registry.get(asker_name) if registry else None
            if not agent:
                continue
            desc_parts = [
                f"你問：{q}\n對方回答：{a}" for q, a in qa_list
            ]
            follow_topic = {
                "id": "OQ-follow",
                "title": "依回答補充或調整發言",
                "description": (
                    "\n\n".join(desc_parts)
                    + "\n\n請依上述回答簡要說明你是否要補充或調整你的立場；若無需補充請寫「無需補充」。"
                ),
            }
            try:
                response = agent.respond_to_topic(
                    follow_topic,
                    previous_responses=contributions,
                    artifact_snapshot=snapshot,
                )
                resp = (
                    response
                    if isinstance(response, dict)
                    else {"content": str(response)}
                )
                resp = dict(resp)
                result.append({
                    "agent": asker_name,
                    "response": resp,
                    "is_follow_up": True,
                })
            except Exception:
                pass
        return result

    def handle_open_questions(
        self,
        contributions: List[Dict],
        registry,
        stakeholders: List[Dict],
        artifact: Optional[Dict[str, Any]] = None,
    ) -> List[Dict]:
        """將 open_questions 依 to 欄位路由到對應 agent 回答（用於 simultaneous 模式：所有人發言後再集中回答）。"""
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

    def propose_compromise_for_vote(
        self,
        topic: Dict,
        contributions: List[Dict],
    ) -> Dict[str, str]:
        """討論結束後由主持人整理單一折衷方案，作為後續投票的唯一標的。"""
        main_contribs = [c for c in contributions if not c.get("is_reply", False)]
        discussion_text = ""
        for c in main_contribs:
            agent = c.get("agent", "?")
            statement = (c.get("response") or {}).get("statement", "")
            discussion_text += f"\n【{agent}】\n{statement}\n"

        if self.output_language == OUTPUT_LANG_EN:
            lang = "Write title, description, and rationale in English."
        else:
            lang = "請以繁體中文撰寫標題、方案內容與理由。"

        user_prompt = f"""你是需求會議的主持人。請在完整閱讀各方發言後，整理出**一個**具體的折衷方案（單一決議 package），
供各參與者下一步投票表決「是否同意採納」；**不要**改成羅列多套互斥選項讓人各選各的。

# 議題
標題: {topic.get("title", "")}
描述: {topic.get("description", "")}

# 各方發言
{discussion_text or "（無發言紀錄）"}

# 要求
- 方案須可執行、條文明確，並簡要說明如何銜接各方立場
- {lang}

# 輸出 JSON
{{
    "title": "方案短標題",
    "description": "方案具體內容",
    "rationale": "為何此方案能平衡各方關切"
}}
只輸出 JSON。"""
        messages = self.build_direct_messages(user_prompt)
        try:
            response = self.model.chat_json(messages)
            title = (response.get("title") or "").strip()
            description = (response.get("description") or "").strip()
            rationale = (response.get("rationale") or "").strip()
            if not description and not title:
                raise ValueError("empty compromise")
            return {
                "title": title or "主持人折衷方案",
                "description": description,
                "rationale": rationale,
            }
        except Exception as e:
            self.logger.warning("主持人折衷方案產生失敗: %s", e)
            return {"title": "", "description": "", "rationale": ""}

    def collect_final_votes(
        self,
        topic: Dict,
        contributions: List[Dict],
        registry,
        artifact: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """在完整討論結束後，先由主持人提出折衷方案，再向各參與者收集對該方案之投票。

        回傳 { "votes": {...}, "mediator_compromise": { title, description, rationale } }
        """
        main_contribs = [c for c in contributions if not c.get("is_reply", False)]

        mediator_compromise: Dict[str, str]
        if main_contribs:
            mediator_compromise = self.propose_compromise_for_vote(topic, contributions)
        else:
            mediator_compromise = {"title": "", "description": "", "rationale": ""}

        voters = topic.get("speaking_order") or topic.get("participants") or []
        if not voters:
            # fallback：以實際有主發言的 agent 順序作為投票者
            voters = [c.get("agent") for c in main_contribs if c.get("agent")]

        snapshot = self.build_artifact_snapshot(artifact)
        votes: Dict[str, str] = {}
        for agent_name in voters:
            agent = registry.get(agent_name) if registry else None
            if not agent:
                self.logger.warning(f"投票階段找不到 Agent '{agent_name}'，略過")
                continue
            try:
                if hasattr(agent, "vote_on_topic"):
                    vote_resp = agent.vote_on_topic(
                        topic,
                        previous_responses=main_contribs,
                        artifact_snapshot=snapshot,
                        mediator_compromise=mediator_compromise,
                    )
                    v = (vote_resp.get("vote") or "").strip().lower()
                    votes[agent_name] = "agreed" if v == "agreed" else "unresolved"
                else:
                    votes[agent_name] = "unresolved"
            except Exception as e:
                self.logger.warning(f"  {agent_name} 最終投票失敗，視為 unresolved: {e}")
                votes[agent_name] = "unresolved"
        return {"votes": votes, "mediator_compromise": mediator_compromise}

    @staticmethod
    def extract_traceability_ids(topic: Dict, contributions: List[Dict], resolution: Dict) -> List[str]:
        """從 source_ids 與討論/決議文字抓出可追溯 id（如 FR-1、NFR-2、CF-01）。"""
        ids = set()
        for sid in topic.get("source_ids", []) or []:
            if isinstance(sid, str) and sid.strip():
                ids.add(sid.strip())
        texts = [
            topic.get("title", ""),
            topic.get("description", ""),
            resolution.get("summary", ""),
            resolution.get("decision", ""),
        ]
        for c in contributions:
            resp = c.get("response", {}) if isinstance(c.get("response"), dict) else {}
            texts.append(resp.get("statement", ""))
        blob = "\n".join(t for t in texts if t)
        for m in re.findall(r"\b(?:FR|NFR|R|CF)-[A-Za-z0-9-]+\b", blob):
            ids.add(m)
        return sorted(ids)

    def build_design_rationale_entry_context(
        self,
        topic: Dict,
        contributions: List[Dict],
        resolution: Dict,
        topic_open_questions: List[Dict],
        round_num: int,
    ) -> Dict[str, Any]:
        """將單一議題討論結果整理為 Design Rationale 單筆上下文。"""
        main_contribs = [c for c in contributions if not c.get("is_reply", False)]
        statements = []
        for c in main_contribs:
            resp = c.get("response", {}) if isinstance(c.get("response"), dict) else {}
            st = (resp.get("statement") or "").strip()
            if st:
                statements.append({"agent": c.get("agent", "?"), "statement": st})

        unresolved_oq = []
        for q in topic_open_questions:
            status = q.get("status", "")
            if status == "answered":
                continue
            unresolved_oq.append(
                {
                    "from_agent": q.get("from_agent", ""),
                    "to_agent": q.get("to_agent", ""),
                    "question": q.get("question", ""),
                    "status": status or "deferred",
                }
            )

        return {
            "topic": {
                "id": topic.get("id", ""),
                "title": topic.get("title", ""),
                "description": topic.get("description", ""),
                "category": topic.get("category", ""),
                "category_label": AGENDA_CATEGORY_LABEL.get(topic.get("category", ""), topic.get("category", "")),
                "discussion_mode": topic.get("discussion_mode", "sequential"),
                "participants": topic.get("participants", []) or topic.get("speaking_order", []),
                "source_ids": topic.get("source_ids", []),
            },
            "discussion": {
                "statements": statements,
                "open_issues": unresolved_oq,
            },
            "resolution": {
                "resolution": resolution.get("resolution", ""),
                "summary": resolution.get("summary", ""),
                "decision": resolution.get("decision", ""),
                "votes": resolution.get("votes", {}),
                "votes_summary": resolution.get("votes_summary", ""),
            },
            "traceability_ids": self.extract_traceability_ids(topic, contributions, resolution),
            "metadata": {
                "round": round_num,
                "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            },
        }

    def generate_design_rationale_entry(self, topic_context: Dict[str, Any]) -> str:
        """生成單一議題的 Design Rationale 章節。"""
        context_text = json.dumps(topic_context, ensure_ascii=False, indent=2)
        user_prompt = f"""# 任務
請根據以下單一議題的討論上下文，產出一段 Design Rationale 章節（Markdown）。

# 議題上下文
{context_text}

# 章節結構（必須完整）
請以「## [topic_id] [topic_title]」作為章節標題，並依序包含以下小節：
1. ### 問題與背景 (Issue / Context)
2. ### 設計目標 (Goals / Objectives)
3. ### 替代方案 (Alternatives)
4. ### 評估準則 (Evaluation Criteria)
5. ### 方案評估 (Evaluation)
6. ### 最終決策 (Decision)
7. ### 決策理由 (Justification)
8. ### 取捨與影響 (Trade-offs & Impacts)
9. ### 未決議事項 (Open Issues)
10. ### 需求追蹤 (Traceability)
11. ### 會議資訊 (Metadata)

# 重要規則
- 僅根據上下文內容整理，禁止捏造不存在的決策、方案或需求。
- 若某小節資訊不足，請明確寫「待補」。
- {mediator_prose_line(self.output_language)}
- 「替代方案」與「方案評估」至少列出上下文中有跡可循的選項；若無法辨識則寫「待補」。
- 「需求追蹤」需優先使用 traceability_ids 與 source_ids。
- 「會議資訊」至少包含：Round、議題 id、參與者、投票結果、產生時間。
- 只輸出該議題章節 Markdown，勿使用程式碼區塊。"""

        messages = self.build_direct_messages(user_prompt)
        raw = self.model.chat(messages)
        return (raw or "").strip()

    def generate_design_rationale(self, topic_context: Dict[str, Any]) -> str:
        """初次建立 design_rationale.md。"""
        topic_id = (topic_context.get("topic") or {}).get("id", "")
        entry = self.generate_design_rationale_entry(topic_context)
        header = "# Design Rationale\n\n"
        header += "> 本文件由 Mediator 於每個議題討論完成後持續維護與更新。\n\n"
        if not entry:
            entry = f"## {topic_id or 'T-??'}\n\n待補\n"
        return header + entry

    def update_design_rationale(self, existing_md: str, topic_context: Dict[str, Any]) -> str:
        """既有 design_rationale.md 追加單一議題章節。"""
        base = (existing_md or "").rstrip()
        entry = self.generate_design_rationale_entry(topic_context)
        if not entry:
            topic_id = (topic_context.get("topic") or {}).get("id", "")
            entry = f"## {topic_id or 'T-??'}\n\n待補\n"
        if not base:
            return self.generate_design_rationale(topic_context)
        return f"{base}\n\n---\n\n{entry}"

    def generate_meeting_markdown(
        self,
        topic: Dict,
        contributions: List[Dict],
        resolution: Dict,
        round_num: int = 0,
    ) -> str:
        mode = topic.get("discussion_mode", "sequential")
        participants = (
            topic.get("participants")
            or topic.get("speaking_order")
            or []
        )
        category = topic.get("category", "")
        cat_label = AGENDA_CATEGORY_LABEL.get(category, category)
        description = topic.get("description", "")

        md = f"# {topic.get('title', '')}\n\n"
        md += f"- **Round**: {round_num}\n"
        md += f"- **Category**: {cat_label}\n"
        if description:
            md += f"- **Description**: {description}\n"
        summary = resolution.get("summary", "")
        decision = resolution.get("decision", "")
        resolution_status = resolution.get("resolution", "")
        md += f"- **Summary**: {summary}\n"
        if decision:
            md += f"- **Decision**: {decision}\n"
        if resolution_status:
            md += f"- **Resolution**: {resolution_status}\n"
        md += f"- **Participants**: {', '.join(participants) if participants else '（無參與者）'}\n"
        md += f"- **Discussion mode**: {mode}\n"

        votes = resolution.get("votes", {}) or {}
        votes_line = [f"{agent}: {vote}" for agent, vote in votes.items()]
        if votes_line:
            md += f"- **Votes**: {', '.join(votes_line)}\n"
        md += "\n"

        mc = resolution.get("mediator_compromise") or {}
        mc_title = (mc.get("title") or "").strip()
        mc_desc = (mc.get("description") or "").strip()
        mc_rat = (mc.get("rationale") or "").strip()
        if mc_title or mc_desc:
            md += "## 主持人折衷方案（表決標的）\n\n"
            if mc_title:
                md += f"**{mc_title}**\n\n"
            if mc_desc:
                md += f"{mc_desc}\n\n"
            if mc_rat:
                md += f"*理由*: {mc_rat}\n\n"

        main_contribs = [c for c in contributions if not c.get("is_reply", False)]
        md += "## 討論內容\n\n"
        if not main_contribs:
            md += "（本議題無人發言）\n\n"
        else:
            for c in main_contribs:
                agent = c.get("agent", "?")
                resp = c.get("response", {})
                statement = resp.get("statement", "")
                md += f"### {agent}\n\n"
                if statement:
                    md += f"{statement}\n\n"

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
            md += "## 開放問題\n\n"
            for i, (from_agent, question, reply_agent, answer) in enumerate(oq_pairs):
                if i > 0:
                    md += "\n---\n\n"
                md += f"**{from_agent}** 問 **{reply_agent}**: {question}\n\n"
                md += f"**{reply_agent}**: {answer}\n\n"

        return md

    def synthesize_and_resolve(
        self,
        topic: Dict,
        contributions: List[Dict],
        final_votes: Optional[Dict[str, str]] = None,
        mediator_compromise: Optional[Dict[str, Any]] = None,
    ) -> Dict:
        """依最終投票（final_votes）以多數決決定是否達成共識；agreed 時由 LLM 產出 summary 與 decision。"""
        if not contributions:
            self.logger.warning(
                f"  [{topic.get('id', '?')}] 無發言紀錄，直接標記為 unresolved"
            )
            return {
                "resolution": "unresolved",
                "summary": "本議題無人發言，無法進行決議。",
                "decision": "",
                "votes": {},
                "votes_summary": "無投票（0/0）",
                "mediator_compromise": {"title": "", "description": "", "rationale": ""},
            }

        votes_by_agent = {}
        if final_votes:
            for agent, vote in final_votes.items():
                v = (vote or "").strip().lower()
                votes_by_agent[agent] = "agreed" if v == "agreed" else "unresolved"
        # 未傳入 final_votes 時無票可計，resolution 將為 unresolved

        votes_list = list(votes_by_agent.values())

        agreed_count = sum(1 for v in votes_list if v == "agreed")
        n = len(votes_list)
        unresolved_count = n - agreed_count
        # 多數決：同意數過半才為 agreed，否則 unresolved
        resolution = (
            "agreed" if n > 0 and agreed_count > unresolved_count else "unresolved"
        )

        discussion_text = ""
        for c in contributions:
            agent = c.get("agent", "?")
            resp = c.get("response", {})
            statement = resp.get("statement", "")
            discussion_text += f"\n【{agent}】\n{statement}\n"

        mc = mediator_compromise or {}
        mc_title = (mc.get("title") or "").strip()
        mc_desc = (mc.get("description") or "").strip()
        mc_rat = (mc.get("rationale") or "").strip()
        compromise_block = ""
        if mc_desc or mc_title:
            compromise_block = f"""# 表決標的（主持人折衷方案）
標題: {mc_title}
內容: {mc_desc}
說明: {mc_rat}

"""

        # 僅用 LLM 產出 summary 與 decision（不再由 LLM 判斷 resolution）
        if resolution == "agreed":
            user_prompt = f"""# 任務
以下議題經討論後，各參與者已對「主持人折衷方案」投票，且多數決判定為「達成共識」。請根據該方案與各方發言整理摘要與具體決策內容；decision 應與通過之主持人方案主旨一致。

# 議題資訊
標題: {topic.get('title', '')}
描述: {topic.get('description', '')}

{compromise_block}# 各方討論內容
{discussion_text}

# 要求
- summary：總結討論內容與共識要點
- decision：具體可執行的決策內容
- {mediator_summary_decision_line(self.output_language)}

# 輸出 JSON
{{{{
    "summary": "總結討論內容與結論",
    "decision": "具體決策內容"
}}}}"""
        else:
            user_prompt = f"""# 任務
{mediator_unresolved_vote_task_line(self.output_language)}

# 議題資訊
標題: {topic.get('title', '')}
描述: {topic.get('description', '')}

{compromise_block}# 各方討論內容
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
            if self.output_language == OUTPUT_LANG_EN:
                summary = f"(Majority outcome: {resolution}; summary generation failed)"
            else:
                summary = "（多數決結果：%s；摘要產生失敗）" % resolution
            decision = ""

        return {
            "resolution": resolution,
            "summary": summary,
            "decision": decision,
            "votes": votes_by_agent,
            "votes_summary": f"{agreed_count} agreed, {unresolved_count} unresolved",
            "mediator_compromise": {
                "title": mc_title,
                "description": mc_desc,
                "rationale": mc_rat,
            },
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
2. 另外設計 1 個折衷方案，整合各方願意放寬或調整的面向（描述時無須使用「可讓步」等字眼）
3. {mediator_human_options_line(self.output_language)}

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

    # ===== 更新決策與 Conflict =====

    def update_decisions(
        self, artifact: Dict[str, Any], round_discussions: List[Dict]
    ) -> Dict:
        discussions_text = json.dumps(round_discussions, ensure_ascii=False, indent=2)
        conflicts_text = json.dumps(
            artifact.get("conflicts", []), ensure_ascii=False, indent=2
        )

        user_prompt = f"""# 任務
彙整本輪所有議程的討論決策，並更新 Conflict 的 label。

# 本輪討論結果
{discussions_text}

# 當前 Conflict 列表
{conflicts_text}

# 規則
- 若本輪討論認定某筆 Conflict 已解決（非 Conflict），將該筆 label 改為 Neutral
- 若本輪討論認定某筆 Neutral 實為 Conflict，將該筆 label 改為 Conflict（誤判修正與升級皆經討論 + 本步驟）
- 其餘依討論結果維持原 label。輸出 conflicts 時請保留每筆原有的所有欄位（id、description、conflict_type、requirement_ids、stakeholder_names 等），僅依討論結果更新 label
- 每個 new_decisions 項目請填寫 resolved_conflict_ids：此決策所解決的 Conflict id 列表（若該議題討論解決了某個 Conflict 則填其 CF-xx id，否則空陣列）
- 若本輪討論中有人指出「尚未列在當前 Conflict 列表中的需求/立場 Conflict」（辨識漏報），請將該筆填入 new_conflicts，格式見下方。id 留空由系統指派。
- {mediator_collect_line(self.output_language)}

# 輸出 JSON
{{{{
    "new_decisions": [...],
    "conflicts": [...],
    "new_conflicts": [
        {{{{
            "description": "Conflict 描述",
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
