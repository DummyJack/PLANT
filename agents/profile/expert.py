import json
import logging
from typing import Dict, List, Optional
from pathlib import Path

from openai import BadRequestError
from agents.base import BaseAgent
from agents.tools.read_external_file import ReadExternalFileTool


class ExpertAgent(BaseAgent):
    """領域專家 Agent — 賦予 domain-research skill，以 read_external_file 工具讀取 doc/ 參考檔案注入法規/標準/安全規範。"""

    name = "expert"

    system_prompt = """你是領域專家，負責注入必須遵守的法規、標準、安全規範（constraint）。
核心原則：Evidence-first、可追溯來源、無證據不建議；約束須含具體條文、適用範圍、合規要求與風險。"""

    def __init__(
        self,
        model,
        tools: Optional[list] = None,
        registry=None,
        doc_dir: str = "doc",
    ):
        agent_tools = list(tools or [])
        self.doc_dir = Path(doc_dir)
        self.doc_dir.mkdir(parents=True, exist_ok=True)
        agent_tools.append(ReadExternalFileTool(base_dir=self.doc_dir))

        super().__init__(
            model,
            tools=agent_tools,
            registry=registry,
            skill_names=["domain-research"],
        )

    @staticmethod
    def parse_first_json(raw: str) -> Dict:
        """從可能含多個 JSON 或後綴文字的內容中，只解析第一個完整 JSON 物件。"""
        if not raw or not isinstance(raw, str):
            return {}
        raw = raw.strip()
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            pass
        start = raw.find("{")
        if start == -1:
            return {}
        depth = 0
        for i in range(start, len(raw)):
            if raw[i] == "{":
                depth += 1
            elif raw[i] == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(raw[start : i + 1])
                    except json.JSONDecodeError:
                        pass
                    break
        return {}

    def build_inject_fallback_prompt(
        self, requirements: List[Dict], rough_idea: str
    ) -> str:
        """內容政策觸發時使用的精簡 prompt，不含外部文件與完整衝突列表。"""
        idea = (rough_idea or "")[:500]
        req_limited = requirements[:10] if requirements else []
        requirements_text = json.dumps(req_limited, ensure_ascii=False, indent=2)
        return f"""# 任務
根據以下需求與背景，以你的專業知識產出應遵守的法規/標準/安全規範，作為 constraint 類型需求。

# 背景（摘要）
{idea}

# 當前需求（前 10 筆）
{requirements_text}

# 步驟
1. 依專業知識識別相關法規、標準、安全規範
2. 將約束寫入 new_requirements，type 標記為 constraint，ref 可填「依領域知識」
3. 若無相關法規可產出，new_requirements 可為空陣列

# 輸出 JSON
{{{{
    "new_requirements": [
        {{{{
            "id": "R-C01",
            "text": "約束描述（法規/標準名稱、合規要求、適用範圍）",
            "type": "constraint",
            "ref": "來源說明",
            "source_stakeholders": ["expert"]
        }}}}
    ]
}}}}"""

    def inject_domain(
        self,
        requirements: List[Dict],
        conflicts: List[Dict],
        rough_idea: str,
        project_overview: Optional[str] = None,
    ) -> Dict:
        """Phase 0: 領域知識注入。依 domain-research skill 使用 read_external_file 讀取 doc/ 參考檔案產出 constraint。"""
        requirements_text = json.dumps(requirements, ensure_ascii=False, indent=2)
        conflicts_text = json.dumps(conflicts, ensure_ascii=False, indent=2)

        overview = (project_overview or "").strip()
        scope_constraint = ""
        if overview:
            scope_constraint = f"\n# 專案概述（供判斷適用範圍）\n{overview}\n"

        has_tools = bool(self.tools)
        tool_instruction = (
            "可先使用 read_external_file 讀取 doc/ 目錄下的參考檔案（法規、標準、技術文件），再依內容產出約束。"
            if has_tools
            else "根據你的專業知識提供建議。"
        )

        user_prompt = f"""# 任務
審查以下需求，注入「與本專案直接相關」且必須遵守的法規/標準/安全規範作為 constraint 類型的需求。

# 背景
{rough_idea}
{scope_constraint}
# 當前需求
{requirements_text}

# 當前衝突
{conflicts_text}

# 步驟
1. {tool_instruction}
2. 依專案概述與範圍，僅識別「適用於本專案」的法規、標準、安全規範（與專案領域、產業、部署環境或受眾直接相關）
3. 將這些約束寫入 new_requirements（type 標記為 constraint）
（衝突辨識由 Analyst 在注入後統一執行，Expert 僅產出 new_requirements）

# 相關性要求
- 每條 constraint 的適用範圍須與本專案一致；與本專案無關或僅間接相關的法規/標準不要列入
- 若專案概述不明，可依 rough_idea 與當前需求推斷專案領域，只產出該領域內確實適用的約束

# 詳細度要求
每條 constraint 的 text 必須包含：法規/標準全名與條文編號、具體合規要求、適用範圍、不合規風險。

# 約束
- 每條 constraint 須附 ref（來源 URL 或文件名）；嚴禁虛構
- 若無與本專案相關的法規，new_requirements 可為空陣列

# 輸出 JSON
{{{{
    "new_requirements": [
        {{{{
            "id": "R-C01",
            "text": "詳細的約束描述（法規全名、條文、合規要求、適用範圍、風險）",
            "type": "constraint",
            "ref": "來源 URL 或文件名",
            "source_stakeholders": ["expert"]
        }}}}
    ]
}}}}"""

        # 若有 domain-research skill，將 skill 內容注入 system 以引導領域研究與工具使用
        system_content = self.system_prompt
        if "domain-research" in self.skill_names:
            try:
                from agents.skills.loader import get_skill
                skill = get_skill("domain-research")
                system_content = system_content + "\n\n# Skill: domain-research\n\n" + (skill.get("content") or "")
            except Exception as e:
                self.logger.debug("載入 domain-research skill 失敗: %s", e)
        messages = [{"role": "system", "content": system_content}, {"role": "user", "content": user_prompt}]

        try:
            if self.tools:
                raw = self.chat_with_tools(messages, max_rounds=3)
                response = self.parse_first_json(raw)
            else:
                response = self.model.chat_json(messages)
        except BadRequestError as e:
            err_msg = str(e).lower()
            if "invalid_prompt" in err_msg or "usage policy" in err_msg:
                self.logger.warning(
                    "Expert 請求觸發內容政策，改以精簡 prompt 僅依模型知識產出約束"
                )
                fallback_prompt = self.build_inject_fallback_prompt(
                    requirements, rough_idea
                )
                response = self.model.chat_json(
                    self.build_direct_messages(fallback_prompt)
                )
            else:
                raise

        new_reqs = response.get("new_requirements", [])
        if not isinstance(new_reqs, list):
            new_reqs = []
        for req in new_reqs:
            if isinstance(req, dict):
                req.setdefault("type", "constraint")
                req.setdefault("source_stakeholders", ["expert"])
                req.setdefault("priority", "must")
        new_reqs = [r for r in new_reqs if isinstance(r, dict)]

        if len(new_reqs) == 0:
            reasons = []
            if not overview:
                reasons.append("專案概述為空")
            if not has_tools:
                reasons.append("無 read_external_file 工具或 doc/ 無參考檔案")
            if reasons:
                self.logger.info(
                    f"Expert 回傳 0 條約束，可能原因：{'、'.join(reasons)}；或模型判斷無適用法規／解析未取得 new_requirements"
                )
            else:
                self.logger.info(
                    "Expert 回傳 0 條約束，可能為模型判斷本專案無適用法規/標準，或輸出格式未含 new_requirements"
                )

        return {"requirements": requirements + new_reqs}

    def get_optional_skill_context(
        self, topic: Dict, artifact_snapshot: Optional[Dict]
    ) -> Optional[str]:
        """議題為領域與合規檢查時，觸發 domain-research 產出簡短要點供發言參考。"""
        if topic.get("category") != "domain_compliance":
            return None
        if "domain-research" not in self.skill_names:
            return None
        context = {"topic": topic, "artifact_snapshot": artifact_snapshot or {}}
        task = """針對 Context 中的議題與專案狀態，簡要列出 1～3 點法規/合規/安全相關要點（可含適用範圍與風險），供會議發言參考。只輸出簡短條列文字，勿 JSON。"""
        try:
            raw = self.invoke_skill("domain-research", task, context=context)
            return (raw or "").strip()[:1500]
        except Exception as e:
            self.logger.debug("議程中觸發 domain-research 失敗: %s", e)
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
            tool_hint = "\n# 工具使用\n- 可先使用 read_external_file 讀取 doc/ 參考檔案，再根據結果撰寫發言。\n- 最後**必須**輸出下列 JSON。"

        user_prompt = f"""你正在以領域專家的身份參與需求討論。

{topic_text}
{prev_text}
{snapshot_text}
{skill_section}
{tool_hint}

# 思考與發言流程
1. 先思考：(1) 此議題相關的法規、標準或技術限制 (2) 不可讓步的要點（須附法規/標準依據）(3) 可接受調整或折衷的要點
2. 再根據思考結果，撰寫一段完整的發言（statement），針對議題提出你的專業見解與法規依據
3. 若有需要請其他角色回答的問題，列入 open_questions（to 填寫目標 agent 名稱，如 "user"、"analyst"、"modeler"）

# 發言風格
- 以領域專家在會議中的口吻：引用法規/標準時註明來源或條文，說明不合規風險與適用範圍
- 資訊不足時可明確說「這部分需要再查證」或「依目前查到的資料…」，不捏造

# 約束
- statement 必須包含具體的法規依據和不合規風險，禁止虛構法規或標準名稱
- 論點必須有客觀依據，無依據則標註「資訊不足」
- 依你的立場投票（vote）：agreed 表示可達成共識；unresolved 表示仍有衝突需升級

輸出 JSON:
{{{{
    "statement": "針對此議題的完整發言內容（含法規依據與風險說明）",
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
