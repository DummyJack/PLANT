import json
from typing import Dict, List, Optional, Any
from agents.base import BaseAgent
from utils import (
    analyst_draft_decision_table_note,
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
            category = "conflict_resolution"
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
        requirements = artifact.get("requirements", [])
        context: Dict[str, Any] = {"requirements": requirements}
        if artifact.get("stakeholders"):
            context["stakeholders"] = artifact["stakeholders"]
        if artifact.get("scope"):
            context["scope"] = artifact["scope"]
        task = """依 conflict-analyzer skill，僅根據 Context.requirements 辨識衝突；本步不看系統模型或其他回饋。

規則：
- label 只用英文 "Conflict" 或 "Neutral"。
- 輸出需同時包含部分 Conflict 與有分析價值的 Neutral，不要為湊數產生空泛 Neutral。
- Conflict：需有 description，並填 requirement_ids 或 related_requirements；conflict_type 只做描述。
- Neutral：需有 description；可選填 requirement_ids；不需 conflict_type。

只輸出一個 JSON 物件：{{"conflicts":[...]}}。勿輸出 Markdown 或其他文字。"""

        try:
            raw = self.invoke_skill("conflict-analyzer", task, context=context)
            data = self.parse_topic_response_json(raw)
        except Exception as e:
            self.logger.warning(f"Conflict 分析失敗: {e}")
            return artifact

        raw_list = data.get("conflicts", [])
        if not isinstance(raw_list, list):
            return {**artifact, "conflicts": list(artifact.get("conflicts", []))}

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

規則：
- 本輪只分析此一利害關係人。
- id 先不要定，由系統後續指派。
- type、priority 維持英文。
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
                r.setdefault("source_stakeholders", [sh_label])
                all_requirements.append(r)

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
            req.setdefault("type", "FR")
            req.setdefault("source_stakeholders", [])
            if req.get("priority") not in ("must", "should", "could"):
                req["priority"] = "should"

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
每筆需含 id、text、type（FR/NFR/constraint）、priority、source_stakeholders；id、type、priority 維持英文。"""
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
            if req.get("priority") not in ("must", "should", "could"):
                req["priority"] = "should"
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
                for field in ("text", "type", "priority", "source_stakeholders")
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
        if topic.get("category") not in ("conflict_resolution",):
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
        if topic.get("category") not in ("conflict_resolution",):
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
            tool_hint = "\n# 工具使用\n- 最後**必須**輸出下列 JSON。"

        user_prompt = f"""{topic_text}
{prev_text}
{snapshot_text}
{skill_section}
{tool_hint}

# 任務
請以需求分析師身分發言，聚焦需求定義、驗收邊界、風險與下一步。

# 規則
- statement 需包含：結論、依據、風險/邊界、建議下一步。
- 依據優先引用 requirement id、conflict id、既有討論或議題描述。
- 保持中立；資訊不足時明確指出缺口，不可假設已確認。
- 不要講實作細節；投票與最終決議不在此步完成。
- 若需要他人補資訊，才在 open_questions 中提出具體問題。
- 可用純文字表格、流程或草圖輔助說明；若使用，請放在程式碼區塊。

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
