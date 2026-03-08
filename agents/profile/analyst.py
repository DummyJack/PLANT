import json
import re
from pathlib import Path
from typing import Dict, List, Optional, Any
from agents.base import BaseAgent

CONFLICT_PATTERNS_PATH = (
    Path(__file__).resolve().parent.parent
    / "skills"
    / "conflict-analyzer"
    / "references"
    / "conflict_patterns.md"
)
CONFLICT_REPORT_TEMPLATE_PATH = (
    Path(__file__).resolve().parent.parent
    / "skills"
    / "conflict-analyzer"
    / "assets"
    / "conflict_report_template.json"
)


def parse_conflict_types_from_patterns(path: Path) -> tuple:
    """從 conflict_patterns.md 的 ## X Conflicts 標題解析出類型 id 順序。"""
    text = path.read_text(encoding="utf-8")
    ids = []
    for m in re.finditer(r"^## (\w+) Conflicts", text, re.MULTILINE):
        if m.group(1) != "Table":
            ids.append(m.group(1))
    return (
        tuple(ids)
        if ids
        else (
            "Logical",
            "Technical",
            "Resource",
            "Temporal",
            "Data",
            "State",
            "Priority",
            "Scope",
        )
    )


ALLOWED_CONFLICT_TYPES = parse_conflict_types_from_patterns(CONFLICT_PATTERNS_PATH)


class AnalystAgent(BaseAgent):
    """需求分析師：賦予 conflict-analyzer、requirements-analyst skill，負責衝突辨識與需求草稿。"""

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
        """依 conflict-analyzer skill 執行衝突辨識；輸出須為 label: Conflict 或 Neutral，回傳更新後的 artifact。"""
        stakeholders = artifact.get("stakeholders", [])
        requirements = artifact.get("requirements", [])
        system_models = artifact.get("system_models") or {}
        context = {
            "stakeholders": stakeholders,
            "requirements": requirements,
            "system_models": system_models,
        }
        task = """依 conflict-analyzer skill 的衝突類型與辨識方式，分析 Context 中的利害關係人、需求與系統模型，辨識所有衝突。
輸出「僅一個」JSON 物件，鍵名為 "conflicts"，值為陣列。每筆須包含：
- label：只能是 "Conflict" 或 "Neutral"（無衝突時用 Neutral）— 此欄位維持英文
- 若 label 為 Conflict：須有 description；並依類型填 stakeholder_names（利害關係人衝突）或 requirement_ids / related_requirements（需求或設計衝突）；conflict_type 須為本 skill 的 8 種類型之一：Logical、Technical、Resource、Temporal、Data、State、Priority、Scope（維持英文）
- 若 label 為 Neutral：可簡述原因，不需 conflict_type
- description、stakeholder_names 等所有說明與描述文字請使用繁體中文
勿輸出 Markdown 或其它文字，只輸出該 JSON。"""

        try:
            raw = self.invoke_skill("conflict-analyzer", task, context=context)
            data = self.parse_topic_response_json(raw)
        except Exception as e:
            self.logger.warning(f"衝突分析 skill 執行失敗: {e}")
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
                conflicts.append(
                    {
                        "id": f"NF-{neutral_count:02d}",
                        "label": "Neutral",
                        "description": c.get("description", ""),
                    }
                )
                continue
            if label != "Conflict":
                continue
            ctype = (c.get("conflict_type") or "").strip()
            if ctype not in ALLOWED_CONFLICT_TYPES:
                ctype = ""
            rel_reqs = c.get("requirement_ids") or c.get("related_requirements") or []
            if c.get("stakeholder_names"):
                cf_id = f"CF-{len([x for x in conflicts if x.get('label') == 'Conflict']) + 1:02d}"
                conflicts.append(
                    {
                        "id": cf_id,
                        "label": "Conflict",
                        "description": c.get("description", ""),
                        "stakeholder_names": c.get("stakeholder_names", []),
                        "conflict_type": ctype,
                    }
                )
            elif rel_reqs or c.get("requirement_ids"):
                cf_id = f"CF-{len([x for x in conflicts if x.get('label') == 'Conflict']) + 1:02d}"
                conflicts.append(
                    {
                        "id": cf_id,
                        "label": "Conflict",
                        "description": c.get("description", ""),
                        "requirement_ids": rel_reqs or c.get("requirement_ids", []),
                        "conflict_type": ctype,
                    }
                )
            else:
                design_count += 1
                cf_id = f"CF-D{design_count:02d}"
                conflicts.append(
                    {
                        "id": cf_id,
                        "label": "Conflict",
                        "description": c.get("description", ""),
                        "requirement_ids": rel_reqs,
                    }
                )

        if conflicts:
            n_conflict = len([x for x in conflicts if x.get("label") == "Conflict"])
            n_neutral = len([x for x in conflicts if x.get("label") == "Neutral"])
            self.logger.info(
                f"辨識出 {len(conflicts)} 筆（Conflict: {n_conflict}，Neutral: {n_neutral}）"
            )
        return {**artifact, "conflicts": conflicts}

    def generate_scope(self, rough_idea: str, stakeholders: List[Dict]) -> Dict:
        """依 requirements-analyst skill 產出專案範圍（description 為專案概述、依 rough_idea；in_scope / out_of_scope 依利害關係人需求）。"""
        context = {"rough_idea": rough_idea, "stakeholders": stakeholders}
        task = """依 requirements-analyst skill 產出專案範圍，規則如下：
- **in_scope** 與 **out_of_scope**：僅根據 Context 的 stakeholders（利害關係人與其需求）產出，列出範圍內項目與排除項目。
- **description**：根據 Context 的 rough_idea 撰寫專案概述（一句話或簡短段落，說明專案目的與邊界）。
- description、in_scope、out_of_scope 的項目與說明文字請使用繁體中文。
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
        """依 requirements-analyst skill 從利害關係人執行需求分析，產出結構化需求清單（尚未正規化為草稿）。"""
        context = {"stakeholders": stakeholders}
        task = """依 requirements-analyst skill，根據 Context 的利害關係人產出結構化需求清單。
輸出「僅一個」JSON 物件，鍵名為 "requirements"，值為陣列。每筆須含：id（如 R-01）、text、type（FR 或 NFR）、priority（must / should / could）、source_stakeholders。NFR 須含可量化指標。
requirements 陣列中的 text 及所有描述性內容請使用繁體中文。id、type、priority 維持英文。勿輸出 Markdown，只輸出該 JSON。"""
        try:
            raw = self.invoke_skill("requirements-analyst", task, context=context)
            data = self.parse_topic_response_json(raw)
        except Exception as e:
            self.logger.warning(f"需求分析 skill 執行失敗: {e}")
            return {"requirements": []}
        requirements = data.get("requirements", [])
        if not isinstance(requirements, list):
            return {"requirements": []}
        return {"requirements": requirements}

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
        task = f"""依 requirements-analyst skill 的 **Output Format**，僅根據 Context 產出完整需求草稿 Markdown。{version_note}
- 草稿全文使用繁體中文，只輸出 Markdown，勿包程式碼區塊。
- **勿產出**文件頂層 H1 標題（不要 # Feature Name）。草稿直接從 Frontmatter 或「概觀」章節開始。
- Frontmatter 僅含 version, status, stakeholders（勿含 feature、created、updated）。version 填 Context.draft_version（初始草稿為 0）；stakeholders 用 Context.stakeholder_names。
- 概觀只寫 Context.scope.description。
- 約束依 Context.feedback 撰寫。勿產出依賴關係、成功標準。
- Scope 章節寫 Context.scope.in_scope 與 Context.scope.out_of_scope。
- **ID 規則**：功能性需求用 **FR-1、FR-2、FR-3** … 依序；非功能性用 **NFR-類別-1**（類別：SEC、PERF、ACC、REL、AVL、MNT、PRT、USB），例如 NFR-SEC-1、NFR-PERF-1。
- **非功能性需求**：常見類別**全部寫上**（安全性、性能、可及性、可靠性、可用性、可維護性、可攜性、易用性），有對應需求則填表，無則該小節可留空表或簡短註明「（本專案暫無）」。
- 衝突需求表格三欄：Issue | Requirements Affected（受影響需求）| Decision（決策）。Requirements Affected 欄位請寫詳細：列出受影響的需求 ID，並對每個 ID 附一句簡短摘要（該需求內容要點）；Decision 欄位標題與內容可使用繁體中文（如「待決」「已決：…」）。不要 Resolution Options。草稿結束於「衝突需求」。
- 功能性與非功能性需求的 **Requirement 欄位**：每格維持簡短（一句話或至多兩句），勿將整段決策或實作細節貼入表格；若原始需求過長，請改寫為精簡摘要。"""
        try:
            raw = self.invoke_skill("requirements-analyst", task, context=context)
        except Exception as e:
            self.logger.warning("Analyst 產出 draft markdown 失敗: %s", e)
            return f"# Requirements Draft\n\n（生成失敗: {e}）"
        return self.strip_code_fences(raw)

    def update_draft(self, artifact: Dict) -> Dict:
        """依 requirements-analyst skill 依決策與討論更新需求草稿。"""
        context = {
            "requirements": artifact.get("requirements", []),
            "decisions": artifact.get("decisions", []),
            "discussions": artifact.get("discussions", []),
            "conflicts": artifact.get("conflicts", []),
            "scope": artifact.get("scope", {}),
            "domain_research": artifact.get("feedback", {}).get("domain_research"),
        }
        task = """依 requirements-analyst skill，**以 Context.requirements（現有需求清單）為基礎**更新需求，勿遺漏或刪除既有版本中的條目。

規則：
1. **保留既有**：Context.requirements 中的每一筆需求原則上**原樣保留**；僅對「受本輪 decisions 或 discussions 直接影響」的條目做**調整或補充**（例如對應已解決衝突的需求可與決策方向對齊）。
2. **有更新才更新**：若某條需求與本輪決策相關，可微調 text 以反映決策結論，但 text 仍須維持簡短（一至兩句話）。與本輪無關的需求**不要改動**。
3. **可新增**：若本輪討論產出 scope 內的新需求，可追加至陣列末尾；勿新增超出 scope.out_of_scope 的需求。
4. **勿遺漏**：輸出的 requirements 陣列必須涵蓋所有既有需求（相同 id 至少保留一筆），再視需要追加新項。

輸出「僅一個」JSON 物件，鍵名為 "requirements"，值為更新後的需求陣列。每筆須含 id、text、type（FR/NFR/constraint）、priority、source_stakeholders。已解決的衝突對應需求須與決策方向一致。每筆 text 維持簡短，勿將整段決策貼入。requirements 陣列中的 text 及描述請使用繁體中文。id、type、priority 維持英文。勿輸出 Markdown，只輸出該 JSON。"""
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
        """依 conflict-analyzer skill 與 assets/conflict_report_template.json 結構，從 artifact 產出需求衝突分析報告（Markdown）；含所有衝突（含已解決）並標示是否已解決。"""
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
        task = """依本 skill 與 Context.report_template（conflict_report_template.json）的結構，僅根據 Context 產出「需求衝突分析報告」。
- Context.conflicts 為**所有衝突**（含已解決與未解決）。每筆有 label：**Conflict** = 未解決，**Neutral** = 已解決。報告須**全部列出**，並在每筆標示「是否已解決」（依 label）。label 維持英文。
- 其餘章節與欄位（metadata、conflict_matrix、recommendations、unresolved/resolved 總數等）依 report_template 撰寫；unresolved 為 label=Conflict 的數量，resolved 為 label=Neutral 的數量。
- 報告內所有章節標題、描述、建議、說明等文字請使用**繁體中文**。
- **輸出為 Markdown**，勿輸出 JSON 或程式碼區塊。只輸出 Markdown。"""
        try:
            raw = self.invoke_skill("conflict-analyzer", task, context=context)
        except Exception as e:
            self.logger.warning("Analyst 產出 conflict report 失敗: %s", e)
            return f"# 需求衝突分析報告\n\n（報告生成失敗: {e}）"
        out = self.strip_code_fences(raw)
        if not out:
            self.logger.warning("Analyst 產出 conflict report 無內容")
            return "# 需求衝突分析報告\n\n（報告無內容）"
        return out

    def get_optional_skill_context(
        self, topic: Dict, artifact_snapshot: Optional[Dict]
    ) -> Optional[str]:
        """議題為衝突討論時，觸發 conflict-analyzer 產出簡短要點供發言參考。"""
        if topic.get("category") != "conflict_resolution":
            return None
        if "conflict-analyzer" not in self.skill_names:
            return None
        context = {"topic": topic, "artifact_snapshot": artifact_snapshot or {}}
        task = """針對 Context 中的議題與專案狀態，簡要列出 1～3 點衝突分析要點（可含類型、涉及需求 id、建議方向），供會議發言參考。請使用繁體中文。只輸出簡短條列文字，勿 JSON。"""
        try:
            raw = self.invoke_skill("conflict-analyzer", task, context=context)
            return (raw or "").strip()[:1500]
        except Exception as e:
            self.logger.debug("議程中觸發 conflict-analyzer 失敗: %s", e)
            return None

    def get_resolution_options_for_topic(
        self, topic: Dict, artifact: Dict[str, Any]
    ) -> Optional[Dict]:
        """議題為衝突討論時，依 conflict-analyzer 產出 resolution_options，供人類裁決使用。回傳格式同 Mediator.prepare_human_options：best_options、compromise。"""
        if topic.get("category") != "conflict_resolution":
            return None
        if "conflict-analyzer" not in self.skill_names:
            return None
        source_ids = topic.get("source_ids") or []
        conflict_ids = [
            s
            for s in source_ids
            if isinstance(s, str) and (s.startswith("CF-") or s.startswith("CF-D"))
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
        task = """針對 Context 中的議題與對應衝突，依 conflict-analyzer skill 的 resolution 結構，僅產出「解決方案選項」。
輸出「僅一個」JSON 物件，須含：
- resolution_options：陣列，每筆含 option（如 "A"/"B"）、strategy、description、pros（陣列）、cons（陣列）、recommendation（boolean）
- recommended_resolution：字串，建議採用的解決方案摘要
- strategy、description、pros、cons、recommended_resolution 等所有文字內容請使用繁體中文
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
                    parts.append(
                        "優點："
                        + (
                            ", ".join(o["pros"])
                            if isinstance(o["pros"], list)
                            else str(o["pros"])
                        )
                    )
                if o.get("cons"):
                    parts.append(
                        "缺點："
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
            compromise = {
                "id": 4,
                "title": "建議方案（Analyst）",
                "description": recommended,
                "rationale": "依 conflict-analyzer 建議採用的解決方案",
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
1. 先思考：(1) 此議題與既有需求的一致性與缺口 (2) 不可讓步的要點（須有需求依據）(3) 可接受調整或折衷的要點
2. 再根據思考結果，撰寫一段完整的發言（statement），針對議題提出你的分析與建議
3. 若有需要請其他角色回答的問題，列入 open_questions（to 填寫目標 agent 名稱，如 "user"、"expert"、"modeler"）

# 發言風格
- 以分析師在會議中的口吻：簡潔、有依據，引用需求 id 或衝突時具體說明，不空泛
- 可說「從 R-01 與 R-02 的關係來看…」「目前衝突 CF-01 若採方案 A…」等

# 約束
- 保持中立，不偏袒任何利害關係人
- statement 必須是完整、有條理的發言，論點須有具體需求依據
- 依你的立場投票（vote）：agreed 表示可達成共識；unresolved 表示仍有衝突需升級
- statement、open_questions 的 question 請使用繁體中文

輸出 JSON:
{{{{
    "statement": "針對此議題的完整發言內容",
    "vote": "agreed 或 unresolved",
    "open_questions": [{{{{"to": "目標 agent 名稱", "question": "問題"}}}}]
}}}}"""

        messages = self.build_direct_messages(user_prompt)
        response = self.chat_for_topic_response(messages)

        return {
            "agent": self.name,
            "statement": response.get("statement", ""),
            "vote": response.get("vote", "unresolved"),
            "open_questions": response.get("open_questions", []),
        }

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
