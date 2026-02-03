from typing import Dict, List
from pathlib import Path

import logging
import json
import PyPDF2


# 領域專家
class ExpertAgent:
    """
    - 根據外部文件提供專業建議，支援格式：.txt, .md, .json, .pdf, .docx, .doc
    - 搜尋網路資源提供專業意見
    """

    system_prompt = """你是一位領域專家，熟悉該系統所屬產業的流程、規範與實務限制。

                    你的任務是：
                    - 驗證候選需求是否符合領域知識
                    - 指出隱含的領域限制、法規或業界慣例
                    - 修正不合理或不可行的需求理解
                    - 補充必要但未被明確說出的領域規則

                    請注意：
                    - 不要主動提出新的功能需求
                    - 不要將需求改寫成規格書語言"""

    def __init__(self, model, doc_dir: str = "doc"):
        self.model = model
        self.doc_dir = Path(doc_dir)
        self.doc_dir.mkdir(exist_ok=True)
        self.logger = logging.getLogger("Plant.ExpertAgent")

    def _load_external_docs(self) -> List[Dict[str, str]]:
        """載入 doc 資料夾中的外部文件"""
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

    # 提供專家建議
    def provide_feedback(
        self, system_description: str, conflicts: List[Dict]
    ) -> List[Dict]:
        # 載入外部文件
        external_docs = self._load_external_docs()

        # 準備文件上下文
        doc_context = ""
        if external_docs:
            doc_context = "\n\n參考文件：\n"
            for doc in external_docs:
                doc_context += f"\n【{doc['filename']}】\n{doc['content'][:500]}...\n"

        # 準備衝突上下文
        conflict_text = (
            "\n".join([f"- {c['id']}: {c['title']}" for c in conflicts])
            if conflicts
            else "無明顯衝突"
        )

        user_prompt = f"""系統概述：{system_description}

                識別出的衝突：
                {conflict_text}
                
                {doc_context}

                根據外部文件提供專業意見：
                1. 法規與合規性（資料保護、隱私權、產業標準等）
                2. 資料安全（加密、存取控制、稽核等）
                3. 系統效能（可擴展性、回應時間、容錯等）
                4. 可維護性與可測試性
                5. 使用者體驗

                請結合上述參考文件，提供具體且有依據的建議。

                請以 JSON 格式回應：
                {{{{
                "feedback": [
                    {{{{
                    "id": "FB-01",
                    "text": ["意見1", "意見2"],
                    "ref": ["參考來源：文件名稱或網路連結"]
                    }}}}
                ]
                }}}}
                """

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

        # 添加文件來源信息
        if external_docs:
            print(f"\n✓ 已參考 {len(external_docs)} 份外部文件")

        return feedback_list

    # 第二輪以上，原有基礎上繼續精煉專家建議
    def refine_feedback(
        self,
        previous_feedback: List[Dict],
    ) -> List[Dict]:
        # 載入外部文件
        external_docs = self._load_external_docs()

        # 準備文件上下文
        doc_context = ""
        if external_docs:
            doc_context = "\n\n參考文件：\n"
            for doc in external_docs:
                doc_context += f"\n【{doc['filename']}】\n{doc['content'][:500]}...\n"

        feedback_text = json.dumps(previous_feedback, ensure_ascii=False, indent=2)

        user_prompt = f"""先前的專家建議：
                    {feedback_text}
                    
                    {doc_context}

                    請執行兩個任務：
                    1. **精煉原有建議**：根據新資訊優化、補充原有的專家建議
                    2. **提出新建議**：在原有建議的基礎上，繼續提出新的專業意見，例如：
                       - 針對新發現的風險點
                       - 更深入的技術建議
                       - 新的最佳實踐
                       - 額外的合規性考量
                    
                    請保留並優化原有建議的 ID，新建議使用新的 ID。

                    請以 JSON 格式回應：
                    {{{{
                    "feedback": [
                        {{{{
                        "id": "FB-01",
                        "text": ["精煉後的原有意見", "補充說明"],
                        "ref": ["參考來源"]
                        }}}},
                        {{{{
                        "id": "FB-XX",
                        "text": ["新的專業意見"],
                        "ref": ["參考來源"]
                        }}}}
                    ]
                    }}}}"""

        try:
            response = self.model.generate_json(user_prompt, self.system_prompt)

            # 添加文件來源信息
            if external_docs:
                print(f"\n✓ 已參考 {len(external_docs)} 份外部文件")

            return response.get("feedback", previous_feedback)
        except Exception as e:
            self.logger.error(f"Expert 建議失敗: {e}")
            return previous_feedback
