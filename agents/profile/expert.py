import json
import logging
import os
import PyPDF2

from typing import Dict, List, Optional
from pathlib import Path

from agents.base import BaseAgent
from agents.tools.web_search import WebSearchTool


class ExpertAgent(BaseAgent):
    name = "expert"

    system_prompt = """你是領域專家，提供基於客觀證據的專業建議。

你的建議分為兩類：
1. 非拘束性建議（binding=false）— 一般性的專業建議、風險提醒、最佳實務參考
2. 拘束性建議（binding=true）— 僅限法規強制要求、安全硬性限制、技術不可行約束

核心原則：
1. Evidence-first — 只根據外部文件或 web_search 結果提供建議，禁止捏造
2. Traceable — 每條建議須附可查證的來源（URL 或文件名），嚴禁虛構 URL
3. binding 門檻 — binding=true 僅限「法規 / 安全 / 技術硬性限制」
4. 無證據不建議 — 若無法找到支持證據，明確標註「資訊不足」，不得臆測
5. 來源分組 — 同一來源（同一 URL 或文件）的多條建議應合併在同一筆 feedback"""

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

    def build_conflict_text(self, conflicts: List[Dict]) -> str:
        if not conflicts:
            return "目前沒有已識別的衝突。"
        lines = []
        for c in conflicts:
            lines.append(f"- {c.get('id', 'N/A')}: {c.get('title', 'N/A')}")
            lines.append(f"  描述: {c.get('description', 'N/A')}")
            stakeholders = c.get('stakeholder_names', [])
            if stakeholders:
                lines.append(f"  涉及: {', '.join(stakeholders)}")
        return "\n".join(lines)

    def build_doc_context(self, external_docs: List[Dict]) -> str:
        if not external_docs:
            return ""
        parts = ["\n# 外部參考文件"]
        for doc in external_docs:
            content = doc['content'][:2000] + "\n... (截斷)" if len(doc['content']) > 2000 else doc['content']
            parts.append(f"\n【{doc['filename']}】\n{content}")
        return "\n".join(parts)

    def build_feedback_prompt(self, conflict_text: str, doc_context: str,
                               has_tools: bool, extra_context: str = "") -> str:
        """統一的建議 prompt 模板"""
        tool_instruction = ""
        ref_instruction = ""

        if has_tools:
            tool_instruction = """# 步驟
1. 使用 web_search 搜尋相關法規、標準、最佳實務（必須至少搜尋一次）
2. 根據搜尋結果編寫建議（ref 必須來自真實搜尋結果的 URL）
3. 輸出最終回應"""
            ref_instruction = "ref 必須是真實 URL，來自 web_search 結果"
        else:
            tool_instruction = """# 注意
目前無搜尋工具。ref 填寫已提供的文件名稱，若無相關文件則填「資訊不足」。嚴禁虛構 URL。"""
            ref_instruction = "ref 填文件名稱或「資訊不足」"

        return f"""{extra_context}
# 衝突摘要
{conflict_text}
{doc_context}

{tool_instruction}

# binding 判斷標準
- binding=true: 僅限法規強制要求 / 安全硬性限制 / 技術不可行
- binding=false: 其他所有建議

# 約束
- {ref_instruction}
- 每筆 feedback 的 ref 是單一來源（一個 URL 或文件名）
- 同一來源產生的多條建議，全部寫在同一筆的 text 陣列中
- 不同來源的建議分成不同筆 feedback"""

    # 提供專家建議

    def provide_feedback(self, conflicts: List[Dict], rough_idea: str) -> List[Dict]:
        external_docs = self.load_external_docs()
        doc_context = self.build_doc_context(external_docs)
        conflict_text = self.build_conflict_text(conflicts)

        if external_docs:
            print(f"✓ 已參考 {len(external_docs)} 份外部文件")

        has_tools = bool(self.tools)

        extra = f"# 任務\n針對以下需求衝突，提供專家建議。\n\n背景: {rough_idea}"
        base_prompt = self.build_feedback_prompt(conflict_text, doc_context, has_tools, extra)

        if has_tools:
            task = f"""{base_prompt}

輸出 JSON:
{{
    "feedback": [
        {{"id": "FB-01", "binding": false, "ref": "URL 或來源名稱", "text": ["從此來源得出的建議1", "建議2"]}}
    ]
}}"""
            messages = self.build_direct_messages(task)
            result = self.model.chat_json(messages)
        else:
            task = f"""{base_prompt}

輸出 JSON:
{{
    "feedback": [
        {{"id": "FB-01", "binding": false, "ref": "來源名稱或URL", "text": ["從此來源得出的建議1", "建議2"]}}
    ]
}}"""
            messages = self.build_direct_messages(task)
            result = self.model.chat_json(messages)

        return self.extract_feedback(result)

    # 覆寫：議題討論回應
    def respond_to_topic(self, topic, previous_responses=None):
        """從法規/標準/技術可行性角度回應議題，若有工具則先搜尋"""
        topic_text = f"議題 [{topic.get('id', '')}]: {topic.get('title', '')}\n描述: {topic.get('description', '')}"

        prev_text = ""
        if previous_responses:
            parts = []
            for r in previous_responses:
                agent = r.get("agent", "?")
                resp = r.get("response", {})
                content = resp.get("content", resp.get("position", ""))
                parts.append(f"【{agent}】{content}")
            prev_text = "\n前面的發言:\n" + "\n".join(parts)

        has_tools = bool(self.tools)

        if has_tools:
            task = f"""你正在以領域專家的身份參與需求討論。請根據你的專業知識回應（可參考法規、標準、最佳實務）。

{topic_text}
{prev_text}

# 回應要求
1. position: 基於法規、標準或技術可行性的專業立場
2. arguments: 有客觀依據的論點（標明來源或註明「資訊不足」）
3. suggestions: 符合法規/標準的具體建議
4. questions_to_others: 想請其他角色（user/analyst）回答的問題

輸出 JSON:
{{{{
    "position": "基於...標準，我認為...",
    "arguments": ["論點1", "論點2"],
    "suggestions": ["建議1", "建議2"],
    "questions_to_others": [{{{{"to": "agent名稱", "question": "問題"}}}}]
}}}}"""
            messages = self.build_direct_messages(task)
            result = self.model.chat_json(messages)

            if not isinstance(result, dict):
                result = {}

            return {
                "agent": self.name,
                "position": result.get("position", ""),
                "arguments": result.get("arguments", []),
                "suggestions": result.get("suggestions", []),
                "questions_to_others": result.get("questions_to_others", []),
            }
        else:
            user_prompt = f"""你正在以領域專家的身份參與需求討論。

{topic_text}
{prev_text}

# 回應要求
1. position: 基於法規、標準或技術可行性的專業立場
2. arguments: 有客觀依據的論點（標明來源或註明「資訊不足」）
3. suggestions: 符合法規/標準的具體建議
4. questions_to_others: 想請其他角色（user/analyst）回答的問題

# 約束
- 論點必須有客觀依據，無依據則標註「資訊不足」
- 禁止虛構法規或標準名稱

輸出 JSON:
{{{{
    "position": "基於...標準，我認為...",
    "arguments": ["論點1", "論點2"],
    "suggestions": ["建議1", "建議2"],
    "questions_to_others": [{{{{"to": "agent名稱", "question": "問題"}}}}]
}}}}"""

            messages = self.build_direct_messages(user_prompt)
            response = self.model.chat_json(messages)

            return {
                "agent": self.name,
                "position": response.get("position", ""),
                "arguments": response.get("arguments", []),
                "suggestions": response.get("suggestions", []),
                "questions_to_others": response.get("questions_to_others", []),
            }

    def extract_feedback(self, result) -> List[Dict]:
        if isinstance(result, dict):
            feedback_list = result.get("feedback", [])
            if not feedback_list and "output" in result:
                output = result["output"]
                if isinstance(output, dict):
                    feedback_list = output.get("feedback", [])
        elif isinstance(result, list):
            feedback_list = result
        else:
            feedback_list = []

        validated = []
        for fb in feedback_list:
            if not isinstance(fb, dict):
                continue
            if not all(key in fb for key in ["id", "text", "ref"]):
                continue
            if not isinstance(fb["text"], list):
                fb["text"] = [fb["text"]]
            # ref 為單一字串（一個來源）
            if isinstance(fb["ref"], list):
                fb["ref"] = fb["ref"][0] if fb["ref"] else ""
            fb.setdefault("binding", False)
            validated.append(fb)

        return validated
