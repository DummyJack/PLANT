import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any, Optional
from agents.base import BaseAgent
from utils import (
    mediator_agenda_language_line,
    mediator_collect_line,
    mediator_human_options_line,
    mediator_prose_line,
    mediator_reasoning_line,
    mediator_summary_decision_line,
    mediator_unresolved_vote_task_line,
)
from utils import normalize_agenda_topic

AGENTS_DIR = Path(__file__).resolve().parent.parent
with open(AGENTS_DIR / "agenda" / "agenda_types.json", "r", encoding="utf-8") as f:
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

    system_prompt = """你是需求調解主持人，負責 triage、主持討論、形成收斂結果。

規則：
1. 根據 proposal pool、queue、open conflicts、open questions 與本輪容量分流議題；不得憑空新增議題來源。
2. 優先走 direct clarification / direct apply / human decision；只有真的需要協調時才進 formal meeting。
3. 討論前形成單一主持人折衷方案，投票只針對該方案是否採納。
4. 保持中立，不直接編寫 requirement；輸出可追蹤的 topic_result。
5. 無法形成可接受折衷方案時，升級至人類裁決。"""

    enabled_agenda_type_ids: Optional[List[str]] = None
    enable_human_escalation: bool = True

    def __init__(
        self,
        model,
        tools: Optional[list] = None,
        registry=None,
        project_config=None,
    ):
        super().__init__(
            model, tools=tools, registry=registry, project_config=project_config
        )

    # ===== Plan: agenda & triage =====

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

    def classify_topic_proposal(
        self,
        proposal: Dict[str, Any],
    ) -> Dict[str, Any]:
        """依 proposal schema 與類型規則決定分流：正式會議、定向問答、直接處理或人工裁決。"""
        category = (proposal.get("category") or "").strip()
        impact = (proposal.get("impact_level") or proposal.get("priority_hint") or "medium").strip().lower()
        requires_multi_party = bool(proposal.get("requires_multi_party"))
        blocks_decision = bool(proposal.get("blocks_decision"))
        needs_human = bool(proposal.get("needs_human"))
        routing_preference = (proposal.get("routing_preference") or "formal_meeting").strip()
        source_ids = [s for s in (proposal.get("source_ids") or []) if str(s).strip()]
        participants = [p for p in (proposal.get("participants") or []) if str(p).strip()]

        action = "direct_clarification"
        reason = "queue_first_default"
        if needs_human or routing_preference == "human_decision":
            action = "human_decision"
            reason = "proposal_marked_for_human"
        elif routing_preference in ("direct_apply", "direct_clarification"):
            action = routing_preference
            reason = "proposal_requested_direct_routing"
        elif category == "open_question":
            if requires_multi_party or blocks_decision or impact == "high" or int(proposal.get("deferred_rounds") or 0) >= 1:
                action = "formal_meeting"
                reason = "open_question_blocks_decision"
            else:
                action = "direct_clarification"
                reason = "single_point_open_question"
        elif category == "new_requirement":
            if impact in {"low", "medium"} and not requires_multi_party and not blocks_decision and len(source_ids) <= 1:
                action = "direct_clarification"
                reason = "new_requirement_needs_scope_check_only"
            else:
                action = "formal_meeting"
                reason = "new_requirement_affects_scope"
        elif category == "conflict_discussion":
            action = "formal_meeting"
            reason = "conflict_discussion_requires_group_recheck"
        elif category == "tradeoff":
            if requires_multi_party or blocks_decision or impact == "high":
                action = "formal_meeting"
                reason = "tradeoff_requires_group_decision"
            else:
                action = "direct_clarification"
                reason = "tradeoff_not_material_yet"
        return {"action": action, "reason": reason}

    def triage_topic_proposals(
        self,
        proposal_pool: List[Dict[str, Any]],
        *,
        active_type_ids: List[str],
        registered: List[str],
        max_items: int,
        skip_source_ids: Optional[set] = None,
    ) -> Dict[str, Any]:
        skip = skip_source_ids or set()
        dedup = []
        seen = set()
        for p in proposal_pool:
            if not isinstance(p, dict):
                continue
            title = (p.get("title") or "").strip()
            category = (p.get("category") or "").strip()
            src = tuple(sorted([str(s) for s in (p.get("source_ids") or []) if str(s).strip()]))
            key = ((p.get("proposal_id") or "").strip(), title, category, src)
            if not title or key in seen:
                continue
            if src and all(s in skip for s in src):
                continue
            seen.add(key)
            dedup.append(p)
        if not dedup:
            return {"items": [], "backlog": [], "meta": {"input_count": 0, "selected_count": 0, "deferred_count": 0}}

        pri = {"high": 0, "medium": 1, "low": 2}
        ordered = sorted(
            dedup,
            key=lambda x: (
                pri.get((x.get("priority_hint") or "medium").strip().lower(), 1),
                -int(x.get("deferred_rounds") or 0),
                int(x.get("round") or 0),
                (x.get("proposal_id") or ""),
            ),
        )
        formal_candidates = []
        direct_clarifications = []
        direct_apply = []
        human_queue = []
        for p in ordered:
            route = self.classify_topic_proposal(p)
            row = dict(p)
            row["triage_action"] = route["action"]
            row["triage_reason"] = route["reason"]
            if route["action"] == "formal_meeting":
                formal_candidates.append(row)
            elif route["action"] == "direct_clarification":
                direct_clarifications.append(row)
            elif route["action"] == "direct_apply":
                direct_apply.append(row)
            elif route["action"] == "human_decision":
                human_queue.append(row)

        selected = formal_candidates[:max_items]
        deferred = []
        for p in formal_candidates[max_items:]:
            row = dict(p)
            row["deferred_rounds"] = int(row.get("deferred_rounds") or 0) + 1
            row["deferred_reason"] = "round_capacity_limit"
            deferred.append(row)

        items = []
        for p in selected:
            category = (p.get("category") or "").strip()
            if category not in active_type_ids:
                category = active_type_ids[0] if active_type_ids else AGENDA_TYPE_IDS[0]
            normalized = normalize_agenda_topic(
                {
                    "title": (p.get("title") or "待討論議題").strip(),
                    "description": (p.get("description") or "").strip(),
                    "category": category,
                    "participants": p.get("participants", []),
                    "discussion_mode": p.get("discussion_mode", "sequential"),
                    "speaking_order": p.get("speaking_order", []),
                    "source_ids": p.get("source_ids", []),
                    "source_proposal_ids": [p.get("proposal_id")] if p.get("proposal_id") else [],
                    "triage_action": "formal_meeting",
                },
                allowed_categories=active_type_ids or AGENDA_TYPE_IDS,
                registered_agents=registered,
                index=len(items) + 1,
            )
            if normalized:
                items.append(normalized)
        return {
            "items": items,
            "backlog": deferred,
            "direct_clarifications": direct_clarifications,
            "direct_apply": direct_apply,
            "human_queue": human_queue,
            "meta": {
                "input_count": len(ordered),
                "formal_candidate_count": len(formal_candidates),
                "selected_count": len(items),
                "deferred_count": len(deferred),
                "direct_clarification_count": len(direct_clarifications),
                "direct_apply_count": len(direct_apply),
                "human_queue_count": len(human_queue),
                "round_capacity_limit": max_items,
            },
        }

    def generate_agenda(
        self,
        artifact: Dict[str, Any],
        registry=None,
        max_items: Optional[int] = None,
        skip_source_ids: Optional[set] = None,
        draft_markdown: Optional[str] = None,
        proposal_pool: Optional[List[Dict[str, Any]]] = None,
    ) -> List[Dict]:
        """由 Mediator LLM 根據最新需求草稿（優先）或專案摘要與已討論項目自行決定要開哪些議程。"""
        limit = max_items or 5
        exclude = {"mediator", "documentor"}
        if registry:
            registered = [n for n in registry.get_names() if n not in exclude]
        else:
            registered = ["user", "analyst", "expert", "modeler"]

        active_types, active_ids = self.get_active_agenda_types()
        types_text = json.dumps(active_types, ensure_ascii=False, indent=2)
        skip = skip_source_ids or set()
        context = ""
        raw_items = []
        if proposal_pool is not None:
            triage = self.triage_topic_proposals(
                proposal_pool or [],
                active_type_ids=active_ids,
                registered=registered,
                max_items=limit,
                skip_source_ids=skip,
            )
            raw_items = triage.get("items", [])
            artifact["proposal_backlog"] = triage.get("backlog", [])
            artifact["clarification_queue"] = triage.get("direct_clarifications", [])
            artifact["direct_apply_queue"] = triage.get("direct_apply", [])
            artifact["human_decision_queue"] = triage.get("human_queue", [])
            artifact["proposal_triage_meta"] = {
                **(triage.get("meta", {}) or {}),
                "mode": "proposal_pool",
            }
            self.logger.info(
                "Triage：%s 筆 → 選 %s 遞延 %s（上限 %s）",
                artifact["proposal_triage_meta"].get("input_count", 0),
                artifact["proposal_triage_meta"].get("selected_count", 0),
                artifact["proposal_triage_meta"].get("deferred_count", 0),
                artifact["proposal_triage_meta"].get("round_capacity_limit", limit),
            )
        else:
            context = self.build_agenda_context(
                artifact, skip, draft_markdown=draft_markdown
            )
            if not context.strip():
                self.logger.info("無足夠內容產生議程")
                return []
        if proposal_pool is not None and not raw_items:
            self.logger.info("proposal_pool 無可用議題，略過本輪 agenda")
            return []

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
- **sequential（逐一發言）**：適合需要「依序陳述並回應前一位」的議題。例如：衝突再審查、決策取捨、開放問題釐清、需求取捨（NFR 競合）。後發言者會看到前面所有人的發言，可針對性回應，討論感較強。
- **simultaneous（同時發言）**：適合「先各自表態、再比較差異」的議題。例如：腦力激盪、多方案並列、各自提出對某議題的立場或建議，不需即時回應前一位。每人只看到議題與專案狀態，不看同輪其他人的發言。
請依議題性質選擇其一。

# 標題與描述撰寫要求（重要）
- **title（標題）**：一句話、具體、讓人一眼知道「要討論什麼」。要與本專案內容掛鉤，例如寫出涉及的對象、需求或 Conflict 重點，勿只寫類型名稱（如勿只寫「Conflict 討論」「需求取捨」）。
- **description（描述）**：簡短說明「為什麼要開這個議題、要解決什麼」。可提及相關需求 id 或 Conflict id，並用一兩句話說明討論重點。
- 範例：標題可為「CF-01 與 CF-03 是否需要改判」而非「Conflict 討論」；描述可為「請逐筆檢查涉及的 requirement pair 是否真的存在互斥或應維持 Neutral」。

# 議程類型與開題
- **conflict_discussion**：當有 label 為 Conflict 或 Neutral 且需要再次檢查標籤是否正確時，應考慮開此類再審查議題。
- **open_question**：當草稿（或摘要）中有待處理開放問題（含需求描述模糊、邊界待確認）時，可開此類。
- **open_question**：若同輪有多個 open_question，執行層會自動合併為單一「集中回覆」議題，讓相關 agent 一次回答；因此可先正常產生 open_question，無需刻意拆得很細。
- **new_requirement**：當草稿（或摘要）中出現「提出新功能、新限制、新例外情境、新需求」時，**應考慮開此類**，勿忽略；此外，若有跡象顯示既有需求需要修正（例如描述不準確、優先順序變動、邊界條件改變），也可用此類議題讓 User 檢視並調整既有需求。
- **tradeoff**：當需求摘要中有多個 NFR（NFR-1、NFR-2…）或 Conflict 涉及效能、可用性、成本等非功能需求之間的競合取捨時，**應考慮開此類**。
- 其餘依專案狀態與優先順序判斷，無強制對應。

# 約束
- 最多開 {limit} 個議程。請依你判斷的優先順序排列。
- 若無需討論的議題，請回傳空陣列
- category 只能是上述類型定義中的 id
- discussion_mode 依上表情境選擇 "sequential" 或 "simultaneous"
- 若有對應的 Conflict/需求/問題 id，請填在 source_ids 方便追蹤
- {mediator_agenda_language_line()}

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

        if not raw_items:
            messages = self.build_direct_messages(user_prompt)
            try:
                response = self.model.chat_json(messages)
            except Exception as e:
                self.logger.warning(f"議程生成 LLM 失敗: {e}")
                return []
            raw_items = response.get("items", [])

        if not raw_items:
            self.logger.info("本輪無新增議程")
            return []

        if proposal_pool is not None:
            raw_items = self._refine_agenda_titles(raw_items)

        ordered_items = raw_items[:limit]
        ordered_items = self.merge_open_question_items(
            ordered_items,
            artifact,
            registered,
        )

        agenda_items = []
        for idx, item in enumerate(ordered_items, 1):
            category = item.get("category", "")
            if category not in active_ids:
                category = active_ids[0] if active_ids else AGENDA_TYPE_IDS[0]
            normalized = normalize_agenda_topic(
                {
                    **item,
                    "id": item.get("id") or f"T-{idx:02d}",
                    "category": category,
                    "triage_action": item.get("triage_action", "formal_meeting"),
                },
                allowed_categories=active_ids or AGENDA_TYPE_IDS,
                registered_agents=registered,
                index=idx,
            )
            if normalized:
                agenda_items.append(normalized)

        return agenda_items

    def _refine_agenda_titles(self, items: List[Dict]) -> List[Dict]:
        """由 Mediator LLM 為 triage 產出的議題批次命名標題。"""
        entries = []
        for i, item in enumerate(items):
            entries.append({
                "index": i,
                "raw_title": (item.get("title") or "").strip(),
                "description": (item.get("description") or "").strip(),
                "category": (item.get("category") or "").strip(),
            })
        prompt = f"""你是需求會議主持人。以下議題由各 agent 提案產生，標題尚未定稿。
請為每個議題撰寫一句**簡短、易懂**的標題（讓人一眼知道要討論什麼）。

議題清單:
{json.dumps(entries, ensure_ascii=False, indent=2)}

規則:
- 繁體中文、一句話；口語可讀，避免公文腔與長串頓號。
- 長度約 **12～28 字**，最多不超過 36 字；不要只寫類型名稱（如「衝突討論」「需求取捨」）。
- 若描述中有具體對象或 ID，標題應納入。
- 僅輸出 JSON array，index 對應原清單。

輸出:
[{{"index": 0, "title": "具體標題"}}, ...]"""
        try:
            messages = self.build_direct_messages(prompt)
            data = self.model.chat_json(messages)
            if not isinstance(data, list):
                data = data.get("items") or data.get("titles") or []
            title_map = {}
            for row in data:
                if isinstance(row, dict) and "index" in row and "title" in row:
                    title_map[int(row["index"])] = str(row["title"]).strip()
            for i, item in enumerate(items):
                new_title = title_map.get(i)
                if new_title:
                    item["title"] = new_title
        except Exception as e:
            self.logger.warning("議題標題命名失敗: %s", e)
        return items

    def name_topic_after_discussion(
        self,
        topic: Dict[str, Any],
        contributions: List[Dict],
        resolution: Dict[str, Any],
        *,
        proposer_agent: Optional[str] = None,
    ) -> str:
        """議題討論結束、存檔前：產出精簡、易懂的一句標題（繁體中文）。失敗或空字串時呼叫端應保留原標題。"""
        prev = (topic.get("title") or "").strip()
        desc = (topic.get("description") or "").strip()
        cat = (topic.get("category") or "").strip()
        summary = (resolution.get("summary") or "").strip()
        decision = (resolution.get("decision") or "").strip()
        rstatus = (
            resolution.get("resolution_status")
            or resolution.get("resolution")
            or ""
        )
        rstatus = str(rstatus).strip()
        contrib_lines: List[str] = []
        for c in contributions[:12]:
            if not isinstance(c, dict):
                continue
            ag = c.get("agent", "?")
            resp = c.get("response") or {}
            stmt = (resp.get("statement") or resp.get("content") or "").strip()
            if stmt:
                snippet = stmt[:200] + ("…" if len(stmt) > 200 else "")
                contrib_lines.append(f"- [{ag}] {snippet}")
        contrib_text = "\n".join(contrib_lines) if contrib_lines else "（無發言摘要）"
        proposer_line = ""
        if proposer_agent:
            proposer_line = f"\n原始提案者（agent id）: {proposer_agent}"
        prompt = f"""你是需求會議主持人。以下議題已討論完畢並將存檔，請**只根據下方資訊**撰寫**一句**繁體中文「會議記錄標題」。

風格（最重要）：
- **簡單易懂**：用口語可讀的短句，避免公文腔、長串頓號或從句堆砌。
- **精簡**：全長 **約 12～28 字為佳**，最多不超過 36 字；能短則短。
- 點出「主題＋重點結論或決策方向」即可，不要複述整段決議全文。

議前標題（可參考，必要時濃縮改寫）: {prev or "（無）"}
類型: {cat or "（無）"}
說明: {desc or "（無）"}{proposer_line}

討論後摘要: {summary or "（無）"}
決議文字: {decision or "（無）"}
收斂狀態: {rstatus or "（無）"}

各方發言摘要:
{contrib_text}

規則:
- 一句話、繁體中文；勿使用 Markdown、引號包裹整句、或條列式。
- 勿虛構未出現的產品名詞或法規名稱。
- 優先從「決議文字／摘要」濃縮，其次才參考發言摘要。

只輸出一個 JSON 物件：{{"title": "最終標題"}}"""
        try:
            messages = self.build_direct_messages(prompt)
            data = self.model.chat_json(messages)
            if not isinstance(data, dict):
                data = {}
            out = (data.get("title") or "").strip()
            if out:
                return out
        except Exception as e:
            self.logger.warning("議題結束後標題命名失敗: %s", e)
        return ""

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

    def merge_open_question_items(
        self,
        items: List[Dict[str, Any]],
        artifact: Dict[str, Any],
        registered: List[str],
    ) -> List[Dict[str, Any]]:
        """
        將多個 open_question 議程合併為單一議題，避免逐題拆散討論。
        需求：只要有 open_question，就由相關 agent 在同一題集中回覆。
        """
        open_items = [it for it in items if (it.get("category") or "").strip() == "open_question"]
        if not open_items:
            return items

        related_agents = set()
        for it in open_items:
            for a in (it.get("participants", []) or []):
                if a in registered:
                    related_agents.add(a)
            for a in (it.get("speaking_order", []) or []):
                if a in registered:
                    related_agents.add(a)

        for q in artifact.get("open_questions", []):
            if q.get("status") == "answered":
                continue
            if not self.should_escalate_open_question(q):
                continue
            to_agent = (q.get("to") or q.get("to_agent") or "").strip()
            if to_agent in registered:
                related_agents.add(to_agent)

        participants = [a for a in registered if a in related_agents]
        if not participants:
            participants = list(registered)

        source_ids: List[str] = []
        seen_ids = set()
        for it in open_items:
            for sid in (it.get("source_ids", []) or []):
                if not sid or sid in seen_ids:
                    continue
                seen_ids.add(sid)
                source_ids.append(sid)

        merged_item = {
            "title": "開放問題集中回覆",
            "description": f"整合 {len(open_items)} 個 open_question 議題，請相關 agent 集中回答。",
            "category": "open_question",
            "participants": participants,
            "discussion_mode": "simultaneous",
            "speaking_order": participants,
            "source_ids": source_ids,
        }

        merged: List[Dict[str, Any]] = []
        inserted = False
        for it in items:
            if (it.get("category") or "").strip() == "open_question":
                if not inserted:
                    merged.append(merged_item)
                    inserted = True
                continue
            merged.append(it)
        return merged

    @staticmethod
    def should_escalate_open_question(q: Dict[str, Any]) -> bool:
        """判斷 open question 是否應升級為正式 agenda topic。"""
        if not isinstance(q, dict):
            return False
        if q.get("status") == "answered":
            return False
        if q.get("needs_agenda") is True:
            return True
        if q.get("status") == "escalate_to_topic":
            return True
        if int(q.get("deferred_count") or 0) >= 2:
            return True
        if q.get("requires_multi_party") is True:
            return True
        if q.get("blocks_decision") is True:
            return True
        return False

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

        sr_cap = self.self_review_round_cap()

        user_prompt = f"""# 任務
你是本輪主持人。根據當前狀態與上一動結果，選下一個動作。

# 動作
- generate_agenda：topics 為空時
- expand_agenda：僅在 state.can_expand_agenda=true 且確有新議題時
- start_discussion：{{"topic_id":"T-01"}}
- resolve_topic：{{"topic_id":"T-01"}}，需已 start_discussion
{escalate_action}- save_topic：{{"topic_id":"T-01"}}，需已 resolve 或 escalate
- expert_review / analyst_review / modeler_review：僅在 queue 或 meeting 產生新 issue 時；params 可帶 {{"max_iterations":1-{sr_cap}}}
- finish_round：僅在 formal topics 已 save、queue 已處理或遞延，且無需 review / expand / escalate 時

# 當前狀態
{state_text}

# 上一步結果
{obs_text}

# 規則
- topics 為空先 generate_agenda
- queue-first：能由 clarification / direct_apply / human_decision 先處理的議題，不要急著重開 formal meeting
- topic 順序：start_discussion → resolve_topic → save_topic{escalate_hint}
- 若上一步 resolve_topic 結果含 needs_human=true，必須先 escalate_to_human 再 save_topic
- queue 未處理完不得 finish_round
- 有 pending_review_issues、deferred 項或新 open_questions 時，先判斷 review / expand / escalate
- 若某題在討論後已明確自然收斂，應直接 resolve_topic 整理結論，不必額外製造主持人折衷方案
- 只有 formal meeting 題目經討論後仍無法收斂時，才交由 resolve_topic 形成主持人折衷或升級人工
- 所有議題 save 完畢且 can_expand_agenda=true 時，應主動評估是否有新議題需補充討論（expand_agenda）；確認無追加需求才 finish_round
- 需要 artifact 細節時先用 artifact_query
- 一次只回一個動作
- {mediator_reasoning_line()}

# 輸出 JSON
{{
  "action": "動作名稱",
  "params": {{}} or {{"topic_id":"T-01"}},
  "reasoning": "一句說明"
}}"""

        messages = self.build_direct_messages(user_prompt)
        try:
            if "artifact_query" in self.tools:
                raw = self.chat_with_tools(messages, max_rounds=self.tool_call_max_rounds)
                response = self.parse_topic_response_json(raw)
            else:
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

    # ===== Plan: pre-meeting =====

    def plan_elicitation_meeting(
        self,
        artifact: Dict[str, Any],
        registry=None,
    ) -> Dict[str, Any]:
        """根據目前需求狀況，規劃隱性需求挖掘會議的參與者與討論模式（回合數由 flow.config elicitation_max_turns 決定）。"""
        requirements = artifact.get("requirements", []) or []
        req_count = len(requirements)

        exclude = {"mediator", "documentor", "user"}
        if registry:
            interviewers = [n for n in registry.get_names() if n not in exclude]
        else:
            interviewers = ["analyst", "expert", "modeler"]
        participants = interviewers + ["user"]

        mode = "sequential"

        plan = {
            "participants": participants,
            "interviewers": interviewers,
            "speaking_order": interviewers + ["user"],
            "discussion_mode": mode,
            "stop_no_new_rounds": 2,
        }
        self.logger.info(
            "Elicitation plan: mode=%s, req_count=%s",
            mode, req_count,
        )
        return plan

    def decide_elicitation_turn_strategy(
        self,
        *,
        artifact: Dict[str, Any],
        turn: int,
        max_turns: int,
        default_participants: List[str],
        default_speaking_order: List[str],
        default_mode: str,
        previous_turn_summary: Optional[Dict[str, Any]] = None,
        ) -> Dict[str, Any]:
        """由 Mediator 逐輪決定挖掘會議安排（collectors + asker + user）。"""
        prev = previous_turn_summary or {}
        default_interviewers = [p for p in default_participants if p != "user"]
        if "analyst" in default_interviewers:
            default_asker = "analyst"
        elif default_interviewers:
            default_asker = default_interviewers[0]
        else:
            default_asker = "analyst"
        preferred_collectors = ["expert", "modeler"]
        default_collectors = [
            p for p in preferred_collectors
            if p in default_interviewers and p != default_asker
        ]
        if not default_collectors:
            default_collectors = [p for p in default_interviewers if p != default_asker]
        prompt = f"""# 任務
你是隱性需求挖掘會議主持人。請為本輪決定哪些角色先蒐集提問資訊（collectors），以及哪個角色負責最後向 user 提出主問題（asker）。

# 本輪資訊
- turn: {turn}/{max_turns}
- default_participants: {default_participants}
- default_asker: {default_asker}
- default_collectors: {default_collectors}

# 上一輪摘要
{json.dumps(prev, ensure_ascii=False, indent=2)}

# 規則
- participants 只能從 default_participants 選，且必須包含 user。
- asker 必須是非 user 角色，且只能有一位。
- collectors 只能是非 user 角色，可 0~2 位；不要包含 asker。
- 預設由 analyst 擔任 asker（主 elicitor）。
- 預設由 expert 與 modeler 擔任 collectors；若其一不可用，再從其他非 user 角色補上。
- 僅輸出 JSON，不要附加說明。

# 輸出 JSON
{{
  "participants": ["analyst","expert","modeler","user"],
  "collectors": ["expert","modeler"],
  "asker": "analyst"
}}"""

        messages = self.build_direct_messages(prompt)
        try:
            data = self.model.chat_json(messages)
        except Exception as e:
            self.logger.warning("逐輪策略決策失敗，改用預設：%s", e)
            return {
                "participants": list(default_participants),
                "collectors": list(default_collectors),
                "asker": default_asker,
            }

        allowed = [str(x).strip() for x in default_participants if str(x).strip()]
        allowed_set = set(allowed)

        participants_raw = data.get("participants") or []
        participants = [
            str(x).strip()
            for x in participants_raw
            if isinstance(x, str) and str(x).strip() in allowed_set
        ]
        if "user" not in participants and "user" in allowed_set:
            participants.append("user")
        if not participants:
            participants = list(default_participants)

        participants_set = set(participants)
        interviewer_candidates = [p for p in participants if p != "user"]
        asker = str(data.get("asker") or "").strip()
        if asker not in interviewer_candidates:
            asker = default_asker if default_asker in interviewer_candidates else (interviewer_candidates[0] if interviewer_candidates else "analyst")
        if "analyst" in interviewer_candidates:
            asker = "analyst"

        collectors_raw = data.get("collectors") or []
        collectors: List[str] = []
        for x in collectors_raw:
            if not isinstance(x, str):
                continue
            role = x.strip()
            if role and role in interviewer_candidates and role != asker and role not in collectors:
                collectors.append(role)
            if len(collectors) >= 2:
                break
        if not collectors:
            for role in preferred_collectors:
                if role in interviewer_candidates and role != asker and role not in collectors:
                    collectors.append(role)
                if len(collectors) >= 2:
                    break
        if not collectors:
            for role in interviewer_candidates:
                if role != asker and role not in collectors:
                    collectors.append(role)
                if len(collectors) >= 2:
                    break

        speaking = collectors + [asker] + (["user"] if "user" in participants_set else [])

        return {
            "participants": participants,
            "collectors": collectors,
            "asker": asker,
            "speaking_order": speaking,
        }

    def plan_pre_meeting_conflict_review(
        self,
        conflict: Dict[str, Any],
        artifact: Optional[Dict[str, Any]] = None,
        registry=None,
    ) -> Dict[str, Any]:
        """由主持人模型動態決定會前衝突再審查的討論模式。

        - 僅回傳 ``discussion_mode`` 與 ``participants``。
        - **sequential**：發言順序完全由 ``participants`` 陣列順序表達，**不**另產生
          ``speaking_order``（下游亦不得推導寫入 record）。
        - **simultaneous**：多人並行發言，同樣不產生 ``speaking_order``。
        """
        participants_def: List[str] = []
        if registry:
            participants_def = [
                n
                for n in registry.get_names()
                if n in {"analyst", "expert", "modeler", "user"}
            ]
        if not participants_def:
            participants_def = ["user", "analyst", "expert", "modeler"]

        allowed_set = set(participants_def)
        n_candidates = 0
        if isinstance(artifact, dict):
            for c in artifact.get("conflicts") or []:
                if not isinstance(c, dict):
                    continue
                if str(c.get("label") or "").strip() in {"Conflict", "Neutral"}:
                    n_candidates += 1

        prompt = f"""你是需求會議主持人，即將進行「會前衝突批次再審查」（同一輪內可能有多筆 Conflict/Neutral pairs 需一併做標籤再審查）。

請決定本輪討論模式（只能二選一）：
- sequential：參與者依你指定的 participants **陣列順序**逐一發言。此模式**不得**使用 speaking_order 欄位；順序**只能**用 participants 表達。
- simultaneous：每位參與者各自獨立、同時提出看法（實作上並行蒐集發言），不強調逐一輪替。

本輪待審項目數（Conflict + Neutral）：{max(1, n_candidates)}

可用的參與者代號（必須從下列集合挑出，不可自創；可刪減但建議保留多方觀點）：
{json.dumps(participants_def, ensure_ascii=False)}

輸出**僅可**為一個 JSON 物件，欄位如下：
{{
  "discussion_mode": "sequential 或 simultaneous",
  "participants": ["..."]
}}

規則：
- participants 至少 2 人，且每個元素必須屬於上方集合；**陣列順序即為 sequential 時的發言順序**。
- 若需逐步比對證據、修正他人判準或逐筆重判，可優先 sequential；若只需快速蒐集獨立判斷可選 simultaneous。
"""
        data: Dict[str, Any] = {}
        try:
            messages = self.build_direct_messages(prompt)
            raw = self.model.chat_json(messages)
            if isinstance(raw, dict):
                data = raw
        except Exception as e:
            self.logger.warning(
                "plan_pre_meeting_conflict_review：LLM 失敗，採預設 sequential：%s",
                e,
            )

        mode = str(data.get("discussion_mode") or "sequential").strip().lower()
        if mode not in {"sequential", "simultaneous"}:
            mode = "sequential"

        participants: List[str] = []
        raw_parts = data.get("participants")
        if isinstance(raw_parts, list):
            for n in raw_parts:
                s = str(n).strip()
                if s in allowed_set and s not in participants:
                    participants.append(s)
        if len(participants) < 2:
            participants = list(participants_def)

        return {"discussion_mode": mode, "participants": participants}

    # ===== Action: discussion moderation =====

    def moderate_sequential(
        self, topic: Dict, registry, artifact: Optional[Dict[str, Any]] = None
    ) -> tuple:
        """逐一發言；輪到某人前先讓他即時回答指向他的問題，再發言（可依問答調整立場）。回傳 (contributions, oq_records)。"""
        contributions = [
            c for c in (topic.get("seed_previous_responses") or [])
            if isinstance(c, dict)
        ]
        oq_records = []
        speaking_order = topic.get("speaking_order") or topic.get("participants") or []
        if not speaking_order:
            self.logger.warning(f"[{topic['id']}] 無發言者")
            return (contributions, oq_records)
        title = topic.get("title", "") or "（無標題）"
        self.logger.info(f"[{topic['id']}] {title} — 逐一: {' → '.join(speaking_order)}")

        snapshot = self.build_artifact_snapshot(artifact)
        for agent_name in speaking_order:
            agent = registry.get(agent_name)
            if not agent:
                self.logger.warning(f"Agent '{agent_name}' 未註冊，跳過")
                continue
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
                if str(topic.get("asker_agent") or "").strip() == agent_name:
                    resp = response if isinstance(response, dict) else {"content": str(response)}
            except Exception as e:
                self.logger.warning(f"  {agent_name} 發言失敗: {e}")
                contributions.append(
                    {"agent": agent_name, "response": {"content": f"（發言失敗: {e}）"}}
                )
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
            self.logger.warning(f"[{topic.get('id', '?')}] 無發言者")
            return []
        title = topic.get("title", "") or "（無標題）"
        self.logger.info(f"[{topic['id']}] {title} — 同時: {', '.join(participants)}")

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

    # ===== Action: open question processing =====

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
                return (
                    q_record,
                    None,
                    {
                        **q_record,
                        "status": "deferred",
                        "deferred_count": int(q_record.get("deferred_count") or 0) + 1,
                        "needs_agenda": False,
                    },
                )
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
                    {
                        **q_record,
                        "status": "answered",
                        "answer": answer,
                        "needs_agenda": False,
                    },
                )
            except Exception:
                return (
                    q_record,
                    None,
                    {
                        **q_record,
                        "status": "deferred",
                        "deferred_count": int(q_record.get("deferred_count") or 0) + 1,
                        "needs_agenda": False,
                    },
                )

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
                        {
                            **valid_questions[idx],
                            "status": "deferred",
                            "deferred_count": int(valid_questions[idx].get("deferred_count") or 0) + 1,
                            "needs_agenda": False,
                        },
                    )

        for i in range(len(valid_questions)):
            contrib, oq = results_by_idx.get(
                i,
                (
                    None,
                    {
                        **valid_questions[i],
                        "status": "deferred",
                        "deferred_count": int(valid_questions[i].get("deferred_count") or 0) + 1,
                        "needs_agenda": False,
                    },
                ),
            )
            q_text = (oq.get("question") or "").strip()
            if oq.get("status") != "answered":
                blocks_decision = any(
                    kw in q_text for kw in ("是否", "要不要", "能否", "可否", "scope", "優先", "衝突", "取捨", "tradeoff")
                )
                requires_multi_party = any(
                    kw in q_text for kw in ("各方", "多方", "哪一方", "是否都", "衝突")
                )
                oq["blocks_decision"] = blocks_decision
                oq["requires_multi_party"] = requires_multi_party
                oq["needs_agenda"] = self.should_escalate_open_question(oq)
                if oq["needs_agenda"]:
                    oq["status"] = "escalate_to_topic"
            oq_records.append(oq)
            if contrib:
                contributions.append(contrib)

        return oq_records

    # ===== Action: voting & resolution =====

    def assess_discussion_convergence(
        self,
        topic: Dict,
        contributions: List[Dict],
    ) -> Dict[str, Any]:
        """討論結束後判斷各方意見是否已自然收斂（無需折衷方案即可形成決議）。"""
        main_contribs = [c for c in contributions if not c.get("is_reply", False)]
        if not main_contribs:
            return {"converged": False, "reason": "無發言"}
        discussion_text = ""
        for c in main_contribs:
            agent = c.get("agent", "?")
            statement = (c.get("response") or {}).get("statement", "")
            discussion_text += f"\n【{agent}】\n{statement}\n"

        user_prompt = f"""你是需求會議主持人。請判斷以下議題的討論是否已自然收斂——亦即各方意見大致一致、無明顯反對或重大分歧，可直接形成決議。

# 議題
標題: {topic.get('title', '')}
描述: {topic.get('description', '')}

# 各方發言
{discussion_text}

# 判斷標準
- 若所有（或絕大多數）發言者觀點一致、無人提出反對或重要保留，判定為「收斂」。
- 若有明確分歧、互相矛盾的立場、或有人提出重要但未被回應的疑慮，判定為「未收斂」。

# 輸出 JSON
{{
  "converged": true 或 false,
  "reason": "一句說明為何收斂/未收斂",
  "summary": "若收斂，簡述共識內容；若未收斂則空字串",
  "decision": "若收斂，寫出可作為決策的具體內容；若未收斂則空字串"
}}
只輸出 JSON。"""
        messages = self.build_direct_messages(user_prompt)
        try:
            data = self.model.chat_json(messages)
            return {
                "converged": bool(data.get("converged")),
                "reason": (data.get("reason") or "").strip(),
                "summary": (data.get("summary") or "").strip(),
                "decision": (data.get("decision") or "").strip(),
            }
        except Exception as e:
            self.logger.warning("收斂判斷失敗: %s", e)
            return {"converged": False, "reason": str(e)}

    def build_converged_resolution(
        self,
        topic: Dict,
        contributions: List[Dict],
        convergence: Dict[str, Any],
    ) -> Dict[str, Any]:
        """討論已自然收斂時，直接產出 agreed resolution（無需折衷方案與投票）。"""
        summary = convergence.get("summary") or "討論各方意見一致，已自然收斂。"
        decision = convergence.get("decision") or summary
        affected_conflict_ids = [
            sid for sid in (topic.get("source_ids") or [])
            if isinstance(sid, str)
            and (sid.startswith("CF-") or sid.startswith("CF-D") or sid.startswith("NF-"))
        ]
        affected_requirement_ids = [
            sid for sid in (topic.get("source_ids") or [])
            if isinstance(sid, str)
            and sid.startswith(("REQ-", "FR-", "NFR-", "R-"))
        ]
        return self.build_topic_result(
            resolution_status="agreed",
            summary=summary,
            decision=decision,
            votes={},
            votes_summary="自然收斂（免投票）",
            mediator_compromise={"title": "", "description": "", "rationale": ""},
            agreed_points=[decision] if decision else [summary],
            unresolved_points=[],
            new_open_questions=[],
            affected_conflict_ids=affected_conflict_ids,
            affected_requirement_ids=affected_requirement_ids,
            needs_approval=bool(affected_requirement_ids),
            needs_human=False,
        )

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
            self.logger.warning("折衷方案失敗: %s", e)
            return {"title": "", "description": "", "rationale": ""}

    def collect_compromise_votes(
        self,
        topic: Dict,
        contributions: List[Dict],
        mediator_compromise: Dict[str, str],
        registry,
        artifact: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, str]:
        """向各參與者收集對主持人折衷方案的投票（agreed / unresolved）。"""
        main_contribs = [c for c in contributions if not c.get("is_reply", False)]
        voters = topic.get("speaking_order") or topic.get("participants") or []
        if not voters:
            voters = [c.get("agent") for c in main_contribs if c.get("agent")]

        snapshot = self.build_artifact_snapshot(artifact)
        votes: Dict[str, str] = {}
        for agent_name in voters:
            agent = registry.get(agent_name) if registry else None
            if not agent:
                self.logger.warning(f"投票找不到 '{agent_name}'，略過")
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
                self.logger.warning(f"  {agent_name} 投票失敗: {e}")
                votes[agent_name] = "unresolved"
        return votes

    def synthesize_and_resolve(
        self,
        topic: Dict,
        contributions: List[Dict],
        final_votes: Optional[Dict[str, str]] = None,
        mediator_compromise: Optional[Dict[str, Any]] = None,
        proposer_agent: Optional[str] = None,
    ) -> Dict:
        """依最終投票以多數決+提案者同意判斷是否達成共識；agreed 時由 LLM 產出 summary 與 decision。"""
        if not contributions:
            self.logger.warning(f"  [{topic.get('id', '?')}] 無發言，標記 unresolved")
            return self.build_topic_result(
                resolution_status="unresolved",
                summary="本議題無人發言，無法進行決議。",
                decision="",
                votes={},
                votes_summary="無投票（0/0）",
                mediator_compromise={"title": "", "description": "", "rationale": ""},
                unresolved_points=["本議題無人發言，無法形成可決議內容。"],
                needs_human=False,
            )

        votes_by_agent = {}
        if final_votes:
            for agent, vote in final_votes.items():
                v = (vote or "").strip().lower()
                votes_by_agent[agent] = "agreed" if v == "agreed" else "unresolved"

        votes_list = list(votes_by_agent.values())

        agreed_count = sum(1 for v in votes_list if v == "agreed")
        n = len(votes_list)
        unresolved_count = n - agreed_count
        majority_agreed = n > 0 and agreed_count > unresolved_count
        proposer_agreed = (
            votes_by_agent.get(proposer_agent) == "agreed"
            if proposer_agent
            else True
        )
        resolution = "agreed" if majority_agreed and proposer_agreed else "unresolved"

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

        consensus_points = []
        unresolved_points = []
        if resolution == "agreed":
            if mc_desc:
                consensus_points.append(mc_desc)
            elif mc_title:
                consensus_points.append(mc_title)
            if not consensus_points:
                consensus_points.append("多數參與者接受主持人折衷方案。")
        else:
            if not majority_agreed:
                unresolved_points.append("主持人折衷方案未獲多數接受。")
            if proposer_agent and not proposer_agreed:
                unresolved_points.append(f"提案者（{proposer_agent}）未同意折衷方案。")
            if not unresolved_points:
                unresolved_points.append("本議題未達成共識。")
        affected_conflict_ids = [
            sid for sid in (topic.get("source_ids") or [])
            if isinstance(sid, str) and (sid.startswith("CF-") or sid.startswith("CF-D") or sid.startswith("NF-"))
        ]
        needs_human = resolution != "agreed" and n >= 2
        resolution_frame = {
            "topic_id": topic.get("id", ""),
            "category": topic.get("category", ""),
            "vote_summary": {
                "total": n,
                "agreed": agreed_count,
                "unresolved": unresolved_count,
            },
            "accepted_compromise": {
                "title": mc_title,
                "description": mc_desc,
                "rationale": mc_rat,
            },
            "agreed_points_seed": consensus_points,
            "unresolved_points_seed": unresolved_points,
            "affected_conflict_ids": affected_conflict_ids,
            "affected_requirement_ids_hint": [
                sid for sid in (topic.get("source_ids") or [])
                if isinstance(sid, str) and sid.startswith(("REQ-", "FR-", "NFR-", "R-"))
            ],
            "needs_human": needs_human,
        }

        if resolution == "agreed":
            user_prompt = f"""# 任務
本議題已由多數決判定為達成共識。請根據主持人折衷方案與各方發言，整理摘要與具體決策。

# 議題資訊
標題: {topic.get('title', '')}
描述: {topic.get('description', '')}

{compromise_block}# 各方討論內容
{discussion_text}

# 已知決議框架
{json.dumps(resolution_frame, ensure_ascii=False, indent=2)}

# 規則
- 若討論已自然收斂，你的工作是整理共識，不是重新發明折衷方案。
- 只有在已知決議框架明確包含主持人折衷方案時，decision 才以該方案為準。
- 先依決議框架整理已知共識，再寫 summary 與 decision。
- decision 必須與已接受的結論一致，不要改變決議方向。
- agreed_points 列 1-3 點具體共識；unresolved_points 只留仍需追蹤事項，沒有就回空陣列。
- agreed_points / unresolved_points 用簡短完整句。
- affected_requirement_ids：列出本議題決議所影響的需求 ID（如 FR-01、NFR-02），從討論內容與已知決議框架的 affected_requirement_ids_hint 推導，不可為空。
- requirement_change_candidates：若決議導致需求文字、優先順序或驗收條件等異動，請列出具體變更；每筆須含 requirement_id、change_type（update/add/remove）、field（text/priority/acceptance_criteria 等）、after（新值）、reason。無變更則空陣列。
- {mediator_summary_decision_line()}

# 輸出 JSON
{{{{
    "summary": "總結討論內容與結論",
    "decision": "具體決策內容",
    "agreed_points": ["共識要點1"],
    "unresolved_points": [],
    "affected_requirement_ids": ["FR-01"],
    "requirement_change_candidates": [
        {{{{
            "requirement_id": "FR-01",
            "change_type": "update",
            "field": "text",
            "after": "更新後的需求描述",
            "reason": "因討論決議調整"
        }}}}
    ]
}}}}"""
        else:
            user_prompt = f"""# 任務
{mediator_unresolved_vote_task_line()}

# 議題資訊
標題: {topic.get('title', '')}
描述: {topic.get('description', '')}

{compromise_block}# 各方討論內容
{discussion_text}

# 已知決議框架
{json.dumps(resolution_frame, ensure_ascii=False, indent=2)}

# 規則
- 若討論尚未自然收斂，你可以整理局部共識，並在需要時提出單一主持人折衷方向。
- 若折衷方向仍無法同時滿足提案核心意圖、關鍵角色專業底線或已知限制，應維持 unresolved / needs_human。
- 先整理已知共識、未共識、卡住決策的 trade-off 或缺口，再輸出欄位。
- decision 保持空字串。
- agreed_points 可列局部共識；沒有就回空陣列。
- unresolved_points 列 1-3 點真正卡住決策的爭點、缺少資訊或待裁決邊界。
- agreed_points / unresolved_points 用簡短完整句。
- affected_requirement_ids：列出本議題涉及的需求 ID，從已知決議框架的 affected_requirement_ids_hint 推導，不可為空。

# 輸出 JSON
{{{{
    "summary": "總結討論內容與各方立場",
    "decision": "",
    "agreed_points": [],
    "unresolved_points": ["未解決爭點"],
    "affected_requirement_ids": ["FR-01"]
}}}}"""

        messages = self.build_direct_messages(user_prompt)
        try:
            response = self.model.chat_json(messages)
            summary = response.get("summary", "")
            decision = response.get("decision", "") if resolution == "agreed" else ""
            agreed_points = response.get("agreed_points", [])
            unresolved_points_from_llm = response.get("unresolved_points", [])
            llm_affected_req_ids = response.get("affected_requirement_ids", [])
            llm_change_candidates = response.get("requirement_change_candidates", [])
        except Exception as e:
            self.logger.warning(f"共識摘要 LLM 失敗: {e}")
            summary = "（多數決結果：%s；摘要產生失敗）" % resolution
            decision = ""
            agreed_points = consensus_points
            unresolved_points_from_llm = unresolved_points
            llm_affected_req_ids = []
            llm_change_candidates = []

        if not isinstance(agreed_points, list):
            agreed_points = consensus_points
        if not isinstance(unresolved_points_from_llm, list):
            unresolved_points_from_llm = unresolved_points

        def _clean_point_list(items: List[Any], fallback: List[str]) -> List[str]:
            out = []
            for item in items:
                if not isinstance(item, str):
                    continue
                text = item.strip()
                if not text:
                    continue
                if text in out:
                    continue
                out.append(text)
            return out or fallback

        agreed_points = _clean_point_list(agreed_points, consensus_points)
        unresolved_points_from_llm = _clean_point_list(
            unresolved_points_from_llm, unresolved_points
        )

        if not llm_affected_req_ids:
            llm_affected_req_ids = [
                sid for sid in (topic.get("source_ids") or [])
                if isinstance(sid, str) and sid.startswith(("REQ-", "FR-", "NFR-", "R-"))
            ]
        needs_approval = bool(llm_affected_req_ids) or bool(llm_change_candidates)

        return self.build_topic_result(
            resolution_status=resolution,
            summary=summary,
            decision=decision,
            votes=votes_by_agent,
            votes_summary=f"{agreed_count} agreed, {unresolved_count} unresolved",
            mediator_compromise={
                "title": mc_title,
                "description": mc_desc,
                "rationale": mc_rat,
            },
            agreed_points=agreed_points or consensus_points,
            unresolved_points=unresolved_points_from_llm or unresolved_points,
            new_open_questions=[],
            affected_conflict_ids=affected_conflict_ids,
            affected_requirement_ids=llm_affected_req_ids,
            requirement_change_candidates=llm_change_candidates if isinstance(llm_change_candidates, list) else [],
            needs_approval=needs_approval,
            needs_human=needs_human,
        )

    # ===== Action: human escalation =====

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
3. {mediator_human_options_line()}

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

    # ===== Action: decisions & output =====

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
- {mediator_collect_line()}

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

    def generate_meeting_markdown(
        self,
        topic: Dict,
        contributions: List[Dict],
        resolution: Dict,
        round_num: int = 0,
        *,
        proposed_by: Optional[str] = None,
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
        proposer = (proposed_by if proposed_by is not None else topic.get("proposed_by"))
        proposer = (proposer or "").strip() or None

        md = f"# {topic.get('title', '')}\n\n"
        md += f"- **Round**: {round_num}\n"
        md += f"- **Category**: {cat_label}\n"
        if description:
            md += f"- **Description**: {description}\n"
        if proposer:
            md += f"- **Proposed by**: {proposer}\n"
        elif topic.get("source_proposal_ids"):
            md += "- **Proposed by**: （無法自提案池追溯）\n"
        else:
            md += "- **Proposed by**: （本議題非來自 agent 提案池，無單一提案者）\n"
        summary = resolution.get("summary", "")
        decision = resolution.get("decision", "")
        resolution_status = resolution.get("resolution_status", resolution.get("resolution", ""))
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
        agreed_points = resolution.get("agreed_points", []) or []
        unresolved_points = resolution.get("unresolved_points", []) or []
        affected_requirement_ids = resolution.get("affected_requirement_ids", []) or []
        verification_impact = resolution.get("verification_impact", {}) or {}
        if agreed_points:
            md += f"- **Agreed points**: {'; '.join(agreed_points)}\n"
        if unresolved_points:
            md += f"- **Unresolved points**: {'; '.join(unresolved_points)}\n"
        if affected_requirement_ids:
            md += f"- **Affected requirements**: {', '.join(affected_requirement_ids)}\n"
        if isinstance(verification_impact, dict):
            level = str(verification_impact.get("level") or "").strip()
            notes = str(verification_impact.get("notes") or "").strip()
            if level or notes:
                line = level or "none"
                if notes:
                    line = f"{line} — {notes}" if line else notes
                md += f"- **Verification impact**: {line}\n"
        if resolution.get("needs_approval"):
            md += "- **Needs approval**: true\n"
        if resolution.get("needs_human"):
            md += "- **Needs human**: true\n"
        md += "\n"

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
                "resolution_status": resolution.get("resolution_status", resolution.get("resolution", "")),
                "summary": resolution.get("summary", ""),
                "decision_summary": resolution.get("decision_summary", resolution.get("summary", "")),
                "decision": resolution.get("decision", ""),
                "votes": resolution.get("votes", {}),
                "votes_summary": resolution.get("votes_summary", ""),
                "agreed_points": resolution.get("agreed_points", []),
                "unresolved_points": resolution.get("unresolved_points", []),
                "new_open_questions": resolution.get("new_open_questions", []),
                "affected_conflict_ids": resolution.get("affected_conflict_ids", []),
                "affected_requirement_ids": resolution.get("affected_requirement_ids", []),
                "verification_impact": resolution.get("verification_impact", {}),
                "needs_approval": resolution.get("needs_approval", False),
                "requirement_change_candidates": resolution.get("requirement_change_candidates", []),
                "needs_human": resolution.get("needs_human", False),
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
- {mediator_prose_line()}
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

    # ===== Helpers =====

    @staticmethod
    def build_topic_result(
        *,
        resolution_status: str,
        summary: str,
        decision: str,
        votes: Optional[Dict[str, str]] = None,
        votes_summary: str = "",
        mediator_compromise: Optional[Dict[str, Any]] = None,
        agreed_points: Optional[List[str]] = None,
        unresolved_points: Optional[List[str]] = None,
        new_open_questions: Optional[List[Dict[str, Any]]] = None,
        affected_conflict_ids: Optional[List[str]] = None,
        affected_requirement_ids: Optional[List[str]] = None,
        verification_impact: Optional[Dict[str, Any]] = None,
        needs_approval: bool = False,
        requirement_change_candidates: Optional[List[Dict[str, Any]]] = None,
        needs_human: bool = False,
    ) -> Dict[str, Any]:
        """統一 topic_result schema，同時保留舊欄位以維持相容。"""
        resolution_status = (resolution_status or "").strip() or "unresolved"
        summary = (summary or "").strip()
        decision = (decision or "").strip()
        votes = votes or {}
        mediator_compromise = mediator_compromise or {
            "title": "",
            "description": "",
            "rationale": "",
        }
        agreed_points = [p.strip() for p in (agreed_points or []) if isinstance(p, str) and p.strip()]
        unresolved_points = [p.strip() for p in (unresolved_points or []) if isinstance(p, str) and p.strip()]
        new_open_questions = [
            q for q in (new_open_questions or [])
            if isinstance(q, dict) and ((q.get("question") or "").strip())
        ]
        affected_conflict_ids = [
            cid.strip() for cid in (affected_conflict_ids or [])
            if isinstance(cid, str) and cid.strip()
        ]
        affected_requirement_ids = [
            rid.strip() for rid in (affected_requirement_ids or [])
            if isinstance(rid, str) and rid.strip()
        ]
        verification_impact = verification_impact or {}
        if not isinstance(verification_impact, dict):
            verification_impact = {}
        verification_impact = {
            "level": str(verification_impact.get("level") or "none").strip() or "none",
            "notes": str(verification_impact.get("notes") or "").strip(),
        }
        requirement_change_candidates = [
            row for row in (requirement_change_candidates or []) if isinstance(row, dict)
        ]
        dod_complete = bool(
            decision
            and (resolution_status not in {"agreed", "human_decision"}
                 or affected_requirement_ids)
        )
        return {
            "schema_version": "topic_result.v1",
            "resolution": resolution_status,
            "summary": summary,
            "decision": decision,
            "votes": votes,
            "votes_summary": votes_summary,
            "mediator_compromise": mediator_compromise,
            "resolution_status": resolution_status,
            "decision_summary": summary,
            "agreed_points": agreed_points,
            "unresolved_points": unresolved_points,
            "new_open_questions": new_open_questions,
            "affected_conflict_ids": affected_conflict_ids,
            "affected_requirement_ids": affected_requirement_ids,
            "verification_impact": verification_impact,
            "needs_approval": bool(needs_approval),
            "requirement_change_candidates": requirement_change_candidates,
            "needs_human": bool(needs_human),
            "dod_complete": dod_complete,
        }

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
