import json
import re
from pathlib import Path
from typing import Dict, List, Optional, Any
from agents.base import BaseAgent

_CONFLICT_PATTERNS_PATH = (
    Path(__file__).resolve().parent.parent
    / "skills"
    / "conflict-analyzer"
    / "references"
    / "conflict_patterns.md"
)


def _parse_conflict_types_from_patterns(path: Path) -> tuple:
    """從 conflict_patterns.md 的 ## X Conflicts 標題解析出類型 id 順序。"""
    if not path.exists():
        return ("Logical", "Technical", "Resource", "Temporal", "Data", "State", "Priority", "Scope")
    text = path.read_text(encoding="utf-8")
    ids = []
    for m in re.finditer(r"^## (\w+) Conflicts", text, re.MULTILINE):
        if m.group(1) != "Table":
            ids.append(m.group(1))
    return tuple(ids) if ids else ("Logical", "Technical", "Resource", "Temporal", "Data", "State", "Priority", "Scope")


ALLOWED_CONFLICT_TYPES = _parse_conflict_types_from_patterns(_CONFLICT_PATTERNS_PATH)
CONFLICT_TYPE_LABELS = {
    "Logical": "邏輯衝突",
    "Technical": "技術衝突",
    "Resource": "資源衝突",
    "Temporal": "時序衝突",
    "Data": "資料衝突",
    "State": "狀態衝突",
    "Priority": "優先序衝突",
    "Scope": "範圍衝突",
}


class AnalystAgent(BaseAgent):
    """需求分析師：賦予 conflict-analyzer、requirements-analyst skill，負責衝突辨識與需求草稿。"""

    name = "analyst"

    system_prompt = """你是一個專業的需求分析師，在需求討論流程中負責產出與維護需求產物，並辨識衝突。
# 職責與產出
1. **範圍**：依 rough_idea 與 stakeholders 產出 scope（description、in_scope、out_of_scope）。
2. **衝突辨識**：依 artifact 狀態執行衝突分析，只保留 label 為 Conflict 的項目並賦予 id（CF-01…、CF-D01…）。
3. **需求草稿**：建立初版需求清單（create_draft）、依 decisions/discussions 更新需求清單（update_draft）。
4. **會議發言**：參與議題討論時以分析師身份發言，引用需求 id 或衝突 id，保持中立，依立場輸出 vote（agreed/unresolved）與 open_questions。

# 約束
- 只根據既有資料與 skill 產出，不捏造需求或衝突。
- 衝突 label 僅使用 Conflict 與 Neutral；術語與格式依各 skill 的說明與 task 指示。
- 在討論中不代其他角色發言，論點須有需求或衝突依據。"""

    def __init__(self, model, tools: Optional[list] = None, registry=None):
        super().__init__(
            model,
            tools=tools,
            registry=registry,
            skill_names=["conflict-analyzer", "requirements-analyst"],
        )

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
- label：只能是 "Conflict" 或 "Neutral"（無衝突時用 Neutral）
- 若 label 為 Conflict：須有 description；並依類型填 stakeholder_names（利害關係人衝突）或 requirement_ids / related_requirements（需求或設計衝突）；conflict_type 須為本 skill 的 8 種類型之一：Logical、Technical、Resource、Temporal、Data、State、Priority、Scope
- 若 label 為 Neutral：可簡述原因，不需 conflict_type
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
        for c in raw_list:
            label = (c.get("label") or "").strip()
            if label != "Conflict":
                continue
            ctype = (c.get("conflict_type") or "").strip()
            if ctype not in ALLOWED_CONFLICT_TYPES:
                ctype = ALLOWED_CONFLICT_TYPES[0]
            rel_reqs = c.get("requirement_ids") or c.get("related_requirements") or []
            if c.get("stakeholder_names"):
                cf_id = f"CF-{len(conflicts) + 1:02d}"
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
                cf_id = f"CF-{len(conflicts) + 1:02d}"
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
            self.logger.info(
                f"辨識出 {len(conflicts)} 個衝突（label: Conflict / Neutral）"
            )
        return {**artifact, "conflicts": conflicts}

    def generate_scope(self, rough_idea: str, stakeholders: List[Dict]) -> Dict:
        """依 requirements-analyst skill 產出專案範圍（description / in_scope / out_of_scope）。"""
        context = {"rough_idea": rough_idea, "stakeholders": stakeholders}
        task = """依 requirements-analyst skill，根據 Context 的 rough_idea 與 stakeholders 產出專案範圍。
輸出「僅一個」JSON 物件，鍵名 "scope"，值為 { "description": "一句話描述範圍與邊界", "in_scope": ["項目"], "out_of_scope": ["排除項目"] }。
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

    def create_draft(self, stakeholders: List[Dict]) -> Dict:
        """依 requirements-analyst skill 從利害關係人產出需求草稿。"""
        context = {"stakeholders": stakeholders}
        task = """依 requirements-analyst skill，根據 Context 的利害關係人產出結構化需求清單。
輸出「僅一個」JSON 物件，鍵名為 "requirements"，值為陣列。每筆須含：id（如 R-01）、text、type（FR 或 NFR）、priority（must / should / could）、source_stakeholders。NFR 須含可量化指標。勿輸出 Markdown，只輸出該 JSON。"""
        try:
            raw = self.invoke_skill("requirements-analyst", task, context=context)
            data = self.parse_topic_response_json(raw)
        except Exception as e:
            self.logger.warning(f"需求分析 skill 執行失敗: {e}")
            return {"requirements": [], "conflicts": []}
        requirements = data.get("requirements", [])
        if not isinstance(requirements, list):
            return {"requirements": [], "conflicts": []}
        for req in requirements:
            req.setdefault("type", "FR")
            req.setdefault("source_stakeholders", [])
            if req.get("priority") not in ("must", "should", "could"):
                req["priority"] = "should"
        return {"requirements": requirements, "conflicts": []}

    def update_draft(self, artifact: Dict) -> Dict:
        """依 requirements-analyst skill 依決策與討論更新需求草稿。"""
        context = {
            "requirements": artifact.get("requirements", []),
            "decisions": artifact.get("decisions", []),
            "discussions": artifact.get("discussions", []),
            "conflicts": artifact.get("conflicts", []),
            "scope": artifact.get("scope", {}),
        }
        task = """依 requirements-analyst skill，根據 Context 的 decisions 與 discussions 更新 requirements；更新時須符合 scope（範圍邊界），勿新增超出 out_of_scope 的需求。
輸出「僅一個」JSON 物件，鍵名為 "requirements"，值為更新後的需求陣列。每筆須含 id、text、type（FR/NFR/constraint）、priority、source_stakeholders。已解決的衝突對應需求須反映決策。勿輸出 Markdown，只輸出該 JSON。"""
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
        for req in requirements:
            if req.get("priority") not in ("must", "should", "could"):
                req["priority"] = "should"
        return {
            "requirements": requirements,
            "conflicts": artifact.get("conflicts", []),
        }

    def get_optional_skill_context(
        self, topic: Dict, artifact_snapshot: Optional[Dict]
    ) -> Optional[str]:
        """議題為衝突討論時，觸發 conflict-analyzer 產出簡短要點供發言參考。"""
        if topic.get("category") != "conflict_resolution":
            return None
        if "conflict-analyzer" not in self.skill_names:
            return None
        context = {"topic": topic, "artifact_snapshot": artifact_snapshot or {}}
        task = """針對 Context 中的議題與專案狀態，簡要列出 1～3 點衝突分析要點（可含類型、涉及需求 id、建議方向），供會議發言參考。只輸出簡短條列文字，勿 JSON。"""
        try:
            raw = self.invoke_skill("conflict-analyzer", task, context=context)
            return (raw or "").strip()[:1500]
        except Exception as e:
            self.logger.debug("議程中觸發 conflict-analyzer 失敗: %s", e)
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
            tool_hint = "\n# 工具使用\n- 最後**必須**輸出下列 JSON。"

        user_prompt = f"""你正在以系統分析師的身份參與需求討論。

{topic_text}
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

    def generate_draft_markdown(
        self,
        artifact: Dict[str, Any],
        draft_version: Optional[int] = None,
        round_num: Optional[int] = None,
        recent_decisions_limit: Optional[int] = None,
    ) -> str:
        """依 requirements-analyst skill 的 Output Format，從 artifact 產出需求草稿 Markdown。"""
        n = 10 if recent_decisions_limit is None else max(0, recent_decisions_limit)
        decisions = artifact.get("decisions", [])[-n:] if n else []
        context = {
            "scope": artifact.get("scope", {}),
            "rough_idea": artifact.get("rough_idea", ""),
            "stakeholders": artifact.get("stakeholders", []),
            "requirements": artifact.get("requirements", []),
            "conflicts": artifact.get("conflicts", []),
            "open_questions": artifact.get("open_questions", []),
            "decisions": decisions,
            "system_models": artifact.get("system_models", {}),
        }
        version_note = ""
        if draft_version is not None:
            version_note = f" 本稿版本: draft_v{draft_version}。"
        if round_num is not None:
            version_note += f" 對應輪次: Round {round_num}。"
        task = f"""依 requirements-analyst skill 的 **Output Format**，僅根據 Context 產出完整需求草稿 Markdown。{version_note}
只輸出 Markdown，勿包程式碼區塊。"""
        try:
            raw = self.invoke_skill("requirements-analyst", task, context=context)
        except Exception as e:
            self.logger.warning("Analyst 產出 draft markdown 失敗: %s", e)
            return f"# Requirements Draft\n\n（生成失敗: {e}）"
        return self._strip_code_fences(raw)

    @staticmethod
    def _strip_code_fences(text: str) -> str:
        s = (text or "").strip()
        if s.startswith("```"):
            idx = s.find("\n")
            if idx != -1:
                s = s[idx + 1:]
        if s.endswith("```"):
            s = s[:-3]
        return s.strip()

    def generate_conflict_report(
        self,
        artifact: Dict[str, Any],
        round_num: Optional[int] = None,
        recent_decisions_limit: Optional[int] = None,
    ) -> str:
        """依 conflict-analyzer skill 與 assets/conflict_report_format.md，從 artifact 產出需求衝突分析報告（Markdown）。"""
        n = 10 if recent_decisions_limit is None else max(0, recent_decisions_limit)
        decisions = artifact.get("decisions", [])[-n:] if n else []
        active = [c for c in artifact.get("conflicts", []) if c.get("label") == "Conflict"]
        context = {
            "conflicts": active,
            "requirements": artifact.get("requirements", []),
            "stakeholders": artifact.get("stakeholders", []),
            "scope": artifact.get("scope", {}),
            "rough_idea": artifact.get("rough_idea", ""),
            "open_questions": artifact.get("open_questions", []),
            "decisions": decisions,
            "system_models": artifact.get("system_models", {}),
            "round_num": round_num,
        }
        task = """依本 skill 與 conflict_report_format.md 的 Report Structure，僅根據 Context 產出「需求衝突分析報告」Markdown。只輸出 Markdown，勿包程式碼區塊。"""
        try:
            raw = self.invoke_skill("conflict-analyzer", task, context=context)
        except Exception as e:
            self.logger.warning("Analyst 產出 conflict report 失敗: %s", e)
            return self._empty_conflict_report_md(artifact)
        return self._strip_code_fences(raw) or self._empty_conflict_report_md(artifact)

    @staticmethod
    def _empty_conflict_report_md(artifact: Dict[str, Any]) -> str:
        reqs = artifact.get("requirements", [])
        active = [c for c in artifact.get("conflicts", []) if c.get("label") == "Conflict"]
        proj = (artifact.get("scope") or {}).get("description", "")[:50] or "Project"
        return (
            "# Requirement Conflict Analysis Report\n\n## Executive Summary\n"
            f"- **Project:** {proj}\n- **Conflicts Found:** {len(active)}\n"
            f"- **Requirements Analyzed:** {len(reqs)}\n\n*（報告生成失敗或無內容）*"
        )
