import json
import logging
import os
import PyPDF2

from typing import Dict, List, Optional
from pathlib import Path

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

    def inject_domain(self, requirements: List[Dict], conflicts: List[Dict], rough_idea: str) -> Dict:
        """Phase 0 Step 0.4: 領域知識注入 — 將法規/標準/安全規範寫入 requirements"""
        external_docs = self.load_external_docs()
        doc_context = self.build_doc_context(external_docs)

        if external_docs:
            print(f"✓ 已參考 {len(external_docs)} 份外部文件")

        requirements_text = json.dumps(requirements, ensure_ascii=False, indent=2)
        conflicts_text = json.dumps(conflicts, ensure_ascii=False, indent=2)

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

# 當前需求
{requirements_text}

# 當前衝突
{conflicts_text}
{doc_context}

# 步驟
1. {tool_instruction}
2. 識別必須遵守的法規、標準、安全規範
3. 將這些約束寫入 new_requirements（type 標記為 constraint）
4. 檢查新約束是否與現有需求衝突，若有則寫入 new_conflicts

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
    ],
    "new_conflicts": [
        {{{{
            "id": "CF-xx",
            "label": "Conflict",
            "description": "新約束與哪些需求產生衝突，具體矛盾點為何",
            "texts": {{{{"expert": "約束內容", "原利害關係人": "原需求內容"}}}}
        }}}}
    ]
}}}}"""

        messages = self.build_direct_messages(user_prompt)

        if self.tools:
            raw = self.chat_with_tools(messages, max_rounds=3)
            try:
                response = json.loads(raw) if isinstance(raw, str) else raw
            except json.JSONDecodeError:
                import re
                m = re.search(r"\{.*\}", raw, re.DOTALL)
                response = json.loads(m.group(0)) if m else {}
        else:
            response = self.model.chat_json(messages)

        new_reqs = response.get("new_requirements", [])
        for req in new_reqs:
            req.setdefault("type", "constraint")
            req.setdefault("source_stakeholders", ["expert"])

        new_conflicts = response.get("new_conflicts", [])
        for cf in new_conflicts:
            cf.setdefault("label", "Conflict")
            cf.setdefault("texts", {})
            cf.setdefault("source", "expert")

        return {
            "requirements": requirements + new_reqs,
            "conflicts": conflicts + new_conflicts,
        }

    def respond_to_topic(self, topic, previous_responses=None):
        topic_text = f"議題 [{topic.get('id', '')}]: {topic.get('title', '')}\n描述: {topic.get('description', '')}"

        prev_text = ""
        if previous_responses:
            parts = [f"【{r.get('agent', '?')}】\n{r.get('response', {}).get('statement', '')}"
                     for r in previous_responses]
            prev_text = "\n前面的發言:\n" + "\n\n".join(parts)

        user_prompt = f"""你正在以領域專家的身份參與需求討論。

{topic_text}
{prev_text}

# 思考與發言流程
1. 先思考：(1) 此議題相關的法規、標準或技術限制 (2) 不可讓步的要點（須附法規/標準依據）(3) 可接受調整或折衷的要點
2. 再根據思考結果，撰寫一段完整的發言（statement），針對議題提出你的專業見解與法規依據
3. 若有需要請其他角色回答的問題，列入 open_questions（to 填寫目標 agent 名稱，如 "user"、"analyst"、"modeler"）

# 約束
- statement 必須包含具體的法規依據和不合規風險，禁止虛構法規或標準名稱
- 論點必須有客觀依據，無依據則標註「資訊不足」

輸出 JSON:
{{{{
    "statement": "針對此議題的完整發言內容（含法規依據與風險說明）",
    "open_questions": [{{{{"to": "目標 agent 名稱", "question": "問題"}}}}]
}}}}"""

        messages = self.build_direct_messages(user_prompt)
        response = self.model.chat_json(messages)

        return {
            "agent": self.name,
            "statement": response.get("statement", ""),
            "open_questions": response.get("open_questions", []),
        }
