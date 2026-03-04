import json
import logging
import os
import PyPDF2

from typing import Dict, List, Optional
from pathlib import Path

from openai import BadRequestError
from agents.base import BaseAgent
from agents.tools.web_search import WebSearchTool


class ExpertAgent(BaseAgent):
    """領域專家 Agent — 領域知識注入、法規/標準/安全規範約束"""

    name = "expert"

    system_prompt = """你是領域專家，負責注入必須遵守的法規、標準、安全規範。

核心原則：
1. Evidence-first — 只根據外部文件或 web_search 結果提供建議，禁止捏造
2. Traceable — 每條建議須附可查證的來源（URL 或文件名），嚴禁虛構 URL
3. 拘束性約束 — 注入的法規/標準/安全規範標記為 constraint
4. 無證據不建議 — 若無法找到支持證據，明確標註「資訊不足」
5. 衝突敏感 — 若注入的約束與現有需求產生衝突，必須標記
6. 詳盡說明 — 每條約束必須包含具體條文內容、適用範圍、合規要求的詳細描述"""

    def __init__(self, model, tools: Optional[list] = None, registry=None,
                 doc_dir: str = "doc", enable_web_search: bool = True):
        agent_tools = list(tools or [])

        if enable_web_search:
            tavily_key = os.getenv("TAVILY_API_KEY")
            if tavily_key:
                agent_tools.append(WebSearchTool(api_key=tavily_key))
            else:
                logging.getLogger("Plant.ExpertAgent").warning("TAVILY_API_KEY 未設定")

        super().__init__(model, tools=agent_tools, registry=registry)
        self.doc_dir = Path(doc_dir)
        self.doc_dir.mkdir(exist_ok=True)
        self.enable_web_search = enable_web_search

    def load_external_docs(self) -> List[Dict[str, str]]:
        docs = []
        text_formats = [".txt", ".md", ".json"]

        if not self.doc_dir.exists():
            return docs

        for file_path in self.doc_dir.iterdir():
            if not file_path.is_file():
                continue
            try:
                content = None
                if file_path.suffix in text_formats:
                    with open(file_path, "r", encoding="utf-8") as f:
                        content = f.read()
                elif file_path.suffix == ".pdf":
                    try:
                        with open(file_path, "rb") as f:
                            pdf_reader = PyPDF2.PdfReader(f)
                            content = "".join(page.extract_text() + "\n" for page in pdf_reader.pages)
                    except Exception as e:
                        print(f"無法讀取 PDF {file_path.name}: {e}")
                        continue
                elif file_path.suffix in [".docx", ".doc"]:
                    try:
                        from docx import Document
                        doc = Document(file_path)
                        content = "\n".join(para.text for para in doc.paragraphs)
                    except Exception as e:
                        print(f"無法讀取 Word {file_path.name}: {e}")
                        continue

                if content:
                    docs.append({"filename": file_path.name, "content": content, "type": file_path.suffix[1:]})
            except Exception as e:
                print(f"無法載入文件 {file_path.name}: {e}")

        return docs

    def build_doc_context(self, external_docs: List[Dict]) -> str:
        if not external_docs:
            return ""
        parts = ["\n# 外部參考文件"]
        for doc in external_docs:
            parts.append(f"\n【{doc['filename']}】\n{doc['content']}")
        return "\n".join(parts)

    @staticmethod
    def _parse_first_json(raw: str) -> Dict:
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

    def _build_inject_fallback_prompt(self, requirements: List[Dict], rough_idea: str) -> str:
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
        """Phase 0: 領域知識注入。查詢網頁時僅搜尋與「專案概述」相關的法規/標準/安全規範。"""
        external_docs = self.load_external_docs()
        doc_context = self.build_doc_context(external_docs)

        if external_docs:
            print(f"✓ 已參考 {len(external_docs)} 份外部文件")

        requirements_text = json.dumps(requirements, ensure_ascii=False, indent=2)
        conflicts_text = json.dumps(conflicts, ensure_ascii=False, indent=2)

        overview = (project_overview or "").strip()
        scope_constraint = ""
        if overview:
            scope_constraint = f"\n# 查詢範圍約束\n使用 web_search 時，僅搜尋與以下「專案概述」相關的法規/標準/安全規範。\n專案概述：\n{overview}\n勿搜尋與本專案無關的內容。\n"

        has_tools = bool(self.tools)
        tool_instruction = (
            "請使用 web_search 搜尋相關法規、標準、安全規範（必須至少搜尋一次）"
            if has_tools else
            "根據已提供的文件和你的專業知識提供建議"
        )

        user_prompt = f"""# 任務
審查以下需求，注入必須遵守的法規/標準/安全規範作為 constraint 類型的需求。

# 背景
{rough_idea}
{scope_constraint}
# 當前需求
{requirements_text}

# 當前衝突
{conflicts_text}
{doc_context}

# 步驟
1. {tool_instruction}
2. 識別必須遵守的法規、標準、安全規範
3. 將這些約束寫入 new_requirements（type 標記為 constraint）
（衝突辨識由 Analyst 在注入後統一執行，Expert 僅產出 new_requirements）

# 詳細度要求
每條 constraint 的 text 必須包含：
- 法規/標準的全名與條文編號
- 具體的合規要求描述（不可只寫「需遵守 XXX 法規」）
- 適用範圍（此約束影響系統的哪些面向）
- 不合規的風險或後果

# 約束
- 每條 constraint 須附 ref（來源 URL 或文件名）
- 嚴禁虛構 URL 或法規名稱
- 若無相關法規，new_requirements 可為空陣列

# 輸出 JSON
{{{{
    "new_requirements": [
        {{{{
            "id": "R-C01",
            "text": "詳細的約束描述（包含法規全名、條文、合規要求、適用範圍、風險）",
            "type": "constraint",
            "ref": "來源 URL 或文件名",
            "source_stakeholders": ["expert"]
        }}}}
    ]
}}}}"""

        messages = self.build_direct_messages(user_prompt)

        try:
            if self.tools:
                raw = self.chat_with_tools(messages, max_rounds=3)
                response = self._parse_first_json(raw)
            else:
                response = self.model.chat_json(messages)
        except BadRequestError as e:
            err_msg = str(e).lower()
            if "invalid_prompt" in err_msg or "usage policy" in err_msg:
                self.logger.warning("Expert 請求觸發內容政策，改以精簡 prompt 僅依模型知識產出約束")
                fallback_prompt = self._build_inject_fallback_prompt(requirements, rough_idea)
                response = self.model.chat_json(self.build_direct_messages(fallback_prompt))
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
                reasons.append("未設定 TAVILY_API_KEY 或無 web_search 工具")
            if reasons:
                self.logger.info(f"Expert 回傳 0 條約束，可能原因：{'、'.join(reasons)}；或模型判斷無適用法規／解析未取得 new_requirements")
            else:
                self.logger.info("Expert 回傳 0 條約束，可能為模型判斷本專案無適用法規/標準，或輸出格式未含 new_requirements")

        return {"requirements": requirements + new_reqs}

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
            tool_hint = "\n# 工具使用\n- 可先使用 web_search 查詢法規、標準或技術文件，再根據結果撰寫發言。\n- 最後**必須**輸出下列 JSON。"

        user_prompt = f"""你正在以領域專家的身份參與需求討論。

{topic_text}
{prev_text}
{snapshot_text}
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

輸出 JSON:
{{{{
    "statement": "針對此議題的完整發言內容（含法規依據與風險說明）",
    "open_questions": [{{{{"to": "目標 agent 名稱", "question": "問題"}}}}]
}}}}"""

        messages = self.build_direct_messages(user_prompt)
        response = self._chat_for_topic_response(messages)

        return {
            "agent": self.name,
            "statement": response.get("statement", ""),
            "open_questions": response.get("open_questions", []),
        }
