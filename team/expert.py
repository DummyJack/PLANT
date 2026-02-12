import json
import logging
import os
import PyPDF2

from typing import Dict, List, Optional
from pathlib import Path

from agents.base import BaseAgent
from agents.memory import Memory
from agents.tools.web_search import WebSearchTool


class ExpertAgent(BaseAgent):
    """領域專家 Agent — Tool Use (WebSearch) + ReAct + Reflection"""

    name = "expert"

    system_prompt = """你是領域專家（Expert Agent），提供基於客觀證據的專業建議。

你的建議分為兩類：
1. 非拘束性建議（binding=false）— 一般性的專業建議、風險提醒、最佳實務參考
2. 拘束性建議（binding=true）— 僅限法規強制要求、安全硬性限制、技術不可行約束

核心原則：
1. Evidence-first — 只根據外部文件或 web_search 結果提供建議，禁止捏造
2. Traceable — 每條建議須附可查證的來源（URL 或文件名），嚴禁虛構 URL
3. binding 門檻 — binding=true 僅限「法規 / 安全 / 技術硬性限制」，必須附 reason
4. 無證據不建議 — 若無法找到支持證據，明確標註「資訊不足」，不得臆測
5. 裁決角色 — 討論無法達成共識時，可基於客觀證據提供拘束性裁決"""

    reflection_criteria = "每條建議必須有可查證的參考來源（URL 或文件名），禁止虛構。binding=true 的建議必須附明確的法規或技術依據。"

    def __init__(self, model, tools: Optional[list] = None,
                 memory: Optional[Memory] = None, registry=None,
                 doc_dir: str = "doc", enable_web_search: bool = True):
        agent_tools = list(tools or [])

        if enable_web_search:
            tavily_key = os.getenv("TAVILY_API_KEY")
            if tavily_key:
                agent_tools.append(WebSearchTool(api_key=tavily_key))
            else:
                logging.getLogger("Plant.ExpertAgent").warning("TAVILY_API_KEY 未設定")

        super().__init__(model, tools=agent_tools, memory=memory, registry=registry)
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
- 每條建議的 text 可以有多條，用 list 表示
- binding=true 必須附 reason（法規條文或技術限制說明）"""

    # 提供專家建議

    def provide_feedback(self, conflicts: List[Dict], rough_idea: str) -> List[Dict]:
        external_docs = self.load_external_docs()
        doc_context = self.build_doc_context(external_docs)
        conflict_text = self.build_conflict_text(conflicts)

        if external_docs:
            print(f"✓ 已參考 {len(external_docs)} 份外部文件")

        self.memory.clear_short_term()
        has_tools = bool(self.tools)

        extra = f"# 任務\n針對以下需求衝突，提供專家建議。\n\n背景: {rough_idea}"
        base_prompt = self.build_feedback_prompt(conflict_text, doc_context, has_tools, extra)

        if has_tools:
            task = f"""{base_prompt}

輸出格式（action=respond 的 output 中）:
{{
    "action": "respond",
    "output": {{
        "feedback": [
            {{"id": "FB-01", "binding": false, "text": ["建議內容"], "ref": ["URL"], "reason": "原因"}}
        ]
    }}
}}"""
            result = self.run(task, max_steps=3, min_tool_uses=1)
        else:
            task = f"""{base_prompt}

輸出 JSON:
{{
    "feedback": [
        {{"id": "FB-01", "binding": false, "text": ["建議內容"], "ref": ["來源"], "reason": "原因"}}
    ]
}}"""
            result = self.direct_generate(task, output_format="json")

        return self.extract_feedback(result)

    # 拘束性裁決

    def provide_binding_ruling(self, topic: Dict, contributions: List[Dict]) -> Dict:
        self.memory.clear_short_term()

        discussion_text = ""
        for c in contributions:
            agent = c.get("agent", "?")
            resp = c.get("response", {})
            content = resp.get("content", resp.get("position", json.dumps(resp, ensure_ascii=False)))
            discussion_text += f"\n【{agent}】\n{content}\n"

        has_tools = bool(self.tools)

        ruling_prompt = f"""# 任務
對以下無法達成共識的議題提供拘束性專業裁決。

# 議題
標題: {topic.get('title', '')}
描述: {topic.get('description', '')}

# 各方討論
{discussion_text}

# 裁決原則
- 裁決必須基於客觀證據（法規、標準、技術限制）
- 若無客觀依據支持裁決，必須回傳 resolved=false
- 禁止基於主觀偏好做出裁決"""

        if has_tools:
            task = f"""{ruling_prompt}

# 步驟
1. 使用 web_search 搜尋相關法規、標準
2. 判斷是否有客觀依據做出裁決
3. 輸出裁決（無依據則 resolved=false）

輸出格式（action=respond 的 output 中）:
{{
    "action": "respond",
    "output": {{
        "resolved": true/false,
        "ruling": "裁決內容",
        "binding_advice": [{{"text": "...", "ref": "URL", "reason": "依據"}}],
        "resolution": "agreed/partial",
        "summary": "摘要",
        "decision": "決策"
    }}
}}"""
            result = self.run(task, max_steps=3, min_tool_uses=1)
        else:
            task = f"""{ruling_prompt}

輸出 JSON:
{{
    "resolved": true/false,
    "ruling": "裁決內容",
    "binding_advice": [{{"text": "...", "ref": "來源", "reason": "依據"}}],
    "resolution": "agreed/partial",
    "summary": "摘要",
    "decision": "決策"
}}"""
            result = self.direct_generate(task, output_format="json")

        if not isinstance(result, dict):
            result = {}

        return {
            "resolved": result.get("resolved", False),
            "ruling": result.get("ruling", ""),
            "binding_advice": result.get("binding_advice", []),
            "resolution": result.get("resolution", "partial"),
            "summary": result.get("summary", ""),
            "decision": result.get("decision", ""),
        }

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
            task = f"""你正在以領域專家的身份參與需求討論。請先搜尋相關資訊再回應。

{topic_text}
{prev_text}

# 步驟
1. 使用 web_search 搜尋與議題相關的法規、標準、最佳實務
2. 根據搜尋結果提供專業意見

輸出格式（action=respond 的 output 中）:
{{
    "action": "respond",
    "output": {{
        "position": "基於[來源]，我認為...",
        "arguments": ["論點1（附來源）", "論點2"],
        "suggestions": ["建議1", "建議2"]
    }}
}}"""
            self.memory.add("user", f"回應議題: {topic.get('title', '')[:50]}")
            result = self.run(task, max_steps=3, min_tool_uses=1)

            if not isinstance(result, dict):
                result = {}

            return {
                "agent": self.name,
                "position": result.get("position", ""),
                "arguments": result.get("arguments", []),
                "suggestions": result.get("suggestions", []),
            }
        else:
            user_prompt = f"""你正在以領域專家的身份參與需求討論。

{topic_text}
{prev_text}

# 回應要求
1. position: 基於法規、標準或技術可行性的專業立場
2. arguments: 有客觀依據的論點（標明來源或註明「資訊不足」）
3. suggestions: 符合法規/標準的具體建議

# 約束
- 論點必須有客觀依據，無依據則標註「資訊不足」
- 禁止虛構法規或標準名稱

輸出 JSON:
{{{{
    "position": "基於...標準，我認為...",
    "arguments": ["論點1", "論點2"],
    "suggestions": ["建議1", "建議2"]
}}}}"""

            self.memory.add("user", f"回應議題: {topic.get('title', '')[:50]}")
            messages = self.build_direct_messages(user_prompt)
            response = self.model.chat_json(messages)

            return {
                "agent": self.name,
                "position": response.get("position", ""),
                "arguments": response.get("arguments", []),
                "suggestions": response.get("suggestions", []),
            }

    def extract_feedback(self, result) -> List[Dict]:
        if isinstance(result, dict):
            # 直接取 feedback，或從 ReAct 巢狀格式 {output: {feedback: [...]}} 取
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
            if not isinstance(fb["ref"], list):
                fb["ref"] = [fb["ref"]] if fb["ref"] else []
            fb.setdefault("binding", False)
            fb.setdefault("reason", "")
            validated.append(fb)

        return validated
