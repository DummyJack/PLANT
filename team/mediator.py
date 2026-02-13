import json

from typing import Dict, List, Any, Optional

from agents.base import BaseAgent
from agents.memory import Memory


class MediatorAgent(BaseAgent):
    """需求調解主持人 — 會議主持、衝突報告、草稿生成"""

    name = "mediator"

    system_prompt = """你是需求調解主持人（Mediator Agent），負責主持需求討論會議。

核心職責：
1. 議題管理 — 分析需求規格，識別需要討論的議題
2. 討論主持 — 決定討論模式（逐一/同時），維持討論秩序
3. 共識促成 — 綜合各方意見，嘗試達成共識
4. 衝突報告 — 將衝突結構化為報告
5. 草稿生成 — 將討論結果轉化為需求草稿

核心原則：
- 中立客觀 — 不偏袒任何利害關係人，不提出自己的技術觀點
- 忠於資料 — 只根據已有的分析結果和討論內容做出綜合判斷
- 無法共識時升級 — 先請 Expert 裁決，Expert 也無法時才升級至人類"""

    reflection_criteria = "衝突報告必須涵蓋所有已識別的衝突，每個衝突有明確的標題、描述和涉及的利害關係人。"

    def __init__(self, model, tools: Optional[list] = None,
                 memory: Optional[Memory] = None, registry=None):
        super().__init__(model, tools=tools, memory=memory, registry=registry)

    # Round 2+: 議題生成

    def generate_topics(self, current_spec: Dict, rough_idea: str,
                        previous_meetings: List[Dict] = None) -> List[Dict]:
        self.memory.clear_short_term()

        spec_text = json.dumps(current_spec, ensure_ascii=False, indent=2)
        if len(spec_text) > 3000:
            spec_text = spec_text[:3000] + "\n... (已截斷)"

        idea_text = rough_idea if isinstance(rough_idea, str) else str(rough_idea)

        prev_meetings_text = ""
        if previous_meetings:
            summaries = []
            for m in previous_meetings[-5:]:
                topic = m.get("topic", {})
                resolution = m.get("resolution", {})
                summaries.append(
                    f"- {topic.get('title', '?')}: {resolution.get('status', '?')} — {resolution.get('summary', '')[:100]}"
                )
            prev_meetings_text = f"\n# 前次會議記錄\n" + "\n".join(summaries)

        user_prompt = f"""# 任務
分析現有需求規格，識別本輪需要討論的議題。

# 初始想法
{idea_text}

# 現有需求規格
{spec_text}
{prev_meetings_text}

# 議題類型
- conflict: 需求衝突，需要解決
- requirement_gap: 需求缺口，需要補充
- refinement: 需求不夠明確，需要精煉
- new_concern: 新發現的關注點

# 討論模式選擇
- sequential（逐一發言）：爭議性高的議題，讓各方充分表達並回應
- simultaneous（同時發言）：資訊補充、簡單議題，各方獨立表達即可

# 約束
- 避免與前次會議已解決的議題重複
- 每個議題必須有明確的預期結果
- 可選參與者: user, analyst, expert

# 輸出 JSON
{{{{
    "topics": [
        {{{{
            "id": "T-01",
            "title": "議題標題",
            "description": "議題描述",
            "type": "conflict/requirement_gap/refinement/new_concern",
            "discussion_mode": "sequential/simultaneous",
            "participants": ["agent名稱"],
            "speaking_order": ["agent名稱"],
            "expected_outcome": "預期結果"
        }}}}
    ]
}}}}"""

        self.memory.add("user", "分析 Spec 生成議題清單")
        messages = self.build_direct_messages(user_prompt)
        response = self.model.chat_json(messages)

        topics = response.get("topics", [])
        validated = []
        for t in topics:
            if not isinstance(t, dict) or not t.get("id") or not t.get("title"):
                continue
            t.setdefault("type", "refinement")
            t.setdefault("discussion_mode", "simultaneous")
            t.setdefault("participants", ["user", "analyst", "expert"])
            t.setdefault("speaking_order", t["participants"])
            t.setdefault("expected_outcome", "")
            validated.append(t)

        self.memory.add("assistant", f"已生成 {len(validated)} 個議題")
        return validated

    # Round 2+: 主持討論

    def moderate_sequential(self, topic: Dict, registry) -> List[Dict]:
        """逐一發言模式：按順序呼叫 Agent，每個 Agent 可看到前面的發言"""
        contributions = []
        speaking_order = topic.get("speaking_order", topic.get("participants", []))
        self.logger.info(f"[{topic['id']}] 逐一發言: {' → '.join(speaking_order)}")

        for agent_name in speaking_order:
            agent = registry.get(agent_name)
            if not agent:
                self.logger.warning(f"Agent '{agent_name}' 未註冊，跳過")
                continue
            try:
                response = agent.respond_to_topic(topic, previous_responses=contributions)
                contributions.append({
                    "agent": agent_name,
                    "response": response if isinstance(response, dict) else {"content": str(response)},
                })
            except Exception as e:
                self.logger.warning(f"  {agent_name} 發言失敗: {e}")
                contributions.append({"agent": agent_name, "response": {"content": f"（發言失敗: {e}）"}})

        return contributions

    def moderate_simultaneous(self, topic: Dict, registry) -> List[Dict]:
        """同時發言模式：所有 Agent 獨立作答"""
        contributions = []
        participants = topic.get("participants", [])
        self.logger.info(f"[{topic['id']}] 同時發言: {', '.join(participants)}")

        for agent_name in participants:
            agent = registry.get(agent_name)
            if not agent:
                self.logger.warning(f"Agent '{agent_name}' 未註冊，跳過")
                continue
            try:
                response = agent.respond_to_topic(topic, previous_responses=None)
                contributions.append({
                    "agent": agent_name,
                    "response": response if isinstance(response, dict) else {"content": str(response)},
                })
            except Exception as e:
                self.logger.warning(f"  {agent_name} 發言失敗: {e}")
                contributions.append({"agent": agent_name, "response": {"content": f"（發言失敗: {e}）"}})

        return contributions

    # Round 2+: 綜合結果

    def synthesize_and_resolve(self, topic: Dict, contributions: List[Dict]) -> Dict:
        discussion_text = ""
        for c in contributions:
            agent = c.get("agent", "?")
            resp = c.get("response", {})
            content = resp.get("content", resp.get("position", json.dumps(resp, ensure_ascii=False)))
            discussion_text += f"\n【{agent}】\n{content}\n"

        user_prompt = f"""# 任務
綜合以下議題的討論結果，判斷是否達成共識。

# 議題資訊
標題: {topic.get('title', '')}
描述: {topic.get('description', '')}
類型: {topic.get('type', '')}

# 各方討論內容
{discussion_text}

# 共識判斷標準
- agreed: 各方立場一致或差異可忽略，可直接形成決策
- partial: 部分共識，仍有具體爭議點需後續處理
- unresolved: 各方立場嚴重分歧，無法自行解決

# 約束
- 如實反映各方立場，不要人為「製造」共識
- decision 必須具體可執行，不能是空泛的折衷語句

# 輸出 JSON
{{{{
    "resolution": "agreed/partial/unresolved",
    "summary": "綜合摘要",
    "decision": "具體決策內容",
    "remaining_issues": ["剩餘爭議"],
    "escalation_needed": false/true
}}}}"""

        self.memory.add("user", f"綜合議題 {topic.get('id', '')} 的討論結果")
        messages = self.build_direct_messages(user_prompt)
        response = self.model.chat_json(messages)

        result = {
            "resolution": response.get("resolution", "unresolved"),
            "summary": response.get("summary", ""),
            "decision": response.get("decision", ""),
            "remaining_issues": response.get("remaining_issues", []),
            "escalation_needed": response.get("escalation_needed", False),
        }
        self.memory.add("assistant", f"議題 {topic.get('id', '')}: {result['resolution']}")
        return result

    # 產生需求草稿（逐章節）

    # 每個章節對應的 artifact 資料
    DRAFT_SECTION_DATA_MAP = {
        "1. System Overview": ["rough_idea"],
        "2. Requirement Engineering": ["candidates", "stakeholders"],
        "3. System Stakeholders": ["stakeholders"],
        "4. Conflicting Requirements": ["reports", "decisions"],
        "5. Functional Requirements": ["candidates", "feedback", "decisions"],
        "6. Non-Functional Requirements": ["candidates", "feedback"],
    }

    # 每個章節的額外提示
    DRAFT_SECTION_HINTS = {
        "1. System Overview": "根據 rough_idea 撰寫系統概述。",
        "2. Requirement Engineering": "從 candidates 整理使用者需求和系統需求。",
        "3. System Stakeholders": "列出每位利害關係人的關注點和需求。",
        "4. Conflicting Requirements": (
            "將 reports 轉為衝突需求：reports 的 id, title, stakeholder_names, description → 此章節的 id, stakeholder_name, description。"
            "decisions 為討論後的決策結果。"
        ),
        "5. Functional Requirements": "從 candidates 和 decisions 中提取功能性需求。",
        "6. Non-Functional Requirements": "從 candidates 中提取非功能性需求（效能、安全、可用性等）。",
    }

    def generate_draft(self, artifact: Dict[str, Any], draft_template: list) -> Dict[str, Any]:
        full_artifact = {
            "rough_idea": artifact.get("rough_idea", ""),
            "stakeholders": artifact.get("stakeholders", []),
            "candidates": self.extract_candidates(artifact.get("analyse", [])),
            "reports": artifact.get("reports", []),
            "feedback": artifact.get("feedback", []),
            "decisions": artifact.get("decisions", []),
        }

        generated_sections = []

        for section_template in draft_template:
            section_name = section_template.get("section", "")
            self.logger.info(f"  生成草稿章節: {section_name}")

            # 取得該章節對應的 artifact 子集
            relevant_keys = self.DRAFT_SECTION_DATA_MAP.get(section_name, list(full_artifact.keys()))
            section_artifact = {k: full_artifact[k] for k in relevant_keys if k in full_artifact}
            section_artifact_text = json.dumps(section_artifact, ensure_ascii=False, indent=2)

            section_template_text = json.dumps(section_template, ensure_ascii=False, indent=2)
            hint = self.DRAFT_SECTION_HINTS.get(section_name, "")

            user_prompt = f"""# 任務
根據中間產物產生需求草稿的「{section_name}」章節。

# 提示
{hint}

# 相關資料
{section_artifact_text}

# 約束
- 嚴格遵循模板結構
- 只根據已提供的資料填寫，禁止捏造

# 輸出 JSON（只輸出此章節）
{section_template_text}"""

            try:
                section_result = self.generate_with_reflection(user_prompt)
                generated_sections.append(section_result)
            except Exception as e:
                self.logger.warning(f"  章節 {section_name} 生成失敗: {e}，使用空模板")
                generated_sections.append(section_template)

        draft = {"draft": generated_sections}
        self.memory.add("assistant", f"draft generated ({len(generated_sections)} sections)")
        return draft

    def extract_candidates(self, analyse: list) -> list:
        all_candidates = []
        for group in analyse:
            if "candidates" in group:
                all_candidates.extend(group["candidates"])
        return all_candidates

    # 衝突報告
    def generate_conflict_report(self, conflict_groups: List[Dict]) -> List[Dict]:
        formatted_conflicts = []
        for idx, group in enumerate(conflict_groups, 1):
            conflict_text = f"{idx}. "
            for stakeholder_name, text in group.get("texts", {}).items():
                if isinstance(text, list):
                    text_str = "; ".join(text)
                else:
                    text_str = text
                conflict_text += f"{stakeholder_name}: {text_str}\n"
            conflict_text += f"衝突理由: {group.get('reason', '')}\n"
            formatted_conflicts.append(conflict_text)

        conflicts_text = "\n".join(formatted_conflicts)

        user_prompt = f"""# 任務
根據以下 {len(conflict_groups)} 個需求衝突分析結果，為每個衝突生成結構化的衝突報告。

# 衝突分析
{conflicts_text}

# 報告欄位
每個衝突報告包含：
1. id: 衝突 ID（CR-01 起）
2. stakeholder_names: 涉及的利害關係人名稱列表
3. title: 衝突標題（簡明扼要）
4. description: 詳細衝突描述（包含具體矛盾點）

# 約束
- 必須為所有 {len(conflict_groups)} 個衝突都生成報告
- description 必須具體描述矛盾點，不得空泛

# 輸出 JSON
{{{{
    "conflicts": [
        {{{{
            "id": "CR-01",
            "stakeholder_names": ["利害關係人A", "利害關係人B"],
            "title": "衝突標題",
            "description": "詳細衝突描述"
        }}}}
    ]
}}}}"""

        self.memory.add("user", f"產生 {len(conflict_groups)} 個衝突報告")
        response = self.generate_with_reflection(user_prompt)

        if isinstance(response, dict) and "conflicts" in response:
            return response["conflicts"]
        elif isinstance(response, list):
            return response
        return []