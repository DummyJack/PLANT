import json
from pathlib import Path
from typing import Dict, List, Optional, Any
from agents.base import BaseAgent
from utils import (
    OUTPUT_LANG_EN,
    analyst_draft_decision_table_note,
    short_reasoning_line,
)

CONFLICT_REPORT_TEMPLATE_PATH = (
    Path(__file__).resolve().parent.parent
    / "skills"
    / "conflict-analyzer"
    / "assets"
    / "conflict_report_template.json"
)

ANALYST_REVIEW_ACTIONS = [
    "scan_discussions",
    "detect_conflicts",
    "update_requirements",
    "flag_issue",
    "done",
]


class AnalystAgent(BaseAgent):
    """需求分析師：賦予 conflict-analyzer、requirements-analyst skill，負責 Conflict 辨識與需求草稿。"""

    name = "analyst"

    system_prompt = ""

    def __init__(self, model, tools: Optional[list] = None, registry=None):
        super().__init__(
            model,
            tools=tools,
            registry=registry,
            skill_names=["conflict-analyzer", "requirements-analyst"],
        )
        from agents.skills.base import get_skill

        parts = []
        for skill_name in ("requirements-analyst", "conflict-analyzer"):
            skill = get_skill(skill_name)
            if skill.get("content_system"):
                parts.append(skill["content_system"])
        if parts:
            self.system_prompt = "\n\n---\n\n".join(parts)

    def run_conflict_detection(self, artifact: Dict) -> Dict:
        """依 conflict-analyzer skill 僅針對「需求」做 Conflict 辨識：判斷為衝突則 label=Conflict，無衝突則 label=Neutral。"""
        requirements = artifact.get("requirements", [])
        context = {"requirements": requirements}
        task = """依 conflict-analyzer skill 的辨識方式，**僅根據 Context 中的需求（requirements）**辨識是否有 Conflict；本階段不看系統模型或其它回饋。
- **label**：判斷為衝突時標記為 "Conflict"，沒有衝突則標記 "Neutral"。此欄位維持英文。
- **輸出須同時包含兩種 label**：陣列中除所有辨識為 Conflict 的項目外，也須包含至少若干筆 label=Neutral 的項目（例如：對關鍵需求、易混淆需求對或高優先級需求經檢視後判定為無衝突，簡述原因），以利後續討論與報告完整呈現。
- **conflict_type**：僅用於描述衝突類型。references 中的 8 種類型為參考；若依自身知識判斷屬於其他類型，也可使用其他類型名稱，仍視為 Conflict。
- 若 label 為 Conflict：須有 description；填 requirement_ids / related_requirements（涉及的需求 id）；conflict_type 為描述用。
- 若 label 為 Neutral：須有 description（可簡述為何判定無衝突）；可選填 requirement_ids 表示檢視過的需求；不需 conflict_type。
輸出「僅一個」JSON 物件，鍵名為 "conflicts"，值為陣列。勿輸出 Markdown 或其它文字，只輸出該 JSON。"""

        try:
            raw = self.invoke_skill("conflict-analyzer", task, context=context)
            data = self.parse_topic_response_json(raw)
        except Exception as e:
            self.logger.warning(f"Conflict 分析 skill 執行失敗: {e}")
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

    @staticmethod
    def _as_bool(value: Any) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() in ("true", "1", "yes", "y")
        return False

    def reassess_conflicts_with_feedback_and_model(
        self, artifact: Dict, stage: str = "pre_meeting"
    ) -> Dict[str, Any]:
        """Analyst 依 feedback + system_models 複核衝突，並判斷是否要進 requirement_clarification。"""
        conflicts = artifact.get("conflicts", [])
        if not conflicts:
            return {
                "conflicts": [],
                "clarification_requests": [],
                "changed_conflict_ids": [],
            }

        context = {
            "stage": stage,
            "requirements": artifact.get("requirements", []),
            "conflicts": conflicts,
            "feedback": artifact.get("feedback") or {},
            "system_models": artifact.get("system_models") or {},
        }
        task = """請依 Context.feedback 與 Context.system_models，逐筆檢視 Context.conflicts 的判斷是否需要調整，並判斷是否必須先做「更深入討論」才能解決。
輸出「僅一個」JSON 物件，格式：
{
  "assessments": [
    {
      "conflict_id": "CF-01 或 NF-01",
      "change_conflict_result": true 或 false,
      "new_label": "Conflict 或 Neutral",
      "needs_deeper_discussion": true 或 false,
      "reason": "繁體中文，簡短理由",
      "clarification_question": "若 needs_deeper_discussion=true，請提供具體要釐清的問題",
      "requirement_ids": ["FR-1", "NFR-2"]
    }
  ]
}
規則：
- change_conflict_result=true 表示你判斷「原本結果應更改」。
- needs_deeper_discussion=true 表示需要進入 requirement_clarification 議題再判定，且此時先不要直接改 label。
- needs_deeper_discussion=false 且 change_conflict_result=true 時，可直接套用 new_label。
- 僅輸出 JSON，不要 Markdown 或其他文字。"""

        try:
            raw = self.invoke_skill("conflict-analyzer", task, context=context)
            data = self.parse_topic_response_json(raw)
        except Exception as e:
            self.logger.warning("Analyst 複核衝突（feedback+model）失敗: %s", e)
            return {
                "conflicts": list(conflicts),
                "clarification_requests": [],
                "changed_conflict_ids": [],
            }

        assessments = data.get("assessments", [])
        if not isinstance(assessments, list):
            return {
                "conflicts": list(conflicts),
                "clarification_requests": [],
                "changed_conflict_ids": [],
            }

        updated_conflicts = [dict(c) for c in conflicts]
        by_id = {c.get("id"): c for c in updated_conflicts if c.get("id")}
        clarification_requests = []
        changed_conflict_ids = []

        for item in assessments:
            if not isinstance(item, dict):
                continue
            cid = (item.get("conflict_id") or "").strip()
            if not cid or cid not in by_id:
                continue
            target = by_id[cid]
            needs_discuss = self._as_bool(item.get("needs_deeper_discussion"))
            change_result = self._as_bool(item.get("change_conflict_result"))
            new_label = (item.get("new_label") or "").strip()
            if new_label not in ("Conflict", "Neutral"):
                new_label = target.get("label")

            target["needs_deeper_discussion"] = needs_discuss
            if (not needs_discuss) and change_result and new_label in ("Conflict", "Neutral"):
                if target.get("label") != new_label:
                    target["label"] = new_label
                    changed_conflict_ids.append(cid)
                    reason = (item.get("reason") or "").strip()
                    if reason:
                        target["analyst_reassessment_reason"] = reason

            if needs_discuss:
                q = (item.get("clarification_question") or "").strip()
                if not q:
                    q = f"請釐清 {cid} 涉及需求的驗收邊界與衝突判定依據。"
                req_ids = item.get("requirement_ids") or []
                if not isinstance(req_ids, list):
                    req_ids = []
                clarification_requests.append(
                    {
                        "conflict_id": cid,
                        "question": q,
                        "requirement_ids": req_ids,
                        "reason": (item.get("reason") or "").strip(),
                    }
                )

        return {
            "conflicts": updated_conflicts,
            "clarification_requests": clarification_requests,
            "changed_conflict_ids": changed_conflict_ids,
        }

    def finalize_conflicts_after_clarification(
        self,
        artifact: Dict,
        round_discussions: List[Dict],
        baseline_conflicts: Optional[List[Dict]] = None,
    ) -> Dict[str, Any]:
        """針對 requirement_clarification 討論後，最終由 Analyst 判斷是否更新原衝突結果。"""
        current_conflicts = artifact.get("conflicts", [])
        if not current_conflicts:
            return {
                "conflicts": [],
                "handled_conflict_ids": [],
                "changed_conflict_ids": [],
            }

        clarification_topics = [
            d for d in (round_discussions or [])
            if (d.get("topic", {}).get("category") == "requirement_clarification")
        ]
        if not clarification_topics:
            return {
                "conflicts": list(current_conflicts),
                "handled_conflict_ids": [],
                "changed_conflict_ids": [],
            }

        context = {
            "requirements": artifact.get("requirements", []),
            "feedback": artifact.get("feedback") or {},
            "system_models": artifact.get("system_models") or {},
            "baseline_conflicts": baseline_conflicts or current_conflicts,
            "current_conflicts": current_conflicts,
            "clarification_discussions": clarification_topics,
        }
        task = """你是 Analyst。請根據 requirement_clarification 的討論結果，對每筆涉及的 conflict 做最終判定：是否更改原本衝突分析結果。
輸出「僅一個」JSON 物件，格式：
{
  "updates": [
    {
      "conflict_id": "CF-01 或 NF-01",
      "change_conflict_result": true 或 false,
      "new_label": "Conflict 或 Neutral",
      "reason": "繁體中文，說明為何改或不改"
    }
  ]
}
規則：
- 只針對 requirement_clarification 討論涉及到的 conflict 輸出 updates。
- change_conflict_result=true 才套用 new_label；false 則維持原 label。
- 僅輸出 JSON，不要其他文字。"""

        try:
            raw = self.invoke_skill("conflict-analyzer", task, context=context)
            data = self.parse_topic_response_json(raw)
        except Exception as e:
            self.logger.warning("Analyst 會後最終衝突判定失敗: %s", e)
            return {
                "conflicts": list(current_conflicts),
                "handled_conflict_ids": [],
                "changed_conflict_ids": [],
            }

        updates = data.get("updates", [])
        if not isinstance(updates, list):
            return {
                "conflicts": list(current_conflicts),
                "handled_conflict_ids": [],
                "changed_conflict_ids": [],
            }

        out_conflicts = [dict(c) for c in current_conflicts]
        by_id = {c.get("id"): c for c in out_conflicts if c.get("id")}
        handled_conflict_ids = []
        changed_conflict_ids = []

        for upd in updates:
            if not isinstance(upd, dict):
                continue
            cid = (upd.get("conflict_id") or "").strip()
            if not cid or cid not in by_id:
                continue
            handled_conflict_ids.append(cid)
            target = by_id[cid]
            change_result = self._as_bool(upd.get("change_conflict_result"))
            reason = (upd.get("reason") or "").strip()
            if reason:
                target["analyst_final_reason"] = reason
            if not change_result:
                target["needs_deeper_discussion"] = False
                continue
            new_label = (upd.get("new_label") or "").strip()
            if new_label in ("Conflict", "Neutral") and target.get("label") != new_label:
                target["label"] = new_label
                changed_conflict_ids.append(cid)
            target["needs_deeper_discussion"] = False

        return {
            "conflicts": out_conflicts,
            "handled_conflict_ids": list(dict.fromkeys(handled_conflict_ids)),
            "changed_conflict_ids": changed_conflict_ids,
        }

    def generate_scope(self, rough_idea: str, stakeholders: List[Dict]) -> Dict:
        """依 requirements-analyst skill 產出專案範圍（description 為專案概述、依 rough_idea；in_scope / out_of_scope 依利害關係人需求）。"""
        context = {"rough_idea": rough_idea, "stakeholders": stakeholders}
        task = """依 requirements-analyst skill 產出專案範圍，規則如下：
- **in_scope** 與 **out_of_scope**：僅根據 Context 的 stakeholders（利害關係人與其需求）產出，列出範圍內項目與排除項目。
- **description**：根據 Context 的 rough_idea 撰寫專案概述（一句話或簡短段落，說明專案目的與邊界）。
輸出「僅一個」JSON 物件，鍵名 "scope"，值為 { "description": "專案概述（須源自 rough_idea）", "in_scope": ["項目"], "out_of_scope": ["排除項目"] }。
勿輸出 Markdown，只輸出該 JSON。"""
        try:
            raw = self.invoke_skill("requirements-analyst", task, context=context)
            data = self.parse_topic_response_json(raw)
        except Exception as e:
            self.logger.warning(f"requirements-analyst scope 失敗: {e}")
            return {"in_scope": [], "out_of_scope": [], "description": ""}
        scope = data.get("scope") or {}
        if not isinstance(scope, dict):
            return {"in_scope": [], "out_of_scope": [], "description": ""}
        return {
            "in_scope": scope.get("in_scope", []),
            "out_of_scope": scope.get("out_of_scope", []),
            "description": scope.get("description", ""),
        }

    def analyze_requirements(self, stakeholders: List[Dict]) -> Dict[str, Any]:
        """依 requirements-analyst skill 從利害關係人執行需求分析，產出結構化需求清單。每位 stakeholder 單獨產出再合併，以減輕單次負擔並提高條目完整度。"""
        all_requirements = []
        for idx, one_sh in enumerate(stakeholders):
            sh_label = one_sh.get("name") or one_sh.get("id") or f"利害關係人{idx + 1}"
            context = {"stakeholders": [one_sh]}
            task = f"""依 requirements-analyst skill，根據 Context 中**此單一**利害關係人產出結構化需求清單。
**重要**：請將該利害關係人提到的**每項**功能或非功能需求都拆成**獨立條目**，勿合併或遺漏；同一段敘述若含多個可驗收要點，應拆成多筆。寧可多拆、勿少列。
輸出「僅一個」JSON 物件，鍵名為 "requirements"，值為陣列。每筆須含：text、type（FR 或 NFR）、priority（must / should / could）。NFR 須含可量化指標。source_stakeholders 請填 ["{sh_label}"]（此人的識別）。
本輪僅分析此一人，id 由系統後續統一指派，此處可不填或填暫時編號。
type、priority 維持英文。勿輸出 Markdown，只輸出該 JSON。"""
            try:
                raw = self.invoke_skill("requirements-analyst", task, context=context)
                data = self.parse_topic_response_json(raw)
            except Exception as e:
                self.logger.warning(f"需求分析 skill 執行失敗（{sh_label}）: {e}")
                continue
            reqs = data.get("requirements", [])
            if not isinstance(reqs, list):
                continue
            for r in reqs:
                if not r.get("text"):
                    continue
                r.setdefault("source_stakeholders", [sh_label])
                all_requirements.append(r)

        # 統一指派 id：FR-1, FR-2, … 與 NFR-1, NFR-2, …
        fr_list = [r for r in all_requirements if (r.get("type") or "").strip().upper() == "FR"]
        nfr_list = [r for r in all_requirements if (r.get("type") or "").strip().upper() == "NFR"]
        other_list = [r for r in all_requirements if r not in fr_list and r not in nfr_list]
        for i, r in enumerate(fr_list, 1):
            r["id"] = f"FR-{i}"
        for i, r in enumerate(nfr_list, 1):
            r["id"] = f"NFR-{i}"
        for i, r in enumerate(other_list, 1):
            r.setdefault("type", "FR")
            r["id"] = f"FR-{len(fr_list) + i}"  # 接在既有 FR 之後
        merged = fr_list + nfr_list + other_list
        return {"requirements": merged}

    def create_draft(
        self,
        artifact: Dict[str, Any],
        draft_version: Optional[int] = None,
        round_num: Optional[int] = None,
        recent_decisions_limit: Optional[int] = None,
    ) -> str:
        """正規化 artifact 內的需求後，依 requirements-analyst skill 產出需求草稿 Markdown。"""
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
        dec_tbl = analyst_draft_decision_table_note(self.output_language)
        task = f"""依 requirements-analyst skill 的 **Output Format**，僅根據 Context 產出完整需求草稿 Markdown。{version_note}
- 只輸出 Markdown，勿包程式碼區塊。
- **勿產出**文件頂層 H1 標題（不要 # Feature Name）。草稿直接從 Frontmatter 或「概觀」章節開始。
- Frontmatter 僅含 status, stakeholders（勿含 version、feature、created、updated）。stakeholders 用 Context.stakeholder_names。
- 概觀只寫 Context.scope.description。
- 約束依 Context.feedback 撰寫。勿產出依賴關係、成功標準。
- Scope 章節寫 Context.scope.in_scope 與 Context.scope.out_of_scope。
- **ID 規則**：功能性需求用 **FR-1、FR-2、FR-3** … 依序；非功能性需求用 **NFR-1、NFR-2、NFR-3** … 依序。
- **非功能性需求**：與功能性需求採用**相同的扁平表格格式**（ID | Priority | Requirement | Stakeholder | Acceptance Criteria），**不要**分子類別（不要按 Security/Performance 等拆分子章節），所有 NFR 列在同一張表中。
- {dec_tbl}
- 功能性與非功能性需求的 **Requirement 欄位**：每格維持簡短（一句話或至多兩句），勿將整段決策或實作細節貼入表格；若原始需求過長，請改寫為精簡摘要。
- 若 Context.open_questions 有項目，請在草稿中另立章節 **## 開放問題**（或 **## Open questions**），條列尚未結案者（status 非 answered 或明顯待處理），每則簡述問題要點並盡量保留可追溯 id（如來源 agent、相關需求 id）；若無待處理開放問題則可省略此章節或註明「無」。"""
        try:
            raw = self.invoke_skill("requirements-analyst", task, context=context)
        except Exception as e:
            self.logger.warning("Analyst 產出 draft markdown 失敗: %s", e)
            return f"# Requirements Draft\n\n（生成失敗: {e}）"
        md = self.strip_code_fences(raw)

        models = artifact.get("system_models", {}).get("models", [])
        if models:
            sys_hdr = "## System models\n" if self.output_language == OUTPUT_LANG_EN else "## 系統模型\n"
            md += f"\n\n---\n\n{sys_hdr}"
            for m in models:
                name = m.get("name", "未命名模型")
                plantuml = (m.get("plantuml") or "").strip()
                if plantuml:
                    md += f"\n### {name}\n\n```plantuml\n{plantuml}\n```\n"

        return md

    def update_draft(self, artifact: Dict) -> Dict:
        """依 requirements-analyst skill 依決策與討論更新需求草稿。"""
        context = {
            "requirements": artifact.get("requirements", []),
            "decisions": artifact.get("decisions", []),
            "discussions": artifact.get("discussions", []),
            "conflicts": artifact.get("conflicts", []),
            "scope": artifact.get("scope", {}),
            "domain_research": artifact.get("feedback", {}).get("domain_research"),
            "system_models": artifact.get("system_models", {}),
        }
        task = """依 requirements-analyst skill，**以 Context.requirements（現有需求清單）為基礎**更新需求，勿遺漏或刪除既有版本中的條目。

規則：
1. **保留既有**：Context.requirements 中的每一筆需求原則上**原樣保留**；僅對「受本輪 decisions 或 discussions 直接影響」的條目做**調整或補充**（例如對應已解決 Conflict 的需求可與決策方向對齊）。
2. **有更新才更新**：若某條需求與本輪決策相關，可微調 text 以反映決策結論，但 text 仍須維持簡短（一至兩句話）。與本輪無關的需求**不要改動**。
3. **可新增**：若本輪討論產出 scope 內的新需求，可追加至陣列末尾；勿新增超出 scope.out_of_scope 的需求。
4. **勿遺漏**：輸出的 requirements 陣列必須涵蓋所有既有需求（相同 id 至少保留一筆），再視需要追加新項。

輸出「僅一個」JSON 物件，鍵名為 "requirements"，值為更新後的需求陣列。每筆須含 id、text、type（FR/NFR/constraint）、priority、source_stakeholders。已解決的 Conflict 對應需求須與決策方向一致。每筆 text 維持簡短，勿將整段決策貼入。id、type、priority 維持英文。勿輸出 Markdown，只輸出該 JSON。"""
        try:
            raw = self.invoke_skill("requirements-analyst", task, context=context)
            data = self.parse_topic_response_json(raw)
        except Exception as e:
            self.logger.warning(f"需求分析 skill 更新失敗: {e}")
            return {
                "requirements": artifact.get("requirements", []),
                "conflicts": artifact.get("conflicts", []),
            }
        requirements = data.get("requirements", artifact.get("requirements", []))
        if not isinstance(requirements, list):
            requirements = artifact.get("requirements", [])
        # 合併：若 LLM 遺漏既有 id，以舊版補回，避免前版需求被刪除
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
        return {
            "requirements": requirements,
            "conflicts": artifact.get("conflicts", []),
        }

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
        report_template_json = ""
        if CONFLICT_REPORT_TEMPLATE_PATH.exists():
            report_template_json = CONFLICT_REPORT_TEMPLATE_PATH.read_text(
                encoding="utf-8"
            )
        context = {
            "report_template": report_template_json,
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
        task = """依本 skill 與 Context.report_template（conflict_report_template.json）的結構，僅根據 Context 產出「需求 Conflict 分析報告」。
- Context.conflicts 為**所有 Conflict**（含已解決與未解決）。每筆有 label：**Conflict** = 未解決，**Neutral** = 已解決。報告須**全部列出**，並在每筆標示「是否已解決」（依 label）。label 維持英文。
- 其餘章節與欄位（metadata、conflict_matrix、recommendations、unresolved/resolved 總數等）依 report_template 撰寫；unresolved 為 label=Conflict 的數量，resolved 為 label=Neutral 的數量。
- **輸出為 Markdown**，勿輸出 JSON 或程式碼區塊。只輸出 Markdown。"""
        try:
            raw = self.invoke_skill("conflict-analyzer", task, context=context)
        except Exception as e:
            self.logger.warning("Analyst 產出 conflict report 失敗: %s", e)
            return f"# 需求 Conflict 分析報告\n\n（報告生成失敗: {e}）"
        out = self.strip_code_fences(raw)
        if not out:
            self.logger.warning("Analyst 產出 conflict report 無內容")
            return "# 需求 Conflict 分析報告\n\n（報告無內容）"
        return out

    def get_optional_skill_context(
        self, topic: Dict, artifact_snapshot: Optional[Dict]
    ) -> Optional[str]:
        """議題為 Conflict 協調或需求釐清時，觸發 conflict-analyzer 產出簡短要點供發言參考。"""
        if topic.get("category") not in ("conflict_resolution", "requirement_clarification"):
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
        """議題為 Conflict 協調或需求釐清時，依 conflict-analyzer 產出 resolution_options，供人類裁決使用。回傳格式同 Mediator.prepare_human_options：best_options、compromise。"""
        if topic.get("category") not in ("conflict_resolution", "requirement_clarification"):
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
        elif topic.get("category") == "requirement_clarification":
            # 釐清議題可能針對 Neutral（NF-*）誤判修正；無 source_ids 時才需全體候選。
            relevant = list(conflicts)
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
        task = """針對 Context 中的議題與對應判定項（可含 Conflict 與 Neutral），依 conflict-analyzer skill 的 resolution 結構，僅產出「解決方案選項」。
輸出「僅一個」JSON 物件，須含：
- resolution_options：陣列，每筆含 option（如 "A"/"B"）、strategy、description、pros（陣列）、cons（陣列）、recommendation（boolean）
- recommended_resolution：字串，建議採用的解決方案摘要
勿輸出 Markdown 或其它文字，只輸出該 JSON。"""
        try:
            raw = self.invoke_skill("conflict-analyzer", task, context=context)
            data = self.parse_topic_response_json(raw)
        except Exception as e:
            self.logger.warning("Analyst 產出 resolution_options 失敗: %s", e)
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
                    pl = "Pros:" if self.output_language == OUTPUT_LANG_EN else "優點："
                    parts.append(
                        pl
                        + (
                            ", ".join(o["pros"])
                            if isinstance(o["pros"], list)
                            else str(o["pros"])
                        )
                    )
                if o.get("cons"):
                    cl = "Cons:" if self.output_language == OUTPUT_LANG_EN else "缺點："
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
            if self.output_language == OUTPUT_LANG_EN:
                c_title = "Recommended (Analyst)"
                c_rat = "Resolution recommended by conflict analysis"
            else:
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

# 思考與發言流程
1. 先思考：(1) 此議題與既有需求的一致性與缺口 (2) 依需求證據你必須堅守的分析結論或驗收底線 (3) 在證據允許範圍內可接受的調整或折衷 (4) 目前資訊中「已確認事實 / 待驗證假設 / 主要風險」
2. 上述 (2)(3) 只用來**內部**整理立場；撰寫 statement 時請勿以「我可讓步的點是…」「不可讓步的點是…」或類似小標／口頭套語作答，應把堅持與彈性**自然融入**結論、依據與建議中。
3. 再根據思考結果，撰寫一段完整的發言（statement），建議採「先結論、再依據、再建議」順序，針對議題提出你的分析與可執行建議
4. 若有需要請其他角色回答的問題，列入 open_questions（to 填寫目標 agent 名稱，如 "user"、"expert"、"modeler"）

# 表達方式（僅能以文字呈現）
- 發言時可善用**文字形式**的圖、表格、流程、草圖輔助說明，例如：Markdown 表格（| 項目 | 說明 |）、編號步驟流程（1. … 2. …）、箭頭式流程（A → B → C）、簡要結構縮排或文字草圖；無法產出真實圖片，僅能以文字表達。**若有使用表格、流程或圖示，請用 ``` … ``` 程式碼區塊包住，與一般敘述分開，方便閱讀。**

# 發言風格
- 以真實需求工程會議中的需求分析師口吻發言：務實、可追蹤、以需求與證據為核心，避免空泛表態
- 先說你支持或反對的結論，再用需求 id、Conflict id、會議內容作為依據，最後給出可落地的下一步
- 可說「從 R-01 與 R-02 的關係來看…」「目前 Conflict CF-01 若採方案 A…」等

# 約束
- 保持中立，不偏袒任何利害關係人
- statement 必須是完整、有條理的發言，論點須有具體需求依據
- 若資訊不足，需明確指出缺口與需補件項目，不可假設已確認
- 避免直接給出實作細節（程式碼/框架），聚焦需求定義、驗收邊界、風險與取捨
- 投票將在討論結束後另行進行，發言時只需專注分析與建議

輸出 JSON:
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

    # ===== 子 OODA 循環 =====

    def run_review_loop(self, artifact, recent_discussions=None, *, max_iterations):
        """Analyst 子 OODA：掃描討論 → 偵測 Conflict → 更新需求。max_iterations 為此次上限（caller 傳入，通常為 5）；第一輪可選填 max_iterations（1–5）由 Analyst 自訂此次實際輪數。"""
        observation = None
        actions_taken = []
        pending_issues = []
        scan_results = None
        effective_max = min(max_iterations, 5)
        i = 0

        while i < effective_max:
            state = self.build_review_state(
                artifact, recent_discussions, actions_taken,
                scan_results, i, effective_max,
            )
            decision = self.decide_next_review_action(state, observation)
            if i == 0:
                n = decision.get("max_iterations")
                if n is not None and isinstance(n, int) and 1 <= n <= 5:
                    effective_max = n
                    self.logger.info(f"  Analyst 自訂此次複審輪數: {effective_max}（1–5）")
            action = decision.get("action", "done")
            self.logger.info(
                f"  Analyst review [{i + 1}/{effective_max}]: {action}"
                f" — {decision.get('reasoning', '')}"
            )
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

    def decide_next_review_action(self, state, last_observation=None):
        state_text = json.dumps(state, ensure_ascii=False, indent=2)
        obs_text = json.dumps(last_observation or {}, ensure_ascii=False, indent=2)

        user_prompt = f"""# 任務
你是需求分析師，正在對當前專案進行自主分析。根據「當前狀態」與「上一步結果」，決定下一步行動。

# 可用動作
- scan_discussions：掃描近期討論內容，提取關鍵變更與潛在 Conflict。無參數。
- detect_conflicts：對當前需求執行 Conflict 偵測。無參數。
- update_requirements：根據近期討論與決策更新需求清單。無參數。
- flag_issue：標記一個需要主持人關注的問題。params: {{ "description": "問題描述" }}
- done：分析完成，交還控制權。無參數。

# 當前狀態
{state_text}

# 上一步結果
{obs_text}

# 決策指引
- 若為第一輪（當前狀態中 iteration 為 1），可選填 max_iterations（1–5）表示此次複審你打算跑幾輪；不填則用目前上限（最多 5）。
- 若有近期討論且尚未掃描，先 scan_discussions
- 若掃描後發現潛在新 Conflict，呼叫 detect_conflicts
- 若有已解決 Conflict 或決策影響需求，呼叫 update_requirements
- 若有無法自行釐清的模糊需求（需利害關係人確認），以 flag_issue 標記供會議討論
- 無需進一步分析時呼叫 done
- {short_reasoning_line(self.output_language)}

輸出 JSON:
{{
    "action": "動作名稱",
    "params": {{}},
    "reasoning": "一句說明",
    "max_iterations": "選填，僅第一輪有效；填數字 1–5 表示此次複審自訂輪數"
}}"""

        messages = self.build_direct_messages(user_prompt)
        try:
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
                draft = self.update_draft(artifact)
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
