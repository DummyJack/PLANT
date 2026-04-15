import json
from typing import Dict, List, Optional, Any
from agents.base import BaseAgent
from utils import (
    analyst_draft_decision_table_note,
    current_output_language,
    short_reasoning_line,
)


ANALYST_REVIEW_ACTIONS = [
    "scan_discussions",
    "detect_conflicts",
    "update_requirements",
    "flag_issue",
    "done",
]

ANALYST_PROJECT_SYSTEM_PROMPT = """你是需求分析師，負責把多方意見整理成可落地、可驗證、可追蹤的需求規格。

規則：
1. 主動辨識衝突、缺口與歧義，保留不確定性。
2. 僅整理 scope 內需求；超出範圍者保留待決。
3. 可修正文句、結構與欄位，但不得自行解除 trade-off、裁定衝突、擴張 scope 或刪除有爭議需求。
4. 重大變更優先產生 requirement_change_candidates；只有低風險變更可自動落地。
5. 需求應盡量清楚、可驗證、可測試；不足時標記待確認。"""


class AnalystAgent(BaseAgent):
    name = "analyst"

    system_prompt = ""

    def __init__(
        self,
        model,
        tools: Optional[list] = None,
        registry=None,
        project_config=None,
    ):
        super().__init__(
            model,
            tools=tools,
            registry=registry,
            skill_names=["conflict-analyzer", "requirements-analyst"],
            project_config=project_config,
        )
        from agents.skills.base import get_skill

        parts = []
        for skill_name in ("requirements-analyst", "conflict-analyzer"):
            skill = get_skill(skill_name)
            if skill.get("content_system"):
                parts.append(skill["content_system"])
        blocks = [ANALYST_PROJECT_SYSTEM_PROMPT]
        blocks.extend(parts)
        self.system_prompt = "\n\n---\n\n".join([b for b in blocks if b])

    # ===== Monitor =====
    def run_review_loop(self, artifact, recent_discussions=None, *, max_iterations):
        observation = None
        actions_taken = []
        pending_issues = []
        scan_results = None
        loop_cap = self.self_review_round_cap()
        effective_max = min(max_iterations, loop_cap)
        i = 0

        while i < effective_max:
            state = self.build_review_state(
                artifact, recent_discussions, actions_taken,
                scan_results, i, effective_max,
            )
            decision = self.decide_next_review_action(state, observation)
            if i == 0:
                n = decision.get("max_iterations")
                if n is not None and isinstance(n, int) and 1 <= n <= effective_max:
                    effective_max = n
                    self.logger.info("  Analyst review 輪數: %s/%s", effective_max, loop_cap)
            action = decision.get("action", "done")
            self.logger.info(f"  Analyst review [{i + 1}/{effective_max}]: {action}")
            if action == "done" or action not in ANALYST_REVIEW_ACTIONS:
                break

            params = decision.get("params") or {}
            observation = self.execute_review_action(
                action, params, artifact, pending_issues, recent_discussions,
            )
            if action == "scan_discussions" and observation.get("result"):
                scan_results = observation["result"]
            actions_taken.append({
                "action": action,
                "params": params,
                "result_summary": observation.get("summary", ""),
            })
            if observation.get("error"):
                self.logger.warning(f"  Analyst review error: {observation['error']}")
            i += 1

        return {
            "agent": self.name,
            "actions_taken": actions_taken,
            "pending_issues": pending_issues,
        }

    def build_review_state(
        self, artifact, recent_discussions, actions_taken,
        scan_results, iteration, max_iterations,
    ):
        reqs = artifact.get("requirements", [])
        summary_reqs = [
            {"id": r.get("id"), "type": r.get("type"),
             "text": (r.get("text") or "")}
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
        state = {
            "requirements_count": len(reqs),
            "requirements": summary_reqs,
            "conflicts": conflicts,
            "recent_discussions": disc_summaries,
            "has_scan_results": scan_results is not None,
            "actions_taken": actions_taken,
            "iteration": iteration + 1,
            "max_iterations": max_iterations,
        }
        if scan_results:
            state["scan_highlights"] = {
                "key_changes": scan_results.get("key_changes", []),
                "potential_conflicts": scan_results.get(
                    "potential_conflicts", []
                ),
            }
        return state

    # ===== Plan =====
    def decide_next_review_action(self, state, last_observation=None):
        state_text = json.dumps(state, ensure_ascii=False, indent=2)
        obs_text = json.dumps(last_observation or {}, ensure_ascii=False, indent=2)
        sr_current = int(state.get("max_iterations") or 1)

        user_prompt = f"""# 任務
你是需求分析師。根據當前狀態與上一步結果，選下一個動作。

# 動作
- scan_discussions：先掃近期討論
- detect_conflicts：重新檢查需求衝突
- update_requirements：依已確認討論/決策整理需求
- flag_issue：{{"description":"問題描述"}}
- done：結束

# 當前狀態
{state_text}

# 上一步結果
{obs_text}

# 規則
- 第一輪可選填 max_iterations=1-{sr_current}；不填就沿用 {sr_current}
- 有近期討論且尚未掃描：先 scan_discussions
- 掃描後有新衝突跡象：detect_conflicts
- 已有決策或已解衝突影響需求：update_requirements
- 無法自行釐清且需要會議處理：flag_issue
- 需要 requirements/conflicts/decisions/open_questions 細節時，先用 artifact_query
- artifact_query 例子：
  - {{"mode":"summarize","section":"conflicts"}}
  - {{"mode":"find_items","section":"conflicts","filters":{{"status":"pending"}},"compact":true}}
  - {{"mode":"related_context","item_id":"REQ-001","compact":true}}
  - {{"mode":"get_section","section":"requirements","compact":true,"limit":20}}
- 無需進一步分析就選 done
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
            self.logger.warning(f"Analyst review 決策失敗: {e}")
            return {"action": "done", "params": {}, "reasoning": f"fallback: {e}"}

        action = (response.get("action") or "").strip()
        if action not in ANALYST_REVIEW_ACTIONS:
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
        max_items: int = 3,
    ) -> List[Dict[str, Any]]:
        proposals: List[Dict[str, Any]] = []
        for c in artifact.get("conflicts", []):
            cid = (c.get("id") or "").strip()
            label = (c.get("label") or "").strip()
            if not cid or label not in ("Conflict", "Neutral"):
                continue
            category = "conflict_discussion"
            if label == "Conflict":
                title = f"{cid} 衝突判定與解法協調"
                why_now = "目前仍為 Conflict，需會議協調可執行決策。"
                routing_preference = "formal_meeting"
                requires_multi_party = True
                blocks_decision = True
            else:
                title = f"{cid} Neutral 判定再確認"
                why_now = "避免 Neutral 誤判，先快速釐清是否真的需要升級為正式衝突處理。"
                routing_preference = "direct_clarification"
                requires_multi_party = False
                blocks_decision = False
            proposals.append(
                {
                    "title": title,
                    "description": (c.get("description") or "").strip(),
                    "category": category,
                    "participants": ["analyst", "expert", "modeler", "user"],
                    "discussion_mode": "sequential",
                    "speaking_order": ["analyst", "expert", "modeler", "user"],
                    "source_ids": [cid] + list(c.get("requirement_ids", []) or []),
                    "priority_hint": "high" if label == "Conflict" else "medium",
                    "impact_level": "high" if label == "Conflict" else "medium",
                    "why_now": why_now,
                    "requires_multi_party": requires_multi_party,
                    "blocks_decision": blocks_decision,
                    "routing_preference": routing_preference,
                    "proposed_by": "analyst",
                    "round": round_num,
                }
            )

        for oq in artifact.get("open_questions", []):
            if oq.get("status") == "answered":
                continue
            q = (oq.get("question") or "").strip()
            if not q:
                continue
            src = str(oq.get("source_conflict_id") or "").strip()
            proposals.append(
                {
                    "title": "待回答開放問題釐清",
                    "description": q,
                    "category": "open_question",
                    "participants": ["analyst", "expert", "modeler", "user"],
                    "discussion_mode": "simultaneous",
                    "speaking_order": ["analyst", "expert", "modeler", "user"],
                    "source_ids": [src] if src else [],
                    "priority_hint": "high",
                    "impact_level": "medium",
                    "why_now": "開放問題未解，會影響本輪收斂品質。",
                    "requires_multi_party": False,
                    "blocks_decision": True,
                    "routing_preference": "direct_clarification",
                    "proposed_by": "analyst",
                    "round": round_num,
                }
            )

        return proposals[: max(1, max_items)]

    # ===== Action: conflict analysis =====
    def run_conflict_detection(self, artifact: Dict) -> Dict:
        """依 conflict-analyzer skill 僅針對「需求」做 Conflict 辨識：判斷為衝突則 label=Conflict，無衝突則 label=Neutral。"""
        meta = artifact.get("meta") or {}
        requirements = artifact.get("requirements", [])
        # 通用布林開關：
        # - True  : pairwise 後再做整體檢查（可抓 3+ 需求衝突）
        # - False : 只做 pairwise
        holistic_enabled_cfg = self.project_config.get(
            "enable_all_conflict_check", True
        )
        holistic_enabled = bool(
            meta.get("enable_all_conflict_check", holistic_enabled_cfg)
        )

        pairwise_mode = bool(meta.get("pairwise_only"))
        n_pairs = 0
        pairwise_extra = ""
        pair_id_prefix = str(meta.get("pair_id_prefix") or "PAIR").strip() or "PAIR"
        if pairwise_mode:
            n_pairs = int(meta.get("pair_count") or 0)
            if n_pairs <= 0:
                return {**artifact, "conflicts": list(artifact.get("conflicts", []))}
            # 已明確提供 pairwise 對照時，固定採 pairwise-only 流程。
            holistic_enabled = False
            lines = []
            for i in range(n_pairs):
                rid_a, rid_b = (
                    f"{pair_id_prefix}-P{i}-a",
                    f"{pair_id_prefix}-P{i}-b",
                )
                ta = tb = ""
                for r in requirements:
                    if not isinstance(r, dict):
                        continue
                    if str(r.get("id") or "").strip() == rid_a:
                        ta = str(r.get("text") or "").strip()
                    if str(r.get("id") or "").strip() == rid_b:
                        tb = str(r.get("text") or "").strip()
                lines.append(
                    f"- pair_index={i}  ids=[{rid_a},{rid_b}]  A={ta[:500]}  B={tb[:500]}"
                )
            pairwise_extra = (
                f"\n\n【pairwise 模式附加規則】\n"
                f"- 以下共有 {n_pairs} 對需求，對與對完全獨立。\n"
                "- 你只能比較同一 pair_index 下的 A 與 B，絕不可跨 pair 比較。\n"
                f"- 每一對都必須輸出恰好一筆結果，共 {n_pairs} 筆；"
                f"pair_index 必須涵蓋 0..{n_pairs - 1} 各一次。\n"
                "- 每筆必含 pair_index、label、description、requirement_ids；"
                "其中 requirement_ids 必須對應該對的兩個 id。\n\n"
                "對照表：\n"
                f"{chr(10).join(lines)}\n\n"
                "輸出格式（嚴格）：\n"
                '{"conflicts":[{"pair_index":0,"label":"Conflict","description":"...",'
                f'"requirement_ids":["{pair_id_prefix}-P0-a","{pair_id_prefix}-P0-b"]}}, ...]}}'
            )

        context: Dict[str, Any] = {"requirements": requirements}
        if artifact.get("stakeholders"):
            context["stakeholders"] = artifact["stakeholders"]
        if artifact.get("scope"):
            context["scope"] = artifact["scope"]
        base_task = """依 conflict-analyzer skill，僅根據 Context.requirements 辨識衝突；本步不看系統模型或其他回饋。

規則：
- label 只用英文 "Conflict" 或 "Neutral"。
- references/conflict_patterns.md 中的各類 pattern 只能作為候選掃描線索，不可因為符合某個 pattern 就直接判為 Conflict。
- 是否標為 Conflict，最終仍必須回到本題的核心判準：兩項需求是否明確互斥、無法同時成立、或一方成立將直接違反另一方。
- 若某筆需求僅看起來屬於某類 conflict pattern，但最終可確認兩項需求既不衝突、也不重複，且沒有直接語義關係，才可標為 Neutral。
- 不要為了替 conflict_type 分類而過度升級標籤；label 判定優先於 conflict_type。
- conflict_type 只是描述結果，不是產生 Conflict 的理由本身。
- 輸出需同時包含部分 Conflict 與有分析價值的 Neutral，不要為湊數產生空泛 Neutral。
- 只有在兩項需求存在明確互斥、無法同時成立、或一方成立將直接違反另一方時，才標為 Conflict。
- 若只是資訊不足、語意模糊、範圍未明、角色不同、情境不同、優先級不同或屬於一般 tradeoff，不能因看不出衝突就直接標為 Neutral；只有在可明確判斷兩項需求既不衝突、也不重複，且沒有直接語義關係時，才可標為 Neutral。
- 不要把「尚未決定怎麼做」或「仍需補充限制」誤判為 Conflict。
- Conflict：需有 description，並填 requirement_ids 或 related_requirements；conflict_type 只做描述。
- 你需要在整包 requirements 中找出所有具分析價值的衝突對或衝突群，不可因先找到一組就停止。
- 若存在多組彼此獨立的衝突（例如 1,2 與 3,4），應分別輸出為不同的 Conflict 項目。
- 同一條 requirement 可同時參與多個 Conflict；不要為了避免重複而省略真實衝突。
- 若多條需求其實屬於同一個互斥核心，再合併為同一筆 Conflict；否則應拆開輸出。
- requirement_ids 或 related_requirements 必須精確對應到該筆 Conflict 直接涉及的需求；若無法明確對應，不要臆測或硬配。
- 每筆 Conflict 的 description 必須清楚指出：衝突的需求是哪些、互斥點是什麼、為何不能同時成立。
- Neutral：需有 description；可選填 requirement_ids；不需 conflict_type。
- Neutral 僅用於兩項需求既不衝突、也不重複，且彼此沒有直接語義關係的情況。
- 若兩項需求之間存在直接語義關聯、功能依賴、範圍重疊、條件約束關係，或只是重述/改寫，不要標為 Neutral。
- Neutral 的 description 必須說明為何這兩項需求彼此無衝突、無重複、且無直接語義關係。

只輸出一個 JSON 物件：{{"conflicts":[...]}}。勿輸出 Markdown 或其他文字。"""

        pairwise_only_extra = """

【pairwise-only 模式附加規則】
- 請優先以兩兩（pairwise）角度掃描需求關係後輸出結果。
- 不要輸出需要 3 條以上需求同時成立才會出現的群組衝突。"""

        holistic_extra = """

【pairwise+holistic 模式附加規則】
- 你可先利用 Context.pairwise_conflict_hints 作為線索，但最終請做整體一致性檢查。
- 除了兩兩衝突，也要找出三條以上需求共同造成的群組衝突。"""

        task = base_task + pairwise_extra
        if (not holistic_enabled) and (not pairwise_mode):
            task += pairwise_only_extra
        if holistic_enabled and not pairwise_mode:
            pairwise_hint_task = base_task + pairwise_only_extra
            try:
                hint_raw = self.invoke_skill(
                    "conflict-analyzer", pairwise_hint_task, context=context
                )
                hint_data = self.parse_topic_response_json(hint_raw)
                hints = hint_data.get("conflicts", [])
                if isinstance(hints, list) and hints:
                    context["pairwise_conflict_hints"] = hints
            except Exception as e:
                self.logger.warning(f"pairwise 預掃描失敗，改以整體檢查繼續: {e}")
            task += holistic_extra

        try:
            raw = self.invoke_skill("conflict-analyzer", task, context=context)
            data = self.parse_topic_response_json(raw)
        except Exception as e:
            if pairwise_mode:
                self.logger.warning(f"pairwise 批次衝突分析失敗: {e}")
                return {
                    **artifact,
                    "conflicts": [],
                }
            self.logger.warning(f"Conflict 分析失敗: {e}")
            return artifact

        raw_list = data.get("conflicts", [])
        if not isinstance(raw_list, list):
            raw_list = []

        if pairwise_mode:
            by_pair: Dict[int, Dict[str, Any]] = {}
            for c in raw_list:
                if not isinstance(c, dict):
                    continue
                try:
                    pi = int(c.get("pair_index"))
                except (TypeError, ValueError):
                    continue
                if pi < 0 or pi >= n_pairs:
                    continue
                label = (c.get("label") or "").strip()
                if label not in {"Conflict", "Neutral"}:
                    continue
                rid_a, rid_b = (
                    f"{pair_id_prefix}-P{pi}-a",
                    f"{pair_id_prefix}-P{pi}-b",
                )
                rel = (
                    c.get("requirement_ids")
                    or c.get("related_requirements")
                    or [rid_a, rid_b]
                )
                entry: Dict[str, Any] = {
                    "id": f"PAIR-{pi:03d}",
                    "label": label,
                    "pair_index": pi,
                    "description": (c.get("description") or "").strip(),
                    "requirement_ids": rel if isinstance(rel, list) else [rid_a, rid_b],
                }
                if label == "Conflict":
                    entry["conflict_type"] = (c.get("conflict_type") or "").strip()
                by_pair[pi] = entry

            conflicts: List[Dict[str, Any]] = []
            for i in range(n_pairs):
                if i in by_pair:
                    conflicts.append(by_pair[i])
            missing_pairs = [i for i in range(n_pairs) if i not in by_pair]

            nc = len([x for x in conflicts if x.get("label") == "Conflict"])
            nn = len([x for x in conflicts if x.get("label") == "Neutral"])
            self.logger.info(
                f"pairwise 批次辨識 {n_pairs} 對（Conflict: {nc}，Neutral: {nn}，Missing: {len(missing_pairs)}）"
            )
            return {
                **artifact,
                "conflicts": conflicts,
            }

        conflicts = []
        design_count = 0
        neutral_count = 0
        for c in raw_list:
            label = (c.get("label") or "").strip()
            if label == "Neutral":
                neutral_count += 1
                nf_entry = {
                    "id": f"NF-{neutral_count:02d}",
                    "label": "Neutral",
                    "description": c.get("description", ""),
                }
                conflicts.append(nf_entry)
                continue
            if label != "Conflict":
                continue
            # conflict_type 為描述用，可為 8 類或模型自訂類型，不限制
            ctype = (c.get("conflict_type") or "").strip()
            rel_reqs = c.get("requirement_ids") or c.get("related_requirements") or []
            if c.get("stakeholder_names"):
                cf_id = f"CF-{len([x for x in conflicts if x.get('label') == 'Conflict']) + 1:02d}"
                entry = {
                    "id": cf_id,
                    "label": "Conflict",
                    "description": c.get("description", ""),
                    "stakeholder_names": c.get("stakeholder_names", []),
                    "conflict_type": ctype,
                }
            elif rel_reqs or c.get("requirement_ids"):
                cf_id = f"CF-{len([x for x in conflicts if x.get('label') == 'Conflict']) + 1:02d}"
                entry = {
                    "id": cf_id,
                    "label": "Conflict",
                    "description": c.get("description", ""),
                    "requirement_ids": rel_reqs or c.get("requirement_ids", []),
                    "conflict_type": ctype,
                }
            else:
                design_count += 1
                cf_id = f"CF-D{design_count:02d}"
                entry = {
                    "id": cf_id,
                    "label": "Conflict",
                    "description": c.get("description", ""),
                    "requirement_ids": rel_reqs,
                }
            conflicts.append(entry)

        if conflicts:
            n_conflict = len([x for x in conflicts if x.get("label") == "Conflict"])
            n_neutral = len([x for x in conflicts if x.get("label") == "Neutral"])
            self.logger.info(
                f"辨識出 {len(conflicts)} 筆（Conflict: {n_conflict}，Neutral: {n_neutral}）"
            )
        return {**artifact, "conflicts": conflicts}

    # ===== Action: requirements-analyst (scope/requirements/draft) =====
    def run_requirements_analyst(
        self,
        action: str,
        *,
        rough_idea: str = "",
        stakeholders: Optional[List[Dict]] = None,
        artifact: Optional[Dict[str, Any]] = None,
        draft_version: Optional[int] = None,
        round_num: Optional[int] = None,
        recent_decisions_limit: Optional[int] = None,
    ):
        """requirements-analyst skill 統一入口。

        action:
            "generate_scope"          -> 回傳 Dict (scope)
            "analyze_requirements"    -> 回傳 Dict (requirements list)
            "create_draft"            -> 回傳 str  (Markdown)
            "update_draft"            -> 回傳 Dict (requirements + change_candidates)
        """
        if action == "generate_scope":
            return self._ra_generate_scope(rough_idea, stakeholders or [], artifact=artifact)
        if action == "analyze_requirements":
            return self._ra_analyze_requirements(stakeholders or [])
        if action == "create_draft":
            return self._ra_create_draft(
                artifact or {},
                draft_version=draft_version,
                round_num=round_num,
                recent_decisions_limit=recent_decisions_limit,
            )
        if action == "update_draft":
            return self._ra_update_draft(artifact or {})
        raise ValueError(f"未知 requirements action: {action}")

    def signoff_conflict_recheck(
        self,
        proposal_list: List[Dict[str, Any]],
        discussion_rows: List[Dict[str, Any]],
        extracted_pair_reviews: Optional[List[Dict[str, Any]]] = None,
    ) -> tuple[List[Dict[str, Any]], str]:
        """Analyst 根據 pair_reviews 與原始 requirement pair 做最終裁定。"""
        if not proposal_list:
            return [], ""
        prompt = (
            "你是資深需求分析師（Analyst）。請根據 requirement pair 原文與各 agent 的逐筆 pair_reviews，"
            "對每筆 Conflict/Neutral pair 做最終裁定。\n\n"
            f"# 待裁定項目\n{json.dumps(proposal_list, ensure_ascii=False, indent=2)}\n\n"
            f"# 各 agent 的 pair_reviews\n{json.dumps(extracted_pair_reviews or [], ensure_ascii=False, indent=2)}\n\n"
            f"# 補充會議內容（僅在 pair_reviews 不足時參考）\n{json.dumps(discussion_rows, ensure_ascii=False, indent=2)}\n\n"
            "# 裁定規則\n"
            "- 先看 requirement_a / requirement_b 原文，再看各 agent 的 pair_reviews。\n"
            "- discussion_rows 只在 pair_reviews 證據不足時作補充參考。\n"
            "- 若 pair_reviews 與 pair 原文足以支持改判，new_label 可改為 Conflict 或 Neutral。\n"
            "- 若 extracted_pair_reviews 為空，預設維持 current_label，除非 requirement_a / requirement_b 原文本身已足以明確推翻現標籤。\n"
            "- 若證據不足、理由不一致或沒有明確共識，維持 current_label。\n"
            "- Conflict 只在兩項需求無法同時成立，或一方成立會直接違反另一方時成立。\n"
            "- Neutral 只在兩項需求既不衝突、也不重複，且沒有直接語義關係時成立。\n"
            "- 若兩項需求描述同一功能範圍、同一流程、同一資料處理或同一輸出行為，即表示存在直接語義關係；不能僅因兩者可共存就判為 Neutral。\n"
            "- 若 supporting pair_reviews 主要以 subset、refinement、complementary step 或 same-flow relationship 支持 Neutral，必須重新檢查是否其實已存在直接語義關係；若存在，不可僅因不互斥就維持 Neutral。\n"
            "- 你必須對 proposal_list 中的每一個 pair 都輸出一筆 decision；即使決定維持 current_label，也不可省略。\n"
            "- 只輸出 JSON array，不要輸出 Markdown、程式碼區塊、前言或額外說明。\n"
            "- 請直接做最終裁定，不要重述整場會議。\n\n"
            "# 輸出 JSON array\n"
            '[{"id": "衝突ID", "new_label": "Conflict 或 Neutral", '
            '"reason": "一句繁中裁定理由"}]'
        )
        messages = self.build_direct_messages(prompt)
        raw = (self.model.chat(messages, action="conflict_recheck_signoff") or "").strip()
        text = raw
        if text.startswith("```json"):
            text = text[len("```json") :].strip()
        elif text.startswith("```"):
            text = text[len("```") :].strip()
        if text.endswith("```"):
            text = text[:-3].strip()
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            match = re.search(r"(\[[\s\S]*\])", text)
            if match:
                try:
                    data = json.loads(match.group(1))
                except json.JSONDecodeError:
                    data = None
            else:
                data = None
        if isinstance(data, list):
            return data, raw
        if isinstance(data, dict) and isinstance(data.get("decisions"), list):
            return data["decisions"], raw
        return [], raw

    def extract_elicitation_candidates(
        self,
        discussion_text: str,
        existing_ids: List[str],
    ) -> List[Dict[str, Any]]:
        """從隱性需求挖掘討論中提取候選需求（原始 JSON）。"""
        prompt = (
            "你是需求分析師。以下是一場隱性需求挖掘會議的討論內容。"
            "請從中提取**尚未被記錄**的新需求候選。\n\n"
            f"# 討論內容\n{discussion_text}\n\n"
            f"# 目前已有的需求 ID\n{json.dumps(sorted(existing_ids), ensure_ascii=False)}\n\n"
            "# 規則\n"
            "- 只提取討論中明確提及但尚未被記錄的新需求\n"
            "- 每筆需含：text, type (FR/NFR/constraint), priority (must/should/could), "
            "source_stakeholders, verification_method (test/review/inspection), acceptance_criteria\n"
            "- NFR 的 acceptance_criteria 必須含可量測指標\n"
            "- 若無新需求，回傳空陣列\n"
            "- 不要重複已有需求\n\n"
            '# 輸出 JSON\n{"candidates": [...]}'
        )
        messages = self.build_direct_messages(prompt)
        data = self.model.chat_json(messages, action="elicitation_extract")
        raw = data.get("candidates", []) if isinstance(data, dict) else []
        return raw if isinstance(raw, list) else []

    @staticmethod
    def _normalize_requirement_record(
        req: Dict[str, Any],
        *,
        fallback_source_stakeholders: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        out = dict(req) if isinstance(req, dict) else {}
        out["text"] = str(out.get("text") or "").strip()
        rtype = str(out.get("type") or "FR").strip()
        if rtype not in {"FR", "NFR", "constraint"}:
            rtype = "FR"
        out["type"] = rtype
        priority = str(out.get("priority") or "should").strip()
        if priority not in {"must", "should", "could"}:
            priority = "should"
        out["priority"] = priority
        src = out.get("source_stakeholders")
        if not isinstance(src, list):
            src = []
        src = [str(s).strip() for s in src if str(s).strip()]
        if not src and fallback_source_stakeholders:
            src = [
                str(s).strip()
                for s in fallback_source_stakeholders
                if str(s).strip()
            ]
        out["source_stakeholders"] = src
        out["verification_method"] = str(out.get("verification_method") or "").strip()
        out["acceptance_criteria"] = str(out.get("acceptance_criteria") or "").strip()
        status = str(out.get("status") or "draft").strip().lower()
        if status not in {"draft", "approved", "baselined", "rejected"}:
            status = "draft"
        out["status"] = status
        return out

    def _ra_generate_scope(
        self, rough_idea: str, stakeholders: List[Dict],
        *, artifact: Optional[Dict[str, Any]] = None,
    ) -> Dict:
        context: Dict[str, Any] = {"rough_idea": rough_idea, "stakeholders": stakeholders}
        if artifact:
            if artifact.get("requirements"):
                context["requirements"] = artifact["requirements"]
            if artifact.get("conflicts"):
                context["conflicts"] = artifact["conflicts"]
            dr = (artifact.get("feedback") or {}).get("domain_research")
            if dr:
                context["domain_research"] = dr
            models = (artifact.get("system_models") or {}).get("models")
            if models:
                context["system_models"] = [
                    {"name": m.get("name"), "type": m.get("type")} for m in models
                ]
        task = """依 requirements-analyst skill，根據 Context 產出專案範圍。

只輸出：
{"scope":{"description":"...", "in_scope":["..."], "out_of_scope":["..."]}}

規則：
- description 來自 rough_idea。
- in_scope / out_of_scope 須綜合 stakeholders 需求、requirements、conflicts、domain_research 與 system_models（若有）來判斷邊界。
- 勿輸出 Markdown。"""
        try:
            data = self._invoke_requirements_analyst_json(task, context)
        except Exception as e:
            self.logger.warning(f"scope 生成失敗: {e}")
            return {"in_scope": [], "out_of_scope": [], "description": ""}
        scope = data.get("scope") or {}
        if not isinstance(scope, dict):
            return {"in_scope": [], "out_of_scope": [], "description": ""}
        return {
            "in_scope": scope.get("in_scope", []),
            "out_of_scope": scope.get("out_of_scope", []),
            "description": scope.get("description", ""),
        }

    def _ra_analyze_requirements(self, stakeholders: List[Dict]) -> Dict[str, Any]:
        all_requirements = []
        for idx, one_sh in enumerate(stakeholders):
            sh_label = one_sh.get("name") or one_sh.get("id") or f"利害關係人{idx + 1}"
            context = {"stakeholders": [one_sh]}
            task = f"""依 requirements-analyst skill，根據 Context 中此單一利害關係人產出結構化需求清單。

只輸出：
{{"requirements":[...]}}

每筆需含：
- text
- type（FR 或 NFR）
- priority（must / should / could）
- source_stakeholders: ["{sh_label}"]
- verification_method（test / review / inspection 其中之一）
- acceptance_criteria（可驗證條件，盡量具體；NFR 必須含量測數值如 ≤2s、≥99.9%；禁止「快速」「適當」等模糊詞）

規則：
- 本輪只分析此一利害關係人。
- id 先不要定，由系統後續指派。
- type、priority 維持英文。
- verification_method 需用英文（test/review/inspection）。
- 勿輸出 Markdown。"""
            try:
                data = self._invoke_requirements_analyst_json(task, context)
            except Exception as e:
                self.logger.warning(f"需求分析失敗（{sh_label}）: {e}")
                continue
            reqs = data.get("requirements", [])
            if not isinstance(reqs, list):
                continue
            for r in reqs:
                if not r.get("text"):
                    continue
                normalized = self._normalize_requirement_record(
                    r,
                    fallback_source_stakeholders=[sh_label],
                )
                all_requirements.append(normalized)

        fr_list = [r for r in all_requirements if (r.get("type") or "").strip().upper() == "FR"]
        nfr_list = [r for r in all_requirements if (r.get("type") or "").strip().upper() == "NFR"]
        other_list = [r for r in all_requirements if r not in fr_list and r not in nfr_list]
        for i, r in enumerate(fr_list, 1):
            r["id"] = f"FR-{i}"
        for i, r in enumerate(nfr_list, 1):
            r["id"] = f"NFR-{i}"
        for i, r in enumerate(other_list, 1):
            r.setdefault("type", "FR")
            r["id"] = f"FR-{len(fr_list) + i}"
        return {"requirements": fr_list + nfr_list + other_list}

    def _ra_create_draft(
        self,
        artifact: Dict[str, Any],
        draft_version: Optional[int] = None,
        round_num: Optional[int] = None,
        recent_decisions_limit: Optional[int] = None,
    ) -> str:
        requirements = artifact.get("requirements", [])
        for req in requirements:
            req_norm = self._normalize_requirement_record(req)
            req.update(req_norm)

        n = 10 if recent_decisions_limit is None else max(0, recent_decisions_limit)
        decisions = artifact.get("decisions", [])[-n:] if n else []
        scope = artifact.get("scope", {}) or {}
        feedback = artifact.get("feedback", {}) or {}
        stakeholder_names = [
            (s.get("name") or str(s))
            for s in artifact.get("stakeholders", [])
            if s.get("name") or str(s).strip()
        ]
        context = {
            "scope": scope,
            "project_overview": scope.get("description", ""),
            "stakeholders": artifact.get("stakeholders", []),
            "stakeholder_names": stakeholder_names,
            "requirements": artifact.get("requirements", []),
            "conflicts": artifact.get("conflicts", []),
            "open_questions": artifact.get("open_questions", []),
            "decisions": decisions,
            "system_models": artifact.get("system_models", {}),
            "feedback": feedback,
            "domain_research": feedback.get("domain_research"),
            "draft_version": draft_version if draft_version is not None else 0,
        }
        version_note = ""
        if draft_version is not None:
            version_note = f" 本稿版本: draft_v{draft_version}。"
        if round_num is not None:
            version_note += f" 對應輪次: Round {round_num}。"
        dec_tbl = analyst_draft_decision_table_note()
        task = f"""依 requirements-analyst skill，僅根據 Context 產出完整需求草稿 Markdown。{version_note}

格式要求：
- 只輸出 Markdown，勿包程式碼區塊。
- 不要輸出文件頂層 H1；草稿直接從 Frontmatter 或概觀章節開始。
- Frontmatter 只保留 status、stakeholders；stakeholders 用 Context.stakeholder_names。
- 概觀只寫 Context.scope.description。
- 約束依 Context.feedback 撰寫；勿產出依賴關係或成功標準。
- Scope 章節寫 Context.scope.in_scope 與 Context.scope.out_of_scope。
- 功能性需求用 FR-1、FR-2…；非功能性需求用 NFR-1、NFR-2…。
- 非功能性需求與功能性需求都使用扁平表格格式，不分子類別。
- FR 表格每列至少包含：id、text、priority、source_stakeholders、verification_method、acceptance_criteria。
- NFR 表格每列至少包含：id、text、priority、source_stakeholders、verification_method、acceptance_criteria。
- verification_method 只能使用 test/review/inspection（英文）。
- NFR 的 acceptance_criteria 必須含可量測指標（如 ≤2s、≥99.9%、≤500ms），禁止「快速」「適當」等模糊詞。
- 若 acceptance_criteria 暫缺，請明確標示「待補」。
- {dec_tbl}
- 若 Context.open_questions 有未結案項目，另立「開放問題」章節；若無可省略。"""
        try:
            raw = self._invoke_requirements_analyst_text(task, context)
        except Exception as e:
            self.logger.warning("draft 生成失敗: %s", e)
            return f"# Requirements Draft\n\n（生成失敗: {e}）"
        md = self.strip_code_fences(raw)

        models = artifact.get("system_models", {}).get("models", [])
        if models:
            sys_hdr = "## 系統模型\n"
            md += f"\n\n---\n\n{sys_hdr}"
            for m in models:
                name = m.get("name", "未命名模型")
                plantuml = (m.get("plantuml") or "").strip()
                if plantuml:
                    md += f"\n### {name}\n\n```plantuml\n{plantuml}\n```\n"
        return md

    def _ra_update_draft(self, artifact: Dict) -> Dict:
        context = {
            "requirements": artifact.get("requirements", []),
            "decisions": artifact.get("decisions", []),
            "discussions": artifact.get("discussions", []),
            "conflicts": artifact.get("conflicts", []),
            "scope": artifact.get("scope", {}),
            "domain_research": artifact.get("feedback", {}).get("domain_research"),
            "system_models": artifact.get("system_models", {}),
        }
        task = """依 requirements-analyst skill，基於 Context.requirements 更新需求。

更新邊界：
1. 保留所有既有需求；只調整受本輪 decisions 或 discussions 直接影響的條目。
2. 與本輪無關的需求不要改動。
3. 可追加 scope 內新需求；不得新增超出 scope.out_of_scope 的需求。
4. 輸出的 requirements 陣列必須涵蓋所有既有 id，再視需要追加新項。
5. 已解決的 conflict 對應需求應與決策方向一致。

只輸出一個 JSON 物件：{{"requirements":[...]}}。
每筆需含 id、text、type（FR/NFR/constraint）、priority、source_stakeholders、verification_method、acceptance_criteria；
id、type、priority、verification_method 維持英文。"""
        try:
            data = self._invoke_requirements_analyst_json(task, context)
        except Exception as e:
            self.logger.warning(f"draft 更新失敗: {e}")
            return {
                "requirements": artifact.get("requirements", []),
                "conflicts": artifact.get("conflicts", []),
                "requirement_change_candidates": [],
            }
        requirements = data.get("requirements", artifact.get("requirements", []))
        if not isinstance(requirements, list):
            requirements = artifact.get("requirements", [])
        prev_by_id = {
            r.get("id"): r for r in artifact.get("requirements", []) if r.get("id")
        }
        returned_ids = {r.get("id") for r in requirements if r.get("id")}
        for pid, prev_req in prev_by_id.items():
            if pid not in returned_ids:
                requirements.append(dict(prev_req))
                self.logger.debug("update_draft: 補回既有需求 %s", pid)
        for req in requirements:
            normalized = self._normalize_requirement_record(req)
            req.update(normalized)
        change_candidates = self._build_requirement_change_candidates(
            artifact.get("requirements", []),
            requirements,
            artifact=artifact,
        )
        applied_requirements = self._apply_safe_requirement_changes(
            artifact.get("requirements", []),
            change_candidates,
        )
        return {
            "requirements": applied_requirements,
            "conflicts": artifact.get("conflicts", []),
            "requirement_change_candidates": change_candidates,
        }

    def _build_requirement_change_candidates(
        self,
        previous_requirements: List[Dict[str, Any]],
        updated_requirements: List[Dict[str, Any]],
        *,
        artifact: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """從舊新版需求清單推導可追蹤的變更候選，不自動產生刪除。"""
        previous_by_id = {
            req.get("id"): dict(req)
            for req in previous_requirements
            if isinstance(req, dict) and req.get("id")
        }
        decisions = (artifact or {}).get("decisions", []) or []
        discussions = (artifact or {}).get("discussions", []) or []
        source_ids = [
            item.get("id")
            for item in list(decisions)[-5:] + list(discussions)[-2:]
            if isinstance(item, dict) and item.get("id")
        ]
        candidates: List[Dict[str, Any]] = []
        seen_keys = set()
        next_index = 1

        for req in updated_requirements:
            if not isinstance(req, dict):
                continue
            req_id = req.get("id")
            if not req_id:
                continue
            before = previous_by_id.get(req_id)
            if before is None:
                req_type = str(req.get("type") or "").strip()
                text = str(req.get("text") or "").strip()
                auto_apply_add = (
                    req_type in {"constraint", "NFR"}
                    and bool(source_ids)
                    and bool(text)
                    and len(text) <= 120
                )
                key = ("add", req_id)
                if key in seen_keys:
                    continue
                seen_keys.add(key)
                candidates.append(
                    {
                        "id": f"RC-{next_index:03d}",
                        "requirement_id": req_id,
                        "change_type": "add",
                        "field": "requirement",
                        "before": None,
                        "after": dict(req),
                        "reason": "Added by analyst draft update.",
                        "source_ids": list(source_ids),
                        "status": "proposed" if auto_apply_add else "pending_review",
                        "auto_apply": auto_apply_add,
                    }
                )
                next_index += 1
                continue

            changed_fields = [
                field
                for field in (
                    "text",
                    "type",
                    "priority",
                    "source_stakeholders",
                    "verification_method",
                    "acceptance_criteria",
                )
                if before.get(field) != req.get(field)
            ]
            if not changed_fields:
                continue
            for field in changed_fields:
                key = ("update", req_id, field)
                if key in seen_keys:
                    continue
                seen_keys.add(key)
                candidates.append(
                    {
                        "id": f"RC-{next_index:03d}",
                        "requirement_id": req_id,
                        "change_type": "update",
                        "field": field,
                        "before": before.get(field),
                        "after": req.get(field),
                        "reason": "Updated by analyst draft refresh after decisions/discussions.",
                        "source_ids": list(source_ids),
                        "status": "proposed",
                        "auto_apply": field == "text",
                    }
                )
                next_index += 1

        return candidates

    def _apply_safe_requirement_changes(
        self,
        previous_requirements: List[Dict[str, Any]],
        change_candidates: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """僅自動套用低風險變更；高風險變更保留為 pending candidates。"""
        applied = [
            dict(req)
            for req in previous_requirements
            if isinstance(req, dict)
        ]
        by_id = {
            req.get("id"): req
            for req in applied
            if req.get("id")
        }
        for candidate in change_candidates:
            if not isinstance(candidate, dict):
                continue
            if candidate.get("change_type") != "update":
                continue
            if not candidate.get("auto_apply"):
                candidate["status"] = "pending_review"
                continue
            req = by_id.get(candidate.get("requirement_id"))
            field = candidate.get("field")
            if not req or field != "text":
                candidate["status"] = "pending_review"
                continue
            req[field] = candidate.get("after")
            candidate["status"] = "applied"
        return applied

    def generate_conflict_report(
        self,
        artifact: Dict[str, Any],
        round_num: Optional[int] = None,
        recent_decisions_limit: Optional[int] = None,
    ) -> str:
        """依 conflict-analyzer skill 與 assets/conflict_report_template.json 結構，從 artifact 產出需求 Conflict 分析報告（Markdown）；含所有 Conflict（含已解決）並標示是否已解決。"""
        n = 10 if recent_decisions_limit is None else max(0, recent_decisions_limit)
        decisions = artifact.get("decisions", [])[-n:] if n else []
        all_conflicts = artifact.get("conflicts", [])
        context = {
            "conflicts": all_conflicts,
            "requirements": artifact.get("requirements", []),
            "stakeholders": artifact.get("stakeholders", []),
            "scope": artifact.get("scope", {}),
            "project_overview": (artifact.get("scope") or {}).get("description", ""),
            "open_questions": artifact.get("open_questions", []),
            "decisions": decisions,
            "system_models": artifact.get("system_models", {}),
            "round_num": round_num,
            "domain_research": artifact.get("feedback", {}).get("domain_research"),
        }
        task = """依本 skill 與 conflict_report_template.json（已在 skill 附件中）產出需求 Conflict 分析報告。

規則：
- Context.conflicts 全部都要列入。
- label=Conflict 視為 unresolved；label=Neutral 視為 resolved。
- resolved / unresolved 統計請與此規則一致。
- 其餘章節依 report_template 結構整理。

只輸出 Markdown，勿輸出 JSON 或程式碼區塊。"""
        try:
            raw = self.invoke_skill("conflict-analyzer", task, context=context)
        except Exception as e:
            self.logger.warning("conflict report 生成失敗: %s", e)
            return f"# 需求 Conflict 分析報告\n\n（報告生成失敗: {e}）"
        out = self.strip_code_fences(raw)
        if not out:
            self.logger.warning("conflict report 無內容")
            return "# 需求 Conflict 分析報告\n\n（報告無內容）"
        return out

    def get_optional_skill_context(
        self, topic: Dict, artifact_snapshot: Optional[Dict]
    ) -> Optional[str]:
        """議題為 Conflict 協調時，觸發 conflict-analyzer 產出簡短要點供發言參考。"""
        if topic.get("category") not in ("conflict_discussion",):
            return None
        if "conflict-analyzer" not in self.skill_names:
            return None
        context = {"topic": topic, "artifact_snapshot": artifact_snapshot or {}}
        task = """針對 Context 中的議題與專案狀態，簡要列出 1～3 點 Conflict 分析要點（可含類型、涉及需求 id、建議方向），供會議發言參考。只輸出簡短條列文字，勿 JSON。"""
        try:
            raw = self.invoke_skill("conflict-analyzer", task, context=context)
            return (raw or "").strip()
        except Exception as e:
            self.logger.debug("議程中觸發 conflict-analyzer 失敗: %s", e)
            return None

    def get_resolution_options_for_topic(
        self, topic: Dict, artifact: Dict[str, Any]
    ) -> Optional[Dict]:
        """議題為 Conflict 協調時，依 conflict-analyzer 產出 resolution_options，供人類裁決使用。回傳格式同 Mediator.prepare_human_options：best_options、compromise。"""
        if topic.get("category") not in ("conflict_discussion",):
            return None
        if "conflict-analyzer" not in self.skill_names:
            return None
        source_ids = topic.get("source_ids") or []
        conflict_ids = [
            s
            for s in source_ids
            if isinstance(s, str)
            and (s.startswith("CF-") or s.startswith("CF-D") or s.startswith("NF-"))
        ]
        conflicts = artifact.get("conflicts", [])
        if conflict_ids:
            relevant = [c for c in conflicts if c.get("id") in conflict_ids]
        else:
            relevant = [c for c in conflicts if c.get("label") == "Conflict"]
        if not relevant:
            return None
        context = {
            "topic": topic,
            "conflicts": relevant,
            "requirements": artifact.get("requirements", []),
            "stakeholders": artifact.get("stakeholders", []),
        }
        task = """針對 Context 中的議題與對應 Conflict/Neutral，依 conflict-analyzer skill 產出解決方案選項。

只輸出一個 JSON 物件，須含：
- resolution_options：每筆含 option、strategy、description、pros、cons、recommendation
- recommended_resolution：建議方案摘要

勿輸出 Markdown 或其它文字。"""
        try:
            raw = self.invoke_skill("conflict-analyzer", task, context=context)
            data = self.parse_topic_response_json(raw)
        except Exception as e:
            self.logger.warning("resolution_options 生成失敗: %s", e)
            return None
        opts = data.get("resolution_options") or []
        recommended = (data.get("recommended_resolution") or "").strip()
        best_options = []
        for i, o in enumerate(opts[:3], 1):
            title = (o.get("strategy") or o.get("option") or "").strip()
            if o.get("option"):
                title = f"方案 {o.get('option')}: {title}"
            desc = (o.get("description") or "").strip()
            if o.get("pros") or o.get("cons"):
                parts = []
                if o.get("pros"):
                    pl = "優點："
                    parts.append(
                        pl
                        + (
                            ", ".join(o["pros"])
                            if isinstance(o["pros"], list)
                            else str(o["pros"])
                        )
                    )
                if o.get("cons"):
                    cl = "缺點："
                    parts.append(
                        cl
                        + (
                            ", ".join(o["cons"])
                            if isinstance(o["cons"], list)
                            else str(o["cons"])
                        )
                    )
                if parts:
                    desc = desc + "\n" + "\n".join(parts) if desc else "\n".join(parts)
            best_options.append(
                {
                    "id": i,
                    "title": title or f"方案 {i}",
                    "description": desc or "(無描述)",
                    "source": "analyst",
                }
            )
        compromise = None
        if recommended:
            c_title = "建議方案（Analyst）"
            c_rat = "依 conflict-analyzer 建議採用的解決方案"
            compromise = {
                "id": 4,
                "title": c_title,
                "description": recommended,
                "rationale": c_rat,
            }
        if not best_options and not compromise:
            return None
        return {"best_options": best_options, "compromise": compromise}

    # ===== Action: meeting response =====
    def respond_to_topic(self, topic, previous_responses=None, artifact_snapshot=None):
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
            tool_hint = "\n# 工具使用\n- 最後**必須**輸出下列 JSON。"

        elicitation_hint = ""
        task_block = "請以需求分析師身分發言，聚焦需求定義、驗收邊界、風險與下一步。"
        rules_block = """- statement 需包含：結論、依據、風險/邊界、建議下一步。
- 依據優先引用 requirement id、conflict id、既有討論或議題描述。
- statement 中涉及需求時，須引用具體 ID（如 FR-01、NFR-02）；NFR 應提及可量測指標。
- 保持中立；資訊不足時明確指出缺口，不可假設已確認。
- 不要講實作細節；投票與最終決議不在此步完成。
- 若需要他人補資訊，才在 open_questions 中提出具體問題。
- open_questions 的 to 欄位只能用系統角色名：user、analyst、expert、modeler；禁止用利害關係人名稱。
- 可用純文字表格、流程或草圖輔助說明；若使用，請放在程式碼區塊。"""
        if topic.get("category") == "conflict_discussion":
            task_block = "請以需求分析師身分逐筆再審查目前這批 Conflict/Neutral pairs，先根據 requirement_a / requirement_b 原文獨立重判，再與 current_label 比較決定 keep 或 modify。"
            rules_block = """- statement 必須是單一合法 JSON object 字串；不可輸出 JSON 以外的前後文。
- statement JSON 結構必須為：{"overall_assessment":"...","pair_reviews":[...]}。
- overall_assessment 用 1-3 句說明整批標註品質是否有系統性偏誤。
- pair_reviews 必須逐筆涵蓋每個 [PAIR-xxx]；每筆都要有：id、independent_label、decision、proposed_label、confidence、reason。
- 先只根據 requirement_a / requirement_b 原文獨立判斷，再與 current_label 比較；不要先順著 current_label 想理由。
- 只有在兩項需求無法同時成立、或一方成立會直接違反另一方時，才支持 Conflict。
- 只有在兩項需求可明確判定為不衝突、不重複，且沒有直接語義關係時，才支持 Neutral。
- 若兩項需求描述同一功能範圍、同一流程、同一資料處理或同一輸出行為，即表示存在直接語義關係；不能僅因兩者可共存就判為 Neutral。
- 若一項需求是另一項的子集、細化、補充步驟或同流程的相鄰行為，不能直接判為 Neutral。
- 若只是語意模糊、範圍未明、角色不同、情境不同、優先級不同或仍需補充條件，不能因看不出衝突就直接支持 Neutral。
- 若支持 Conflict，必須清楚指出互斥點；若支持 Neutral，必須清楚說明為何既不衝突、也不重複，且無直接語義關係。
- 不要跳到實作方案或最終決策。
- 若需要他人補資訊，才在 open_questions 中提出具體問題。
- open_questions 的 to 欄位只能用系統角色名：user、analyst、expert、modeler；禁止用利害關係人名稱。
- 不可用 JSON-like 條列或文字摘要取代合法 JSON。"""
        if topic_id.startswith("ELICIT-") and topic.get("collector_mode"):
            elicitation_hint = """# ELICIT Collector（Analyst）
- 你不是本輪正式提問者。
- 你的任務是替 asker 找出現在最值得問 user 的一個需求缺口。
- 優先補核心需求理解；若核心功能、範圍、偏好仍不清楚，不要先追後段細節。
- 若沒有比既有方向更高價值的新問題，要明講。"""
            task_block = "請以需求分析 collector 身分，輸出一段提問建議，供 asker 整合成正式主問題。"
            rules_block = """- 不要直接對 user 正式發問。
- statement 需包含：需求缺口、建議問題句、為何值得問、如何避免重複。
- 建議問題句只能有 1 個主問題，且要能直接轉成 requirement。
- open_questions 請輸出空陣列。"""
        elif topic_id.startswith("ELICIT-") and str(topic.get("asker_agent") or "").strip() == self.name:
            stop_phrase = (
                "I have gathered enough information"
                if current_output_language() == "en"
                else "我已蒐集足夠資訊"
            )
            elicitation_hint = """# ELICIT Asker（Analyst）
- 你是本輪唯一正式提問者。
- 你的任務是根據前面 collectors 的提問建議，整合成對 user 的唯一主問題。
- 優先補流程、輸入/輸出、驗收條件、使用者偏好與呈現方式等核心缺口。
- 若核心功能或偏好仍不清楚，不要優先追問 exception handling、韌性等後段細節。
- 若 collectors 提出的方向太邊角，改寫成更核心的一題。"""
            task_block = (
                "請以需求分析 interviewer 身分，只輸出對 user 的一個正式主問題（1-3 句）；"
                "若你判斷目前已蒐集到足夠資訊、可以收束本輪需求挖掘，則 statement 請只輸出以下固定句"
                f"（勿加引號、勿改寫、勿額外說明）：{stop_phrase}"
            )
            rules_block = f"""- 若你判斷目前資訊已足以支撐核心需求理解，且再往下追問的增益有限，可直接輸出停止句：{stop_phrase}
- 若核心流程、輸入/輸出範圍、使用者偏好、介面呈現偏好、重要限制仍有明顯空缺，不可停止。
- 若選擇提問，只能問 1 個主問題，不可合併多題。
- 問題必須可回答、可抽取、可直接轉成 requirement。
- 避免使用「還有什麼需求」「請多說一點」等泛問。
- open_questions 請輸出空陣列。"""
        user_prompt = f"""{topic_text}
{prev_text}
{snapshot_text}
{recent_ask_history_text}
{skill_section}
{tool_hint}
{elicitation_hint}

# 任務
{task_block}

# 規則
{rules_block}

# 輸出 JSON
{{{{
    "statement": "針對此議題的完整發言內容",
    "open_questions": [{{{{"to": "目標 agent 名稱", "question": "問題"}}}}]
}}}}"""

        messages = self.build_direct_messages(user_prompt)
        response = self.chat_for_topic_response(messages)

        return {
            "agent": self.name,
            "statement": response.get("statement", ""),
            "open_questions": response.get("open_questions", []),
        }

    def execute_review_action(
        self, action, params, artifact, pending_issues, recent_discussions,
    ):
        obs: Dict = {"action": action, "result": None, "error": None, "summary": ""}

        if action == "scan_discussions":
            if not recent_discussions:
                obs["summary"] = "無近期討論可掃描"
                return obs
            truncated = []
            for disc in recent_discussions:
                topic = disc.get("topic", {})
                contribs = []
                for c in disc.get("contributions", []):
                    resp = c.get("response", {})
                    contribs.append({
                        "agent": c.get("agent"),
                        "statement": (resp.get("statement") or ""),
                    })
                resolution = disc.get("resolution", {})
                truncated.append({
                    "topic": {
                        "id": topic.get("id"),
                        "title": topic.get("title"),
                        "category": topic.get("category"),
                    },
                    "contributions": contribs,
                    "resolution": {
                        "resolution": resolution.get("resolution"),
                        "summary": (resolution.get("summary") or ""),
                    },
                })
            disc_text = json.dumps(truncated, ensure_ascii=False, indent=2)
            task = f"""分析以下近期討論內容，提取關鍵資訊。

{disc_text}

輸出 JSON:
{{
    "key_changes": ["影響需求的重要變更或決策"],
    "new_arguments": ["新提出的論點或立場"],
    "potential_conflicts": ["可能的新 Conflict（含涉及的需求 id）"],
    "requirement_updates_needed": ["需要更新的需求 id 及原因"]
}}
只輸出 JSON。"""
            messages = self.build_direct_messages(task)
            try:
                result = self.model.chat_json(messages)
                obs["result"] = result
                changes = len(result.get("key_changes", []))
                pot = len(result.get("potential_conflicts", []))
                obs["summary"] = f"掃描完成: {changes} 項變更, {pot} 項潛在 Conflict"
            except Exception as e:
                obs["error"] = str(e)
                obs["summary"] = f"掃描失敗: {e}"
            return obs

        if action == "detect_conflicts":
            try:
                old_count = len([
                    c for c in artifact.get("conflicts", [])
                    if c.get("label") == "Conflict"
                ])
                updated = self.run_conflict_detection(artifact)
                artifact["conflicts"] = updated.get(
                    "conflicts", artifact.get("conflicts", [])
                )
                new_conflicts = [
                    c for c in artifact["conflicts"]
                    if c.get("label") == "Conflict"
                ]
                new_neutrals = [
                    c for c in artifact["conflicts"]
                    if c.get("label") == "Neutral"
                ]
                summary = (
                    f"Conflict 偵測: {len(new_conflicts)} Conflict, "
                    f"{len(new_neutrals)} Neutral（前: {old_count} Conflict）"
                )
                obs["summary"] = summary
                obs["result"] = {
                    "total_conflicts": len(new_conflicts),
                    "total_neutrals": len(new_neutrals),
                }
            except Exception as e:
                obs["error"] = str(e)
                obs["summary"] = f"Conflict 偵測失敗: {e}"
            return obs

        if action == "update_requirements":
            try:
                old_count = len(artifact.get("requirements", []))
                draft = self.run_requirements_analyst("update_draft", artifact=artifact)
                artifact["requirements"] = draft.get(
                    "requirements", artifact.get("requirements", [])
                )
                obs["summary"] = (
                    f"需求更新: {len(artifact['requirements'])} 條"
                    f"（前: {old_count}）"
                )
            except Exception as e:
                obs["error"] = str(e)
                obs["summary"] = f"需求更新失敗: {e}"
            return obs

        if action == "flag_issue":
            desc = (params.get("description") or "").strip()
            if not desc:
                obs["error"] = "description 為空"
                return obs
            pending_issues.append({
                "type": "analysis_issue",
                "description": desc,
                "source": "analyst",
            })
            obs["summary"] = f"已標記問題: {desc}"
            return obs

        obs["error"] = f"未知動作: {action}"
        return obs

    # ===== Skill helpers (keep at end) =====
    def _invoke_requirements_analyst_text(
        self, task: str, context: Dict[str, Any]
    ) -> str:
        return self.invoke_skill("requirements-analyst", task, context=context)

    def _invoke_requirements_analyst_json(
        self, task: str, context: Dict[str, Any]
    ) -> Dict[str, Any]:
        raw = self._invoke_requirements_analyst_text(task, context)
        return self.parse_topic_response_json(raw)

    @staticmethod
    def strip_code_fences(text: str) -> str:
        s = (text or "").strip()
        if s.startswith("```"):
            idx = s.find("\n")
            if idx != -1:
                s = s[idx + 1 :]
        if s.endswith("```"):
            s = s[:-3]
        return s.strip()
