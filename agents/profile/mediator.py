import json

from typing import Dict, List, Any, Optional
from agents.base import BaseAgent


class MediatorAgent(BaseAgent):
    """需求調解主持人 — 會議主持、衝突報告、草稿生成"""

    name = "mediator"

    system_prompt = """你是需求調解主持人，負責主持需求討論會議。

核心職責：
1. 議題管理 — 分析需求規格，識別需要討論的議題
2. 討論主持 — 決定討論模式（逐一發言/同時發言），維持討論秩序
3. 共識促成 — 綜合各方意見，嘗試達成共識
4. 衝突報告 — 將衝突結構化為報告
5. 草稿生成 — 將中間產物轉化為需求草稿

核心原則：
- 中立客觀 — 不偏袒任何利害關係人，不提出自己的技術觀點
- 忠於資料 — 只根據已有的分析結果和討論內容做出綜合判斷
- 無法共識時升級 — 無法達成共識時直接升級至人類裁決"""

    def __init__(self, model, tools: Optional[list] = None, registry=None):
        super().__init__(model, tools=tools, registry=registry)

    # Round 2+: 議題生成

    def generate_topics(self, spec_md: str, rough_idea: str, registry=None) -> List[Dict]:
        # 從 registry 取得已註冊的可選參與者（排除 mediator/documentor 本身）
        exclude = {"mediator", "documentor"}
        if registry:
            registered = [n for n in registry.get_names() if n not in exclude]
        else:
            registered = ["user", "analyst", "expert", "modeler"]
        registered_text = ", ".join(registered)

        user_prompt = f"""# 任務
依據需求草稿，提出需要討論的議題。

# 需求草稿
{spec_md}

# 議題類型
- conflict: 需要解決需求衝突
- requirement_gap: 需求缺口，需要補充
- refinement: 需求不夠明確，需要精煉

# 討論模式選擇
- sequential（逐一發言）：爭議性高的議題，讓各方充分表達並回應
- simultaneous（同時發言）：資訊補充、簡單議題，各方獨立表達即可

# 約束
- 避免與前次會議已解決的議題重複
- 每個議題必須有明確的預期結果
- 只能從以下已註冊的參與者中選擇: {registered_text}

# 輸出 JSON
{{{{
    "topics": [
        {{{{
            "id": "T-01",
            "title": "議題標題",
            "description": "議題描述",
            "type": "conflict/requirement_gap/refinement",
            "discussion_mode": "sequential/simultaneous",
            "participants": ["agent名稱"],
            "speaking_order": ["agent名稱"],
            "expected_outcome": "預期結果"
        }}}}
    ]
}}}}"""

        messages = self.build_direct_messages(user_prompt)
        response = self.model.chat_json(messages)

        topics = response.get("topics", [])
        validated = []
        for t in topics:
            if not isinstance(t, dict) or not t.get("id") or not t.get("title"):
                continue
            t.setdefault("type", "refinement")
            t.setdefault("discussion_mode", "simultaneous")
            t.setdefault("participants", registered)
            t.setdefault("speaking_order", t["participants"])
            t.setdefault("expected_outcome", "")
            # 過濾掉未註冊的 agent
            t["participants"] = [p for p in t["participants"] if p in registered]
            t["speaking_order"] = [p for p in t["speaking_order"] if p in registered]
            validated.append(t)

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

        # 收集所有 questions_to_others，讓被點名且尚未回應該問題的 agent 補充回應
        pending_questions = self.collect_pending_questions(contributions, speaking_order)
        if pending_questions:
            self.logger.info(f"[{topic['id']}] 追加回應 {len(pending_questions)} 位被點名 agent")
            for target_name, questions in pending_questions.items():
                agent = registry.get(target_name)
                if not agent:
                    continue
                try:
                    response = agent.respond_to_topic(
                        self.build_question_topic(topic, questions),
                        previous_responses=contributions,
                    )
                    contributions.append({
                        "agent": target_name,
                        "response": response if isinstance(response, dict) else {"content": str(response)},
                        "is_reply": True,
                    })
                except Exception as e:
                    self.logger.warning(f"  {target_name} 追加回應失敗: {e}")

        return contributions

    def collect_pending_questions(self, contributions: List[Dict], speaking_order: list) -> Dict[str, list]:
        """收集 contributions 中 questions_to_others 指向的、尚未在後續發言中回應的 agent"""
        spoken = set()
        questions_by_target: Dict[str, list] = {}

        for c in contributions:
            agent_name = c.get("agent", "")
            spoken.add(agent_name)
            resp = c.get("response", {})
            for q in resp.get("questions_to_others", []):
                target = q.get("to", "")
                question = q.get("question", "")
                if target and question:
                    questions_by_target.setdefault(target, []).append({
                        "from": agent_name,
                        "question": question,
                    })

        # 只保留已經發言過但被後面的人點名的（需要追加回應），或不在 speaking_order 中但被點名的
        # 排除已經在該 agent 發言之後才被點名的情況 → 簡化為：被點名的 agent 若已發言，則需追加
        pending = {}
        for target, qs in questions_by_target.items():
            # 過濾：只保留在 target 發言之後才提出的問題
            target_spoken = target in spoken
            if not target_spoken:
                continue
            late_questions = []
            target_idx = next((i for i, c in enumerate(contributions) if c.get("agent") == target), -1)
            for q in qs:
                asker = q["from"]
                asker_idx = next((i for i, c in enumerate(contributions) if c.get("agent") == asker), -1)
                if asker_idx > target_idx:
                    late_questions.append(q)
            if late_questions:
                pending[target] = late_questions

        return pending

    def build_question_topic(self, original_topic: Dict, questions: list) -> Dict:
        """將被點名的問題包裝成追加議題"""
        q_text = "\n".join(f"- {q['from']} 問：{q['question']}" for q in questions)
        return {
            **original_topic,
            "description": f"{original_topic.get('description', '')}\n\n# 其他參與者向你提出的問題\n{q_text}",
        }

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
    "action_items": [
        {{{{"assignee": "agent名稱", "task": "待辦事項描述"}}}}
    ],
    "escalation_needed": false/true
}}}}"""

        messages = self.build_direct_messages(user_prompt)
        response = self.model.chat_json(messages)

        result = {
            "resolution": response.get("resolution", "unresolved"),
            "summary": response.get("summary", ""),
            "decision": response.get("decision", ""),
            "remaining_issues": response.get("remaining_issues", []),
            "action_items": response.get("action_items", []),
            "escalation_needed": response.get("escalation_needed", False),
        }
        return result

    # Round 2+: 人類裁決篩選

    def prepare_human_options(self, topic: Dict, contributions: List[Dict]) -> Dict:
        discussion_text = ""
        for c in contributions:
            agent = c.get("agent", "?")
            resp = c.get("response", {})
            position = resp.get("position", "")
            arguments = resp.get("arguments", [])
            suggestions = resp.get("suggestions", [])
            discussion_text += f"\n【{agent}】\n立場: {position}\n"
            if arguments:
                discussion_text += "論點:\n" + "\n".join(f"  - {a}" for a in arguments) + "\n"
            if suggestions:
                discussion_text += "建議:\n" + "\n".join(f"  - {s}" for s in suggestions) + "\n"

        user_prompt = f"""# 任務
從以下議題討論中，篩選出 3 個最佳方案和 1 個折衷方案，供人類做最終裁決。

# 議題資訊
標題: {topic.get('title', '')}
描述: {topic.get('description', '')}

# 各方討論內容
{discussion_text}

# 要求
1. 從討論中提取 3 個最具體、可行性最高的方案（best_options）
2. 另外設計 1 個折衷方案（compromise），結合各方觀點的優點

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

        best = response.get("best_options", [])[:3]
        compromise = response.get("compromise", {})
        if compromise:
            compromise.setdefault("id", 4)

        return {"best_options": best, "compromise": compromise}

    # 產生需求規格（Markdown）

    def generate_draft(self, artifact: Dict[str, Any]) -> str:
        full_artifact = {
            "rough_idea": artifact.get("rough_idea", ""),
            "stakeholders": artifact.get("stakeholders", []),
            "candidates": self.extract_candidates(artifact.get("analyse", [])),
            "reports": artifact.get("reports", []),
            "feedback": artifact.get("feedback", []),
            "decisions": artifact.get("decisions", []),
        }
        artifact_text = json.dumps(full_artifact, ensure_ascii=False, indent=2)

        user_prompt = f"""# 任務
將以下中間產物整理成需求草稿 Markdown 文件。

# 中間產物（JSON 格式，僅供參考，不要照搬格式）
{artifact_text}

# 輸出格式要求
- 必須輸出純 Markdown 格式（使用 #, ##, ###, -, 表格等 Markdown 語法）
- 禁止輸出 JSON 格式，禁止使用 ```json 代碼塊包裝整份文件
- 需求要有編號（如 UR-xx, FR-xx, NFR-xx, CR-xx）
- 結構由你依據資料內容彈性安排，涵蓋系統概述、利害關係人、需求、衝突等重點即可
- 最後預留一個「## 附錄」章節（內容留空，UML 模型將由 Modeler 後續補充）

# 約束
- 只根據已提供的資料填寫，禁止捏造
- 輸出第一行必須是 Markdown 標題（以 # 開頭）"""

        messages = self.build_direct_messages(user_prompt)
        spec_md = self.model.chat(messages)
        spec_md = self.strip_code_fences(spec_md)
        return spec_md

    @staticmethod
    def strip_code_fences(text: str) -> str:
        """移除 LLM 輸出可能包裹的 code fence"""
        stripped = text.strip()
        if stripped.startswith("```"):
            first_newline = stripped.find("\n")
            if first_newline != -1:
                stripped = stripped[first_newline + 1:]
            if stripped.endswith("```"):
                stripped = stripped[:-3]
        return stripped.strip()

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

        messages = self.build_direct_messages(user_prompt)
        response = self.model.chat_json(messages)

        if isinstance(response, dict) and "conflicts" in response:
            return response["conflicts"]
        elif isinstance(response, list):
            return response
        return []