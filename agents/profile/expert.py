import json
from typing import Dict, List, Optional
from pathlib import Path

from agents.base import BaseAgent

# 與 ReadExternalFileTool 支援的副檔名一致（供 flow 組裝工具時判斷）
DOC_SUPPORTED_SUFFIXES = (".txt", ".md", ".json", ".pdf", ".docx", ".doc")


def has_supported_doc_files(doc_dir: Path) -> bool:
    """檢查 doc 目錄下是否至少有一個支援的檔案（含子目錄）。"""
    if not doc_dir.is_dir():
        return False
    for p in doc_dir.rglob("*"):
        if p.is_file() and p.suffix.lower() in DOC_SUPPORTED_SUFFIXES:
            return True
    return False


class ExpertAgent(BaseAgent):
    """領域專家 Agent — 賦予 domain-research skill，可搭配 read_external_file 等工具（由 flow 依 enable_tools 注入）。"""

    name = "expert"

    system_prompt = """你是領域專家，負責提供必須遵守的法規、標準、安全規範。
核心原則：Evidence-first、可追溯來源、無證據不建議；約束須含具體條文、適用範圍、合規要求與風險。"""

    def __init__(
        self,
        model,
        tools: Optional[list] = None,
        registry=None,
        doc_dir: str = "doc",
    ):
        self.doc_dir = Path(doc_dir)
        self.doc_dir.mkdir(parents=True, exist_ok=True)
        super().__init__(
            model,
            tools=tools or [],
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

    def provide_domain_knowledge(
        self,
        requirements: List[Dict],
        conflicts: List[Dict],
        project_overview: str = "",
    ) -> Dict:
        """Phase 0: 提供領域知識。依 domain-research skill 的 Research Results 格式產出，結果寫入 artifact.feedback.domain_research，不修改 requirements。"""
        project_overview = (project_overview or "").strip()
        context = {
            "project_overview": project_overview,
            "requirements": requirements,
            "conflicts": conflicts,
        }
        task = """依 domain-research skill 的 **Output Format: Research Results** 執行領域研究並產出結果。
審查 Context 中的需求與專案概述，若有 read_external_file 工具可先讀取 doc/ 參考檔案，依專案範圍識別法規/標準/安全規範與 derived_requirements。
輸出「僅一個」JSON 物件，鍵名 "research_session"，值為物件，須含：
- id（如 RES-{timestamp}）
- domain, topic, timestamp
- findings（domain_context, best_practices, regulatory, competitive 等陣列）
- derived_requirements（陣列，每筆含 id, text, source, source_detail, confidence, needs_validation, category；法規/約束類請產出於此）
- recommendations（選填）
- gaps_in_research（選填）
findings、derived_requirements 的 text/source_detail、recommendations、gaps_in_research 等所有描述與說明文字請使用繁體中文。id、category 等欄位名維持英文。勿輸出 Markdown，只輸出該 JSON。"""
        raw = self.invoke_skill("domain-research", task, context=context)
        response = self.parse_first_json(raw or "")
        research_session = response.get("research_session")
        if isinstance(research_session, dict):
            pass
        elif isinstance(response, dict) and (
            response.get("findings") or response.get("derived_requirements")
        ):
            # skill 有時直接回傳 research 內容於頂層
            research_session = response
        else:
            research_session = {}
        if not research_session:
            self.logger.warning(
                "domain-research skill 未產出 research_session（可能為 JSON 解析失敗或 skill 回傳格式不符）"
            )
        return {"feedback": {"domain_research": research_session}}

    def get_optional_skill_context(
        self, topic: Dict, artifact_snapshot: Optional[Dict]
    ) -> Optional[str]:
        """議題為領域與合規檢查時，觸發 domain-research 產出簡短要點供發言參考。"""
        if topic.get("category") != "domain_compliance":
            return None
        if "domain-research" not in self.skill_names:
            return None
        context = {"topic": topic, "artifact_snapshot": artifact_snapshot or {}}
        task = """針對 Context 中的議題與專案狀態，簡要列出 1～3 點法規/合規/安全相關要點（可含適用範圍與風險），供會議發言參考。請使用繁體中文。只輸出簡短條列文字，勿 JSON。"""
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

        user_prompt = f"""{topic_text}
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
- 若此議題與法規/標準無直接對應，仍請以領域專家角度簡要說明最佳實務、業界常見做法或技術/風險建議；切勿留空或僅輸出 JSON 結構
- 依你的立場投票（vote）：agreed 表示可達成共識；unresolved 表示仍有衝突需升級
- statement、open_questions 的 question 請使用繁體中文

輸出 JSON:
{{{{
    "statement": "針對此議題的完整發言內容（含法規依據與風險說明）",
    "vote": "agreed 或 unresolved",
    "open_questions": [{{{{"to": "目標 agent 名稱", "question": "問題"}}}}]
}}}}"""

        messages = self.build_direct_messages(user_prompt)
        response = self.chat_for_topic_response(messages)
        statement = (response.get("statement") or "").strip()

        # 若仍為空（例如模型只回 JSON 殼、或議題非純法規導致拒答），用簡短重試強制產出內容
        if not statement:
            fallback_prompt = (
                f"{topic_text}\n\n"
                "請以領域專家身份，用 2～4 句話簡要說明你對上述議題的專業看法（可含法規、最佳實務、技術建議或風險提醒）。勿留空，直接輸出繁體中文內容。"
            )
            fallback_messages = self.build_direct_messages(fallback_prompt)
            try:
                raw_fallback = self.model.chat(fallback_messages)
                statement = (raw_fallback or "").strip()
                if len(statement) > 2000:
                    statement = statement[:2000] + "…"
            except Exception as e:
                self.logger.warning("expert 簡短重試失敗: %s", e)
                statement = "（依目前資訊暫無法提供具體法規依據，建議會後再查證後補充分享。）"

        return {
            "agent": self.name,
            "statement": statement,
            "vote": response.get("vote", "unresolved"),
            "open_questions": response.get("open_questions", []),
        }
