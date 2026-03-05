import json
from pathlib import Path
from typing import Dict, List, Optional
from agents.base import BaseAgent
from agents.tools import ArtifactQueryTool

_TYPE_DIR = Path(__file__).resolve().parent.parent / "type"
with open(_TYPE_DIR / "conflict_types.json", "r", encoding="utf-8") as _f:
    _CONFLICT_TYPES = tuple(json.load(_f))
CONFLICT_TYPE_IDS = [t["id"] for t in _CONFLICT_TYPES]
CONFLICT_TYPE_LABELS = {t["id"]: t["label_zh"] for t in _CONFLICT_TYPES}


def format_conflict_types_for_prompt() -> str:
    """供 LLM prompt 使用的衝突類型條列（含 id 與說明）"""
    return "\n".join(f"- {t['id']}: {t['label_zh']} — {t['description']}" for t in _CONFLICT_TYPES)


class AnalystAgent(BaseAgent):
    """需求轉換、分類、利害關係人衝突辨識、草稿版本管理。"""

    name = "analyst"

    system_prompt = """你是需求分析師。

核心職責：
1. 需求轉換 — 將口語化利害關係人需求轉換為正式需求描述
2. 需求分類 — 區分功能性（FR）與非功能性需求（NFR）
3. 衝突辨識 — 全專案衝突由分析師統一辨識：利害關係人衝突、需求/約束間衝突、設計與可測試性衝突"""

    def __init__(self, model, tools: Optional[list] = None, registry=None):
        agent_tools = list(tools or [])
        agent_tools.append(ArtifactQueryTool(lambda: getattr(self, "_current_artifact", None) or {}))
        super().__init__(model, tools=agent_tools, registry=registry)
        self._current_artifact: Optional[Dict] = None

    def set_artifact(self, artifact: Dict) -> None:
        """由執行層在每輪討論前設定，供 query_artifact 工具讀取當前專案狀態。"""
        self._current_artifact = artifact
    
    def detect_stakeholder_conflicts(self, stakeholders: List[Dict]) -> List[Dict]:
        """辨識利害關係人需求衝突：一次檢視全部；若發言或角色超過兩個，同時檢視兩兩之間的可能衝突。"""
        if len(stakeholders) < 2:
            return []
        return self.detect_stakeholder_conflicts_all(stakeholders)

    def detect_stakeholder_conflicts_all(self, stakeholders: List[Dict]) -> List[Dict]:
        """一次檢視所有利害關係人發言，辨識整體性或多方衝突；若發言或角色超過兩個，同時檢視兩兩之間的可能衝突。"""
        parts = []
        total_speeches = 0
        for s in stakeholders:
            raw = s.get("text", "")
            texts = raw if isinstance(raw, list) else [raw] if raw else []
            total_speeches += len(texts)
            segs = "\n".join(f"  {i+1}. {t}" for i, t in enumerate(texts))
            parts.append(f"【{s.get('name', '')}】的發言：\n{segs}")
        speeches_text = "\n\n".join(parts)
        pairwise_hint = ""
        if len(stakeholders) > 2 or total_speeches > 2:
            pairwise_hint = "\n- 因發言或角色超過兩個，請同時檢視兩兩之間的可能衝突；每筆衝突的 stakeholder_names 填涉及的兩人。"

        user_prompt = f"""# 任務
辨識以下利害關係人發言之間是否存在衝突（一次檢視全部）。

# 利害關係人發言
{speeches_text}

# 衝突類型定義（conflict_type 必須為以下 id 之一）
{format_conflict_types_for_prompt()}

# 判斷標準
- 有衝突時 label 填 Conflict，並填寫對應的 conflict_type、description、stakeholder_names（涉及的利害關係人，每筆通常為兩人）。
{pairwise_hint}
- 若沒有衝突，label 填 Neutral（Neutral 不需填 conflict_type）

# 輸出 JSON
{{{{
    "conflicts": [
        {{{{
            "label": "Conflict 或 Neutral",
            "conflict_type": "類型 id（僅當 label 為 Conflict 時必填）",
            "description": "衝突描述（若 Neutral 則簡述原因）",
            "stakeholder_names": ["涉及的利害關係人"]
        }}}}
    ]
}}}}"""

        messages = self.build_direct_messages(user_prompt)
        response = self.model.chat_json(messages)
        return response.get("conflicts", [])

    def run_conflict_detection(self, artifact: Dict) -> Dict:
        """由 Analyst 主動依 artifact 狀態決定並執行衝突辨識，回傳更新後的 artifact。流程不安排細步，只呼叫此入口。"""
        stakeholders = artifact.get("stakeholders", [])
        requirements = artifact.get("requirements", [])
        conflicts = list(artifact.get("conflicts", []))
        system_models = artifact.get("system_models") or {}

        has_stakeholder_cf = any(c.get("stakeholder_names") for c in conflicts)
        if stakeholders and not has_stakeholder_cf:
            raw = self.detect_stakeholder_conflicts(stakeholders)
            conflicts = []
            for c in raw:
                if c.get("label") != "Conflict":
                    continue
                names = c.get("stakeholder_names", [])
                cf_id = f"CF-{len(conflicts) + 1:02d}"
                item = {
                    "id": cf_id,
                    "label": "Conflict",
                    "description": c.get("description", ""),
                    "stakeholder_names": names,
                }
                ctype = c.get("conflict_type", "")
                if ctype and ctype in CONFLICT_TYPE_IDS:
                    item["conflict_type"] = ctype
                else:
                    item["conflict_type"] = CONFLICT_TYPE_IDS[0]
                conflicts.append(item)
            self.logger.info(f"辨識出 {len(conflicts)} 個利害關係人衝突")

        has_constraint = any((r.get("type") or "") == "constraint" for r in requirements)
        if requirements and has_constraint:
            req_cf = self.detect_requirement_conflicts(requirements, conflicts)
            for c in req_cf:
                cf_id = f"CF-{len(conflicts) + 1:02d}"
                ctype = c.get("conflict_type", "") or CONFLICT_TYPE_IDS[0]
                if ctype not in CONFLICT_TYPE_IDS:
                    ctype = CONFLICT_TYPE_IDS[0]
                conflicts.append({
                    "id": cf_id,
                    "label": "Conflict",
                    "description": c.get("description", ""),
                    "requirement_ids": c.get("requirement_ids", []),
                    "conflict_type": ctype,
                })
            if req_cf:
                self.logger.info(f"辨識出 {len(req_cf)} 個需求/約束間衝突")

        models = system_models.get("models", []) if isinstance(system_models, dict) else []
        if models:
            conflicts = [c for c in conflicts if not (c.get("id") or "").startswith("CF-D")]
            design_cf = self.detect_design_conflicts(requirements, system_models)
            for dc in design_cf:
                cf_id = f"CF-D{len(conflicts) + 1:02d}"
                conflicts.append({
                    "id": cf_id,
                    "label": "Conflict",
                    "description": dc.get("description", ""),
                    "requirement_ids": dc.get("related_requirements", []),
                })
            if design_cf:
                self.logger.info(f"辨識出 {len(design_cf)} 個設計/可測試性衝突")

        return {**artifact, "conflicts": conflicts}

    def detect_requirement_conflicts(
        self, requirements: List[Dict], existing_conflicts: Optional[List[Dict]] = None
    ) -> List[Dict]:
        """辨識需求之間的衝突：一次檢視全部；若需求/約束超過兩條，同時檢視兩兩之間的可能衝突。"""
        if not requirements:
            return []
        result = self.detect_requirement_conflicts_all(requirements)
        for c in result:
            c.setdefault("label", "Conflict")
            c.setdefault("requirement_ids", [])
        return result

    def detect_requirement_conflicts_all(self, requirements: List[Dict]) -> List[Dict]:
        """一次檢視所有需求（含 constraint），辨識整體性或多方衝突；若超過兩條則同時檢視兩兩之間的可能衝突。"""
        if len(requirements) < 2:
            return []
        reqs_text = json.dumps(
            [{"id": r.get("id"), "type": r.get("type"), "text": (r.get("text") or "")} for r in requirements],
            ensure_ascii=False,
            indent=2,
        )
        conflict_types_text = format_conflict_types_for_prompt()
        pairwise_hint = ""
        if len(requirements) > 2:
            pairwise_hint = "\n- 因需求/約束超過兩條，請同時檢視兩兩之間的可能衝突；每筆衝突的 requirement_ids 填涉及的 id（通常為兩個）。"
        user_prompt = f"""# 任務
針對以下需求列表（含 constraint），辨識「需求與需求之間」的衝突（一次檢視全部）。例如：約束與既有功能矛盾、NFR 之間競合等。
{pairwise_hint}

# 當前需求列表
{reqs_text}

# 衝突類型定義（conflict_type 必須為以下 id 之一）
{conflict_types_text}

# 判斷標準
- 若某幾條需求之間存在語意衝突，輸出一筆 Conflict，並填寫 conflict_type、description、requirement_ids（涉及的需求 id 列表，至少兩個）
- 若無衝突，請回傳空陣列

# 輸出 JSON
{{{{
    "conflicts": [
        {{{{
            "label": "Conflict",
            "conflict_type": "類型 id",
            "description": "衝突描述",
            "requirement_ids": ["R-01", "R-C01"]
        }}}}
    ]
}}}}"""

        messages = self.build_direct_messages(user_prompt)
        try:
            response = self.model.chat_json(messages)
        except Exception as e:
            self.logger.warning(f"需求整體辨識失敗: {e}")
            return []
        return response.get("conflicts", [])

    def detect_design_conflicts(
        self, requirements: List[Dict], system_models: Dict
    ) -> List[Dict]:
        """辨識系統模型與需求之間的設計/可測試性衝突。由 Analyst 在 Modeler 產出模型後呼叫。"""
        models = system_models.get("models", []) if isinstance(system_models, dict) else []
        if not models:
            return []
        reqs_text = json.dumps(
            [{"id": r.get("id"), "type": r.get("type"), "text": (r.get("text") or "")} for r in requirements],
            ensure_ascii=False,
            indent=2,
        )
        models_summary = []
        for m in models:
            name = m.get("name", "")
            mtype = m.get("type", "")
            plantuml = (m.get("plantuml") or "")
            models_summary.append({"name": name, "type": mtype, "plantuml_preview": plantuml})
        models_text = json.dumps(models_summary, ensure_ascii=False, indent=2)

        user_prompt = f"""# 任務
根據「需求列表」與「系統模型摘要」，辨識設計層面或可測試性的衝突。例如：需求未被模型覆蓋、模型與需求矛盾、可測試性缺口等。

# 需求列表摘要
{reqs_text}

# 系統模型摘要
{models_text}

# 輸出 JSON
僅輸出有衝突的項目；若無衝突請回傳空陣列。
{{{{
    "design_conflicts": [
        {{{{
            "description": "設計/可測試性衝突描述",
            "related_requirements": ["R-01"]
        }}}}
    ]
}}}}"""

        messages = self.build_direct_messages(user_prompt)
        try:
            response = self.model.chat_json(messages)
        except Exception as e:
            self.logger.warning(f"設計衝突辨識失敗: {e}")
            return []
        return response.get("design_conflicts", [])

    def generate_scope(self, rough_idea: str, stakeholders: List[Dict]) -> Dict:
        """依初始想法與利害關係人產出專案範圍（in_scope / out_of_scope / description）。"""
        if not rough_idea:
            return {"in_scope": [], "out_of_scope": [], "description": ""}
        stakeholders_preview = json.dumps(
            [{"name": s.get("name"), "text": (s.get("text") if isinstance(s.get("text"), str) else (s.get("text") or []))} for s in stakeholders],
            ensure_ascii=False,
        )
        user_prompt = f"""# 任務
根據「初始想法」與「利害關係人需求摘要」，產出專案範圍：系統邊界內（in_scope）、明確排除（out_of_scope）、以及一句範圍描述。

# 初始想法
{rough_idea}

# 利害關係人摘要（供參考）
{stakeholders_preview}

# 輸出 JSON
{{{{
    "description": "一句話描述本專案/系統的範圍與邊界",
    "in_scope": ["範圍內項目 1", "範圍內項目 2"],
    "out_of_scope": ["明確排除項目 1"]
}}}}"""

        messages = self.build_direct_messages(user_prompt)
        try:
            response = self.model.chat_json(messages)
        except Exception as e:
            self.logger.warning(f"範圍產出失敗: {e}")
            return {"in_scope": [], "out_of_scope": [], "description": ""}
        return {
            "in_scope": response.get("in_scope", []),
            "out_of_scope": response.get("out_of_scope", []),
            "description": response.get("description", ""),
        }

    def generate_scope_glossary_assumptions(self, rough_idea: str, stakeholders: List[Dict]) -> Dict:
        """Stakeholders 發言完後由 Analyst 產出：專案範圍、術語表、假設。"""
        scope = self.generate_scope(rough_idea, stakeholders)
        stakeholders_preview = json.dumps(
            [{"name": s.get("name"), "text": (s.get("text") if isinstance(s.get("text"), str) else (s.get("text") or []))} for s in stakeholders],
            ensure_ascii=False,
        )
        user_prompt = f"""# 任務
根據「初始想法」與「利害關係人需求摘要」，產出術語表（glossary）與專案假設（assumptions）。

# 初始想法
{rough_idea}

# 利害關係人摘要
{stakeholders_preview}

# 輸出 JSON
{{{{
    "glossary": ["術語或名詞: 簡短定義", "..."],
    "assumptions": ["專案前提或假設一", "專案前提或假設二", "..."]
}}}}"""
        messages = self.build_direct_messages(user_prompt)
        try:
            response = self.model.chat_json(messages)
        except Exception as e:
            self.logger.warning(f"glossary/assumptions 產出失敗: {e}")
            return {"scope": scope, "glossary": [], "assumptions": []}
        return {
            "scope": scope,
            "glossary": response.get("glossary", []),
            "assumptions": response.get("assumptions", []),
        }

    def create_draft(self, stakeholders: List[Dict]) -> Dict:
        requirements = self.convert_to_requirements(stakeholders)
        return {"requirements": requirements, "conflicts": []}

    def convert_to_requirements(self, stakeholders: List[Dict]) -> List[Dict]:
        stakeholder_text = json.dumps(stakeholders, ensure_ascii=False, indent=2)

        user_prompt = f"""# 任務
將以下利害關係人需求轉換為結構化的需求規格。

# 利害關係人資料
{stakeholder_text}

# 處理步驟
1. 將每位利害關係人的 text 轉換為正式的 requirements，標記 source_stakeholders
2. 分類為 FR（功能性需求）或 NFR（非功能性需求）
3. 為每條需求設定 priority：must（必要）、should（重要）、could（可選）

# NFR 要求
每條 NFR 必須包含可量化的指標，禁止使用模糊形容詞。
- 效能：須指定回應時間（如「API 回應時間 ≤ 200ms，P99」）、吞吐量、並發數
- 可用性：須指定正常運行時間（如「系統可用性 ≥ 99.9%」）
- 安全性：須指定安全等級或標準（如「符合 OWASP Top 10 防護要求」）
- 可擴展性：須指定預期負載範圍（如「支援 10,000 並發使用者」）
若利害關係人原始需求模糊，分析師應根據系統類型推定合理的量化指標。

# 輸出 JSON
{{{{
    "requirements": [
        {{{{
            "id": "R-01",
            "text": "正式的需求描述",
            "type": "FR 或 NFR",
            "priority": "must 或 should 或 could",
            "source_stakeholders": ["利害關係人名稱"]
        }}}}
    ]
}}}}"""

        messages = self.build_direct_messages(user_prompt)
        response = self.model.chat_json(messages)

        requirements = response.get("requirements", [])
        for req in requirements:
            req.setdefault("type", "FR")
            req.setdefault("source_stakeholders", [])
            if req.get("priority") not in ("must", "should", "could"):
                req["priority"] = "should"

        return requirements

    def update_draft(self, artifact: Dict) -> Dict:
        """Round 級更新 Step 5.2: 根據決策與討論結果更新需求草稿"""
        context = {
            "requirements": artifact.get("requirements", []),
            "decisions": artifact.get("decisions", []),
            "discussions": artifact.get("discussions", []),
            "conflicts": artifact.get("conflicts", []),
        }
        context_text = json.dumps(context, ensure_ascii=False, indent=2)

        user_prompt = f"""# 任務
根據最新的決策（decisions）和討論結果（discussions），更新需求草稿。

# 當前資料
{context_text}

# 更新規則
1. 依 decisions 與 discussions 的結論，修改或新增 requirements
2. 已由決策解決的衝突（decisions 中的 resolved_conflict_ids）對應的需求應反映該決策內容
3. 保留未受影響的需求不變
4. 去除因決策而不再需要的需求
5. 每條需求保留或設定 priority（must / should / could）

# 輸出 JSON
{{{{
    "requirements": [
        {{{{
            "id": "R-01",
            "text": "需求描述",
            "type": "FR 或 NFR 或 constraint",
            "priority": "must 或 should 或 could",
            "source_stakeholders": ["來源"]
        }}}}
    ]
}}}}"""

        messages = self.build_direct_messages(user_prompt)
        response = self.model.chat_json(messages)

        requirements = response.get("requirements", artifact.get("requirements", []))
        for req in requirements:
            if req.get("priority") not in ("must", "should", "could"):
                req["priority"] = "should"
        return {
            "requirements": requirements,
            "conflicts": artifact.get("conflicts", []),
        }

    def respond_to_topic(self, topic, previous_responses=None, artifact_snapshot=None):
        topic_text = f"議題 [{topic.get('id', '')}]: {topic.get('title', '')}\n描述: {topic.get('description', '')}"

        prev_text = ""
        if previous_responses:
            parts = [f"【{r.get('agent', '?')}】\n{r.get('response', {}).get('statement', '')}"
                     for r in previous_responses]
            prev_text = "\n前面的發言:\n" + "\n\n".join(parts)

        snapshot_text = ""
        if artifact_snapshot:
            snapshot_text = f"\n# 當前專案狀態（供參考）\n{json.dumps(artifact_snapshot, ensure_ascii=False, indent=2)}"

        tool_hint = ""
        if self.tools:
            tool_hint = "\n# 工具使用\n- 可先使用 query_artifact 查詢當前需求與衝突，再根據結果撰寫發言。\n- 最後**必須**輸出下列 JSON。"

        user_prompt = f"""你正在以系統分析師的身份參與需求討論。

{topic_text}
{prev_text}
{snapshot_text}
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
