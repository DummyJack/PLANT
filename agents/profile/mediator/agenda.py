# Mediator agenda logic: triage issue proposals and generate decision topics.
import json
from typing import Any, Dict, List, Optional

from agents.base import (
    mediator_agenda_language_line,
    mediator_reasoning_line,
)

from .validation import AGENDA_ACTIONS, AGENDA_TYPE_IDS, AGENDA_TYPES, normalize_decision_topic


class MediatorAgenda:
    def get_active_agenda_types(self):
        """回傳啟用的決策議題類型（tuple of dicts）和 id 列表。"""
        if self.enabled_agenda_type_ids is None:
            return AGENDA_TYPES, AGENDA_TYPE_IDS
        active = tuple(
            t for t in AGENDA_TYPES
            if t["id"] in self.enabled_agenda_type_ids
        )
        active_ids = [t["id"] for t in active]
        return active, active_ids

    def classify_issue_proposal(
        self,
        proposal: Dict[str, Any],
    ) -> Dict[str, Any]:
        """依 issue proposal schema 與類型規則決定分流：正式會議、定向問答、直接處理或人工裁決。"""
        category = (proposal.get("category") or "").strip()
        impact = (proposal.get("impact_level") or proposal.get("priority_hint") or "medium").strip().lower()
        needs_human = bool(proposal.get("needs_human"))
        routing_preference = (proposal.get("routing_preference") or "formal_meeting").strip()
        source_ids = [s for s in (proposal.get("source_ids") or []) if str(s).strip()]
        participants = [p for p in (proposal.get("participants") or []) if str(p).strip()]
        deferred_rounds = int(proposal.get("deferred_rounds") or 0)
        multi_party = len(participants) >= 3

        action = "direct_clarification"
        reason = "queue_first_default"
        if needs_human or routing_preference == "human_decision":
            action = "human_decision"
            reason = "proposal_marked_for_human"
        elif routing_preference in ("direct_apply", "direct_clarification"):
            action = routing_preference
            reason = "proposal_requested_direct_routing"
        elif category == "open_question":
            if impact == "high" or deferred_rounds >= 1 or multi_party:
                action = "formal_meeting"
                reason = "open_question_requires_group_resolution"
            else:
                action = "direct_clarification"
                reason = "single_point_open_question"
        elif category == "new_requirement":
            if impact in {"low", "medium"} and not multi_party and len(source_ids) <= 1:
                action = "direct_clarification"
                reason = "new_requirement_needs_scope_check_only"
            else:
                action = "formal_meeting"
                reason = "new_requirement_affects_scope"
        elif category == "conflict_discussion":
            action = "formal_meeting"
            reason = "conflict_discussion_requires_group_recheck"
        elif category == "tradeoff":
            if multi_party or impact == "high":
                action = "formal_meeting"
                reason = "tradeoff_requires_group_decision"
            else:
                action = "direct_clarification"
                reason = "tradeoff_not_material_yet"
        return {"action": action, "reason": reason}

    @staticmethod
    def fallback_category_for_disabled_type(category: str, active_type_ids: List[str]) -> Optional[str]:
        """停用的議題類型不可默默降成 conflict_discussion，避免需求補充被錯誤當成衝突審查。"""
        if category in active_type_ids:
            return category
        if category == "new_requirement" and "open_question" in active_type_ids:
            return "open_question"
        if "open_question" in active_type_ids:
            return "open_question"
        if "tradeoff" in active_type_ids:
            return "tradeoff"
        return active_type_ids[0] if active_type_ids else None

    def triage_issue_proposals(
        self,
        issue_pool: List[Dict[str, Any]],
        *,
        active_type_ids: List[str],
        registered: List[str],
        max_items: int,
        skip_source_ids: Optional[set] = None,
    ) -> Dict[str, Any]:
        skip = skip_source_ids or set()
        dedup = []
        seen = set()
        for p in issue_pool:
            if not isinstance(p, dict):
                continue
            title = (p.get("title") or "").strip()
            category = (p.get("category") or "").strip()
            src = tuple(sorted([str(s) for s in (p.get("source_ids") or []) if str(s).strip()]))
            key = ((p.get("issue_id") or "").strip(), title, category, src)
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
                (x.get("issue_id") or ""),
            ),
        )
        formal_candidates = []
        direct_clarifications = []
        direct_apply = []
        human_queue = []
        for p in ordered:
            route = self.classify_issue_proposal(p)
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
            category = self.fallback_category_for_disabled_type(category, active_type_ids)
            if not category:
                continue
            normalized = normalize_decision_topic(
                {
                    "title": (p.get("title") or "待討論議題").strip(),
                    "description": (p.get("description") or "").strip(),
                    "category": category,
                    "participants": p.get("participants", []),
                    "discussion_mode": p.get("discussion_mode", "sequential"),
                    "speaking_order": p.get("speaking_order", []),
                    "source_ids": p.get("source_ids", []),
                    "source_issue_ids": [p.get("issue_id")] if p.get("issue_id") else [],
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

    def generate_decision_topics(
        self,
        artifact: Dict[str, Any],
        registry=None,
        max_items: Optional[int] = None,
        skip_source_ids: Optional[set] = None,
        draft_markdown: Optional[str] = None,
        issue_pool: Optional[List[Dict[str, Any]]] = None,
    ) -> List[Dict]:
        """由 Mediator LLM 根據 issue proposal 或專案狀態產生 decision topics。"""
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
        if issue_pool is not None:
            triage = self.triage_issue_proposals(
                issue_pool or [],
                active_type_ids=active_ids,
                registered=registered,
                max_items=limit,
                skip_source_ids=skip,
            )
            raw_items = triage.get("items", [])
            artifact["issue_backlog"] = triage.get("backlog", [])
            artifact["clarification_queue"] = triage.get("direct_clarifications", [])
            artifact["direct_apply_queue"] = triage.get("direct_apply", [])
            artifact["human_decision_queue"] = triage.get("human_queue", [])
            artifact["issue_triage_meta"] = {
                **(triage.get("meta", {}) or {}),
                "mode": "issue_pool",
            }
            self.logger.info(
                "Issue Triage：%s 筆 → 選 %s 遞延 %s（上限 %s）",
                artifact["issue_triage_meta"].get("input_count", 0),
                artifact["issue_triage_meta"].get("selected_count", 0),
                artifact["issue_triage_meta"].get("deferred_count", 0),
                artifact["issue_triage_meta"].get("round_capacity_limit", limit),
            )
        else:
            context = self.build_agenda_context(
                artifact, skip, draft_markdown=draft_markdown
            )
            if not context.strip():
                self.logger.info("無足夠內容產生決策議題")
                return []
        if issue_pool is not None and not raw_items:
            self.logger.info("issue_pool 無可用 decision topic，略過本輪 agenda")
            return []

        user_prompt = f"""# 任務
    你是需求調解主持人。請根據下方「決策議題排程依據」與「已討論過項目」，自行判斷本輪應處理哪些決策議題。
    若有提供**最新需求草稿**，該草稿為**唯一依據**（含其中的需求表、Conflict、開放問題等章節——開放問題應已寫在草稿內）；請依草稿內文與 id 撰寫議程標題與描述。若僅有專案摘要（無草稿檔），則依該摘要判斷。
    決策議題類型必須從下方「決策議題類型定義」中選擇，每個決策議題需決定：標題、描述、類型、參與者、討論模式、發言順序。

    # 決策議題類型定義（category 必須為以下 id 之一）
    {types_text}

    # 決策議題排程依據
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
    - 範例：標題可為「CF-01 付款失敗處理與退款責任協調」而非「Conflict 討論」；描述可為「請協調相關需求的實作邊界、責任分工與可驗收決策」。

    # 決策議題類型與開題
    - **conflict_discussion**：當有 label 為 Conflict 且需要協調可執行解法時，應考慮開此類議題。Neutral label 再審查不進一般正式會議。
    - **open_question**：當草稿（或摘要）中有待處理開放問題（含需求描述模糊、邊界待確認）時，可開此類。
    - **open_question**：若同輪有多個 open_question，執行層會自動合併為單一「集中回覆」議題，讓相關 agent 一次回答；因此可先正常產生 open_question，無需刻意拆得很細。
    - **new_requirement**：當草稿（或摘要）中出現「提出新功能、新限制、新例外情境、新需求」時，**應考慮開此類**，勿忽略；此外，若有跡象顯示既有需求需要修正（例如描述不準確、優先順序變動、邊界條件改變），也可用此類議題讓 User 檢視並調整既有需求。
    - **tradeoff**：當需求摘要中有多個非功能需求，或 Conflict 涉及效能、可用性、成本等非功能面向之間的競合取捨時，**應考慮開此類**。
    - 其餘依專案狀態與優先順序判斷，無強制對應。

    # 約束
    - 最多排入 {limit} 個決策議題。請依你判斷的優先順序排列。
    - 若無需討論的議題，請回傳空陣列
    - category 只能是上述類型定義中的 id
    - discussion_mode 依上表情境選擇 "sequential" 或 "simultaneous"
    - 若有對應的 Conflict/需求/問題 id，請填在 source_ids 方便追蹤
    - {mediator_agenda_language_line()}

    # 輸出 JSON
    {{
    "items": [
        {{
            "title": "具體決策議題標題（與本專案內容掛鉤的一句話）",
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
                response = self.chat_json(messages)
            except Exception as e:
                self.logger.warning(f"決策議題生成 LLM 失敗: {e}")
                return []
            raw_items = response.get("items", [])

        if not raw_items:
            self.logger.info("本輪無新增決策議題")
            return []

        if issue_pool is not None:
            raw_items = self.refine_agenda_titles(raw_items)

        ordered_items = raw_items[:limit]
        ordered_items = self.merge_open_question_items(
            ordered_items,
            artifact,
            registered,
        )

        agenda_items = []
        for idx, item in enumerate(ordered_items, 1):
            category = item.get("category", "")
            category = self.fallback_category_for_disabled_type(category, active_ids)
            if not category:
                continue
            normalized = normalize_decision_topic(
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

    def refine_agenda_titles(self, items: List[Dict]) -> List[Dict]:
        """由 Mediator LLM 為 triage 產出的議題批次命名標題。"""
        entries = []
        for i, item in enumerate(items):
            entries.append({
                "index": i,
                "raw_title": (item.get("title") or "").strip(),
                "description": (item.get("description") or "").strip(),
                "category": (item.get("category") or "").strip(),
            })
        prompt = f"""你是需求會議主持人。以下決策議題由各 agent issue proposal 產生，標題尚未定稿。
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
            data = self.chat_json(messages)
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
                contrib_lines.append(f"- [{ag}] {stmt}")
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
            data = self.chat_json(messages)
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
        將多個 open_question 決策議題合併為單一議題，避免逐題拆散討論。
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

        escalated_questions: List[str] = []
        for q in artifact.get("open_questions", []):
            if q.get("status") == "answered":
                continue
            if not self.should_escalate_open_question(q):
                continue
            to_agent = (q.get("to") or q.get("to_agent") or "").strip()
            if to_agent in registered:
                related_agents.add(to_agent)
            question = str(q.get("question") or "").strip()
            if question:
                escalated_questions.append(f"- {question}")

        participants = [a for a in registered if a in related_agents]
        if not participants:
            participants = list(registered)

        source_ids: List[str] = []
        source_issue_ids: List[str] = []
        descriptions: List[str] = []
        titles: List[str] = []
        seen_ids = set()
        seen_issue_ids = set()
        for it in open_items:
            title = str(it.get("title") or "").strip()
            description = str(it.get("description") or "").strip()
            if title:
                titles.append(title)
            if description:
                descriptions.append(f"- {title or 'open_question'}: {description}")
            for sid in (it.get("source_ids", []) or []):
                if not sid or sid in seen_ids:
                    continue
                seen_ids.add(sid)
                source_ids.append(sid)
            for issue_id in (it.get("source_issue_ids", []) or []):
                issue_id = str(issue_id or "").strip()
                if issue_id and issue_id not in seen_issue_ids:
                    seen_issue_ids.add(issue_id)
                    source_issue_ids.append(issue_id)

        merged_title = "開放問題集中回覆"
        if len(open_items) == 1 and titles:
            merged_title = titles[0]
        body_parts = []
        if descriptions:
            body_parts.append("來源議題：\n" + "\n".join(descriptions))
        if escalated_questions:
            body_parts.append("待回覆 open_questions：\n" + "\n".join(escalated_questions))
        if not body_parts:
            body_parts.append("本議題缺少具體 open_questions；請先確認來源 proposal 是否可補齊。")

        merged_item = {
            "title": merged_title,
            "description": "\n\n".join(body_parts),
            "category": "open_question",
            "participants": participants,
            "discussion_mode": "simultaneous",
            "speaking_order": participants,
            "source_ids": source_ids,
            "source_issue_ids": source_issue_ids,
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
        """判斷 open question 是否應升級為正式 decision topic。"""
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
        return False

    def plan_agenda_action_impl(
        self,
        state_summary: Dict[str, Any],
        last_observation: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Agenda action 的實際 planner；由 OPA path 呼叫。"""
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
    你是本輪主持人。根據當前狀態與上一動結果，選下一個動作。

    # 動作
    - generate_decision_topics：topics 為空時
    - expand_decision_topics：僅在 state.can_expand_decision_topics=true 且確有新議題時
    - start_discussion：{{"topic_id":"T-01"}}
    - resolve_topic：{{"topic_id":"T-01"}}，需已 start_discussion
    {escalate_action}- save_topic：{{"topic_id":"T-01"}}，需已 resolve 或 escalate
    - finish_round：僅在 formal topics 已 save、queue 已處理或遞延，且無需 expand / escalate 時

    # 當前狀態
    {state_text}

    # 上一步結果
    {obs_text}

    # 規則
    - topics 為空先 generate_decision_topics
    - queue-first：能由 clarification / direct_apply / human_decision 先處理的議題，不要急著重開 formal meeting
    - topic 順序：start_discussion → resolve_topic → save_topic{escalate_hint}
    - 若上一步 resolve_topic 結果含 needs_human=true，必須先 escalate_to_human 再 save_topic
    - queue 未處理完不得 finish_round
    - 有 deferred 項或新 open_questions 時，先判斷 expand / escalate；需求品質問題應併入正式議題討論
    - 若某題在討論後已明確自然收斂，應直接 resolve_topic 整理結論。
    - formal meeting 題目經討論後仍無法收斂時，resolve_topic 會整理決策選項與 recommendation，等待使用者確認。
    - 所有議題 save 完畢且 can_expand_decision_topics=true 時，應主動評估是否有新議題需補充討論（expand_decision_topics）；確認無追加需求才 finish_round
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
                response = self.chat_json(messages)
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
        recent_ask_history: Optional[List[Dict[str, Any]]] = None,
        ) -> Dict[str, Any]:
        """由 Mediator 逐輪決定需求擷取會議階段、發言模式、參與者與訪談對象。"""
        prev = previous_turn_summary or {}
        default_interviewers = [p for p in default_participants if p != "user"]
        stakeholder_rows = [
            {
                "name": str(row.get("name") or "").strip(),
                "text": row.get("text") or [],
            }
            for row in (artifact.get("stakeholders", []) or [])
            if isinstance(row, dict) and str(row.get("name") or "").strip()
        ]
        stakeholder_names = [row["name"] for row in stakeholder_rows]
        if not stakeholder_names:
            stakeholder_names = ["user"]
        default_sequence = [p for p in default_interviewers if p in {"analyst", "modeler", "expert"}]
        if not default_sequence:
            default_sequence = list(default_interviewers)
        if "user" in default_participants:
            default_sequence = default_sequence + ["user"]
        prompt = f"""# 任務
你是需求擷取會議主持人。請根據目前需求理解、已選定利害關係人、最近對話與訪談記憶，安排本輪需求擷取會議。

你要決定：
1. meeting_phase
2. discussion_mode
3. participants
4. speaking_order（只有 sequential 需要；最後一定是 user）
5. target_stakeholders
6. goal
7. agent_actions

# 本輪資訊
- turn: {turn}/{max_turns}
- default_participants: {default_participants}
- default_mode: {default_mode}
- default_sequential_order: {default_sequence}

# 已選定利害關係人
{json.dumps(stakeholder_rows, ensure_ascii=False, indent=2)}

# 上一輪摘要
{json.dumps(prev, ensure_ascii=False, indent=2)}

# 最近幾輪正式提問與 user 回答
{json.dumps(recent_ask_history or [], ensure_ascii=False, indent=2)}

# 訪談記憶（避免重複）
- confirmed_topics：已確認方向，不要重問，只能在需要收斂時重述。
- closed_topics：User 已回答、不在意或不想深入的方向，除非出現矛盾，否則視為關閉。
- do_not_repeat：本輪不得原樣追問的問題類型。
{json.dumps({
    "confirmed_topics": prev.get("confirmed_topics", []),
    "closed_topics": prev.get("closed_topics", []),
    "do_not_repeat": prev.get("do_not_repeat", []),
}, ensure_ascii=False, indent=2)}

# 會議階段
meeting_phase 只能選：
- initial_requirement：對齊目前需求理解、背景、痛點。
- requirement_discussion：深入釐清流程、內容、互動、呈現、限制或例外。
- conclusion：整理目前理解，請 user 確認是否正確或遺漏，或提議收束。

# 發言模式
discussion_mode 只能選：
- sequential：需要逐一承接前面發言、釐清單一主軸或收斂。必須輸出 speaking_order，且最後一定是 user。
- simultaneous：需要 analyst / expert / modeler 各自從不同角度獨立提出問題。不要輸出 speaking_order，User 之後會逐題回答每個問題。

# 訪談推進原則
請像真實需求訪談主持人一樣，根據 user 已回答內容決定下一個最自然、最能補足需求理解的問題。不要為了覆蓋分類而硬問。

請先補足需求主幹，再進入細節審查。需求主幹包含：
- 使用者目標與需求動機。
- 主要使用流程與任務完成方式。
- 系統主要產出、回應或狀態改變。
- 使用者判斷結果有用、正確、足夠或可接受的標準。
- 資訊組織、呈現、互動或體驗偏好。
- 必須具備與可以延後的能力。

在需求主幹尚未清楚前，不要優先安排細節審查問題。只有在 user 主動提到，或該問題會直接改變主要需求、使用流程、產出結果、結果可用性或需求成立性時，才進入細節審查。

如果 user 的回答自然帶到下一個方向，就順著回答追問；不要硬切換到尚未覆蓋但當下不重要的方向。

# 角色分工
- analyst 適合使用情境與目標、產出內容與優先級、呈現方式與使用判斷、收束確認。
- modeler 適合使用流程與互動、角色互動、狀態變化、判斷點、例外流程與人工介入。
- expert 只在風險或外部限制會影響需求成立、結果可信度或使用者接受度時深入。

# agent action
你必須為每個非 user agent 指定 action：
- ask_user：本輪主要向 user 問一個主問題。
- supplement_question：從該角色角度補一個不重複的 user 問題。
- review_only：只審查目前理解，不問 user。
- propose_finish：提議結束需求擷取。

# 規則
- participants 只能從 default_participants 選，且必須包含 user。
- target_stakeholders 只能從已選定利害關係人名稱中選，不得新增角色。
- 每輪至少指定 1 個 target_stakeholder，最多指定 3 個。
- sequential 時 speaking_order 最後一定是 user；user 前至少一位 agent。
- simultaneous 時不要輸出 speaking_order；participants 應包含 2-3 位非 user agent 與 user。
- 除非本輪要 propose_finish，否則至少一個非 user agent 的 action 必須是 ask_user 或 supplement_question。
- review_only 不可向 user 提問，只能做角色審查。
- propose_finish 只能在資訊足夠收束時使用；若使用 propose_finish，該 agent 的發言只能輸出固定停止句。
- 若上一輪已經確認某一方向，本輪應優先順著 user 回答推進到下一個自然缺口；若同一缺口仍重要，必須換成更具體但不誘導的問法。
- 不要重問 confirmed_topics、closed_topics 或 do_not_repeat 中的方向；如果 user 說過不在意、已列過、已覆蓋，就換下一個未確認的大方向。
- 僅輸出 JSON，不要附加說明。

# 輸出 JSON
{{
  "participants": {json.dumps(default_participants, ensure_ascii=False)},
  "meeting_phase": "initial_requirement | requirement_discussion | conclusion",
  "discussion_mode": "sequential | simultaneous",
  "speaking_order": {json.dumps(default_sequence, ensure_ascii=False)},
  "target_stakeholders": {json.dumps(stakeholder_names[:1], ensure_ascii=False)},
  "goal": "本輪訪談目標",
  "agent_actions": {{
    "analyst": {{"action": "ask_user | supplement_question | review_only | propose_finish", "focus": "本輪角色焦點"}},
    "expert": {{"action": "ask_user | supplement_question | review_only | propose_finish", "focus": "本輪角色焦點"}},
    "modeler": {{"action": "ask_user | supplement_question | review_only | propose_finish", "focus": "本輪角色焦點"}}
  }}
}}"""

        messages = self.build_direct_messages(prompt)
        try:
            data = self.chat_json(messages)
        except Exception as e:
            self.logger.warning("逐輪策略決策失敗，改用預設：%s", e)
            data = {
                "participants": list(default_participants),
                "meeting_phase": "initial_requirement" if turn <= 1 else "requirement_discussion",
                "discussion_mode": "sequential",
                "speaking_order": list(default_sequence),
                "target_stakeholders": stakeholder_names[:1],
                "goal": "釐清目前需求理解中最重要的缺口。",
                "agent_actions": {
                    "analyst": {"action": "ask_user", "focus": "釐清需求主幹中最重要的缺口。"},
                    "modeler": {"action": "supplement_question", "focus": "補足主要使用流程或任務完成方式。"},
                    "expert": {"action": "review_only", "focus": "檢查需求成立性、可信度與使用者接受度。"},
                },
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
        for role in ("analyst", "expert", "modeler"):
            if role in allowed_set and role not in participants:
                insert_at = len(participants)
                if "user" in participants:
                    insert_at = participants.index("user")
                participants.insert(insert_at, role)

        participants_set = set(participants)
        mode = str(data.get("discussion_mode") or default_mode or "sequential").strip().lower()
        if mode not in {"sequential", "simultaneous"}:
            mode = "sequential"

        phase = str(data.get("meeting_phase") or "").strip()
        if phase not in {"initial_requirement", "requirement_discussion", "conclusion"}:
            phase = "initial_requirement" if turn <= 1 else "requirement_discussion"

        target_raw = data.get("target_stakeholders") or []
        target_stakeholders: List[str] = []
        for item in target_raw:
            name = str(item or "").strip()
            if name and name in stakeholder_names and name not in target_stakeholders:
                target_stakeholders.append(name)
            if len(target_stakeholders) >= 3:
                break
        if not target_stakeholders:
            target_stakeholders = stakeholder_names[:1]

        speaking: List[str] = []
        if mode == "sequential":
            raw_order = data.get("speaking_order") or default_sequence
            for item in raw_order:
                role = str(item or "").strip()
                if role in participants_set and role != "user" and role not in speaking:
                    speaking.append(role)
            if not speaking:
                speaking = [p for p in default_sequence if p in participants_set and p != "user"][:2]
            if "user" in participants_set:
                speaking.append("user")
        else:
            speaking = []

        allowed_actions = {"ask_user", "supplement_question", "review_only", "propose_finish"}
        raw_agent_actions = data.get("agent_actions") if isinstance(data.get("agent_actions"), dict) else {}
        agent_actions: Dict[str, Dict[str, str]] = {}
        for role in [p for p in participants if p != "user"]:
            raw_action = raw_agent_actions.get(role) if isinstance(raw_agent_actions, dict) else {}
            raw_action = raw_action if isinstance(raw_action, dict) else {}
            action = str(raw_action.get("action") or "").strip().lower()
            if action not in allowed_actions:
                if role == "analyst":
                    action = "ask_user"
                elif role == "modeler":
                    action = "supplement_question"
                else:
                    action = "review_only"
            focus = str(raw_action.get("focus") or "").strip()
            if not focus:
                if role == "analyst":
                    focus = "需求意圖、主要產出、成功標準或收束確認。"
                elif role == "modeler":
                    focus = "主要使用流程、任務完成方式或流程缺口。"
                else:
                    focus = "需求成立性、結果可信度或使用者接受度。"
            agent_actions[role] = {"action": action, "focus": focus}

        has_finish_proposal = any(
            row.get("action") == "propose_finish" for row in agent_actions.values()
        )
        has_user_question = any(
            row.get("action") in {"ask_user", "supplement_question"}
            for row in agent_actions.values()
        )
        if not has_finish_proposal and not has_user_question:
            fallback_role = "analyst" if "analyst" in agent_actions else next(iter(agent_actions), "")
            if fallback_role:
                agent_actions[fallback_role]["action"] = "ask_user"

        return {
            "participants": participants,
            "meeting_phase": phase,
            "discussion_mode": mode,
            "speaking_order": speaking,
            "target_stakeholders": target_stakeholders,
            "goal": str(data.get("goal") or "").strip() or "釐清目前需求理解中最重要的缺口。",
            "agent_actions": agent_actions,
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
                if n in {"analyst", "expert", "modeler"}
            ]
        if not participants_def:
            participants_def = ["analyst", "expert", "modeler"]

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
            raw = self.chat_json(messages)
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
