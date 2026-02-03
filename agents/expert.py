import logging
import json
import PyPDF2

from typing import Dict, List
from pathlib import Path

# 領域專家
class ExpertAgent:

    system_prompt = "你是領域專家，任務是提供專業的建議產業標準、法規和最佳實踐。"

    def __init__(self, model, doc_dir: str = "doc", enable_web_search: bool = True):
        self.model = model
        self.doc_dir = Path(doc_dir)
        self.doc_dir.mkdir(exist_ok=True)
        self.enable_web_search = enable_web_search
        self.logger = logging.getLogger("Plant.ExpertAgent")

    # 載入 doc 資料夾中的外部文件
    def load_external_docs(self) -> List[Dict[str, str]]:
        docs = []

        # 支援的文件格式
        text_formats = [".txt", ".md", ".json"]

        if not self.doc_dir.exists():
            return docs

        for file_path in self.doc_dir.iterdir():
            if not file_path.is_file():
                continue

            try:
                content = None

                # 處理文字格式
                if file_path.suffix in text_formats:
                    with open(file_path, "r", encoding="utf-8") as f:
                        content = f.read()

                # 處理 PDF
                elif file_path.suffix == ".pdf":
                    try:
                        with open(file_path, "rb") as f:
                            pdf_reader = PyPDF2.PdfReader(f)
                            content = ""
                            for page in pdf_reader.pages:
                                content += page.extract_text() + "\n"
                        print(f"✓ 載入 PDF: {file_path.name}")
                    except Exception as e:
                        print(f"⚠️  無法讀取 PDF {file_path.name}: {str(e)}")
                        continue

                # 處理 Word 文件
                elif file_path.suffix in [".docx", ".doc"]:
                    try:
                        from docx import Document

                        doc = Document(file_path)
                        content = "\n".join([para.text for para in doc.paragraphs])
                        print(f"✓ 載入 Word: {file_path.name}")
                    except Exception as e:
                        print(f"⚠️  無法讀取 Word {file_path.name}: {str(e)}")
                        continue

                if content:
                    docs.append(
                        {
                            "filename": file_path.name,
                            "content": content,
                            "type": file_path.suffix[1:],  # 去掉點號
                        }
                    )

            except Exception as e:
                print(f"⚠️  無法載入文件 {file_path.name}: {str(e)}")

        return docs

    # 判斷是否應該使用網路搜索
    def use_web_search(self, external_docs: List[Dict]) -> bool:
        # 如果沒有啟用網路搜索，返回 False
        if not self.enable_web_search:
            return False
        
        # 如果沒有外部文件，自動啟用網路搜索
        if not external_docs:
            return True
        
        return False

    # 提供專家建議
    def provide_feedback(
        self, conflicts: List[Dict], rough_idea: str
    ) -> List[Dict]:
        # 載入外部文件
        external_docs = self.load_external_docs()

        # 判斷是否使用網路搜索
        use_web_search = self.use_web_search(external_docs)

        # 準備文件上下文
        doc_context = ""
        if external_docs:
            doc_context = "參考文件:"
            for doc in external_docs:
                doc_context += f"{doc['filename']}\n{doc['content']}"
        elif use_web_search:
            doc_context = ""

        # 衝突報告上下文
        if conflicts:
            conflict_lines = []
            for c in conflicts:
                conflict_lines.append(f"{c.get('id', 'N/A')}: {c.get('title', 'N/A')}")
                conflict_lines.append(f"描述: {c.get('description', 'N/A')}")
            conflict_text = ",".join(conflict_lines)
        else:
            conflict_text = "沒有衝突"

        # 根據是否使用網路搜索調整提示詞
        search_instruction = ""
        if use_web_search:
            search_instruction = f"""根據粗略想法: {rough_idea} 和衝突報告: {conflict_text} 提供專業的建議。
在 "ref" 欄位中，請提供可供查證的參考來源(必須是有效的網址)，例如: 官方文件網址(如 RFC、IEEE 標準、政府法規網站)、業界最佳實踐指南等"""

        user_prompt = f"""{f'根據外部文件提供專業建議，{doc_context}' if external_docs else ""}
{search_instruction}

請以 JSON 格式回應：
{{{{
"feedback": [
    {{{{
    "id": "FB-01",
    "text": ["意見1", "意見2", "..."],
    "ref": ["參考來源：有效網址或外部文件名稱"]
    }}}},
    {{{{
    "id": "FB-XX",
    "text": ["意見X", "意見Y", "..."],
    "ref": ["參考來源：有效網址或外部文件名稱"]
    }}}}...(依此類推，一個參考來源對應一個或數個意見。)
]
}}}}"""
        response = self.model.generate_json(user_prompt, self.system_prompt)
        feedback_list = response.get("feedback", [])

        # 驗證格式
        for fb in feedback_list:
            if not all(key in fb for key in ["id", "text", "ref"]):
                raise ValueError(f"專家建議格式錯誤: {fb}")
            if not isinstance(fb["text"], list):
                fb["text"] = [fb["text"]]
            if not isinstance(fb["ref"], list):
                fb["ref"] = [fb["ref"]] if fb["ref"] else []

        # 顯示資訊來源
        if external_docs:
            print(f"✓ 已參考 {len(external_docs)} 份外部文件")
        elif use_web_search:
            print(f"✓ 已啟用網路搜索模式")
        else:
            print(f"⚠️  未提供外部文件且網路搜索已停用")

        return feedback_list

    # 第二輪以上，原有基礎上繼續精煉專家建議
    def refine_feedback(
        self,
        conflicts: List[Dict],
        previous_feedback: List[Dict],
        additional_ideas: List[Dict] = None,
    ) -> List[Dict]:
        # 載入外部文件
        external_docs = self.load_external_docs()

        # 判斷是否使用網路搜索
        use_web_search = self.use_web_search(external_docs)

        # 準備文件上下文
        doc_context = ""
        if external_docs:
            doc_context = "參考文件:"
            for doc in external_docs:
                doc_context += f"{doc['filename']}\n{doc['content']}"
        elif use_web_search:
            doc_context = ""

        # 衝突報告上下文
        if conflicts:
            conflict_lines = []
            for c in conflicts:
                conflict_lines.append(f"{c.get('id', 'N/A')}: {c.get('title', 'N/A')}")
                conflict_lines.append(f"描述: {c.get('description', 'N/A')}")
            conflict_text = ",".join(conflict_lines)
        else:
            conflict_text = "沒有衝突"

        # 根據是否使用網路搜索調整提示詞
        search_instruction = ""
        if use_web_search:
            search_instruction = f"""根據額外想法: {additional_ideas} 和衝突報告: {conflict_text} 提供專業的建議。
在 "ref" 欄位中，請提供可供查證的參考來源(必須是有效的網址)，例如: 官方文件網址(如 RFC、IEEE 標準、政府法規網站)、業界最佳實踐指南等
                """

        feedback_text = json.dumps(previous_feedback, ensure_ascii=False, indent=2)

        user_prompt = f"""先前的專家建議：
                    {feedback_text}
                    
                    {f'根據外部文件提供專業建議，{doc_context}' if external_docs else ""}
{search_instruction}

注意一個網址和外部文件對應一個或數個意見，不要重複。

請執行以下任務：
1. **回應額外想法**：如果有人類提出的額外想法，請針對這些想法提供專業建議：
    - 可行性評估
    - 潛在風險與挑戰
    - 相關的法規與標準
    - 實作建議
2. **精煉原有建議**：根據新資訊優化、補充原有的專家建議
3. **提出新建議**：在原有建議的基礎上，繼續提出新的專業意見，例如：
    - 針對新發現的風險點
    - 更深入的技術建議
    - 新的最佳實踐
    - 額外的合規性考量
                    
請保留並優化原有建議的 ID，新建議使用新的 ID。

輸出 JSON:
{{{{
"feedback": [
    {{{{
    "id": "FB-01",
    "text": ["精煉後的原有意見", "補充說明"],
    "ref": ["參考來源：有效網址或外部文件名稱"]
    }}}},
    {{{{
    "id": "FB-XX",
    "text": ["新的專業意見"],
    "ref": ["參考來源：有效網址或文件名稱"]
    }}}}
]
}}}}"""
        try:
            response = self.model.generate_json(user_prompt, self.system_prompt)

            # 顯示資訊來源
            if external_docs:
                print(f"✓ 已參考 {len(external_docs)} 份外部文件")
            elif use_web_search:
                print(f"✓ 已啟用網路搜索模式")

            return response.get("feedback", previous_feedback)
        except Exception as e:
            self.logger.error(f"Expert 建議失敗: {e}")
            return previous_feedback
