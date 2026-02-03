from typing import Dict, List, Optional
from pathlib import Path

import logging
import json
import PyPDF2


# 領域專家
class ExpertAgent:
    """
    - 根據外部文件提供專業建議，支援格式：.txt, .md, .json, .pdf, .docx, .doc
    - 搜尋網路資源提供專業意見（可插拔式）
    """

    system_prompt = "你是領域專家，可以使用外部文件，若系統允許，也可使用 web search。若工具不可用，請忽略該能力。你提供限制、風險與可驗證條件，而不是功能設計。最佳實務僅能作為風險或建議，不得轉寫為強制性需求。"

    def __init__(self, model, doc_dir: str = "doc", enable_web_search: bool = True):
        self.model = model
        self.doc_dir = Path(doc_dir)
        self.doc_dir.mkdir(exist_ok=True)
        self.enable_web_search = enable_web_search
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

    def _should_use_web_search(self, external_docs: List[Dict]) -> bool:
        """判斷是否應該使用網路搜索"""
        # 如果沒有啟用網路搜索，返回 False
        if not self.enable_web_search:
            return False
        
        # 如果沒有外部文件，自動啟用網路搜索
        if not external_docs:
            return True
        
        return False

    # 提供專家建議
    def provide_feedback(
        self, system_description: str, conflicts: List[Dict]
    ) -> List[Dict]:
        # 載入外部文件
        external_docs = self._load_external_docs()

        # 判斷是否使用網路搜索
        use_web_search = self._should_use_web_search(external_docs)

        # 準備文件上下文
        doc_context = ""
        if external_docs:
            doc_context = "\n\n參考文件：\n"
            for doc in external_docs:
                doc_context += f"\n【{doc['filename']}】\n{doc['content'][:500]}...\n"
        elif use_web_search:
            doc_context = "\n\n注意：由於沒有外部文件，請根據網路上可查證的資料提供建議。"

        # 準備衝突上下文
        conflict_text = (
            "\n".join([f"- {c['id']}: {c['title']}" for c in conflicts])
            if conflicts
            else "無明顯衝突"
        )

        # 根據是否使用網路搜索調整提示詞
        search_instruction = ""
        if use_web_search:
            search_instruction = """
                **重要**：由於沒有提供外部文件，請基於你所知的產業標準、法規和最佳實踐提供建議。
                在 "ref" 欄位中，請提供可供查證的參考來源，例如：
                - 官方文件網址（如 RFC、IEEE 標準、政府法規網站）
                - 權威技術文件（如 OWASP、NIST、ISO 標準）
                - 業界最佳實踐指南
                
                **所有參考來源必須是有效的網址或標準文件名稱**，例如：
                - https://www.owasp.org/index.php/XXX
                - RFC 2616
                - ISO/IEC 27001
                - GDPR Article 5
                """

        user_prompt = f"""系統概述：{system_description}

                識別出的衝突：
                {conflict_text}
                
                {doc_context}

                根據{'外部文件' if external_docs else '產業知識'}提供專業意見：
                1. 法規與合規性（資料保護、隱私權、產業標準等）
                2. 資料安全（加密、存取控制、稽核等）
                3. 系統效能（可擴展性、回應時間、容錯等）
                4. 可維護性與可測試性
                5. 使用者體驗
                
                {search_instruction}

                請以 JSON 格式回應：
                {{{{
                "feedback": [
                    {{{{
                    "id": "FB-01",
                    "text": ["意見1", "意見2"],
                    "ref": ["參考來源：文件名稱或有效網址"]
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

        # 顯示資訊來源
        if external_docs:
            print(f"\n✓ 已參考 {len(external_docs)} 份外部文件")
        elif use_web_search:
            print(f"\n✓ 已啟用網路搜索模式（基於產業知識提供建議）")
        else:
            print(f"\n⚠️  未提供外部文件且網路搜索已停用")

        return feedback_list

    # 第二輪以上，原有基礎上繼續精煉專家建議
    def refine_feedback(
        self,
        previous_feedback: List[Dict],
    ) -> List[Dict]:
        # 載入外部文件
        external_docs = self._load_external_docs()

        # 判斷是否使用網路搜索
        use_web_search = self._should_use_web_search(external_docs)

        # 準備文件上下文
        doc_context = ""
        if external_docs:
            doc_context = "\n\n參考文件：\n"
            for doc in external_docs:
                doc_context += f"\n【{doc['filename']}】\n{doc['content'][:500]}...\n"
        elif use_web_search:
            doc_context = "\n\n注意：由於沒有外部文件，請根據網路上可查證的資料提供建議。"

        # 根據是否使用網路搜索調整提示詞
        search_instruction = ""
        if use_web_search:
            search_instruction = """
                **重要**：請基於產業標準、法規和最佳實踐提供建議。
                在 "ref" 欄位中，請提供可供查證的參考來源（有效網址或標準文件名稱）。
                """

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
                    
                    {search_instruction}

                    請以 JSON 格式回應：
                    {{{{
                    "feedback": [
                        {{{{
                        "id": "FB-01",
                        "text": ["精煉後的原有意見", "補充說明"],
                        "ref": ["參考來源：有效網址或文件名稱"]
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
                print(f"\n✓ 已參考 {len(external_docs)} 份外部文件")
            elif use_web_search:
                print(f"\n✓ 已啟用網路搜索模式（基於產業知識提供建議）")

            return response.get("feedback", previous_feedback)
        except Exception as e:
            self.logger.error(f"Expert 建議失敗: {e}")
            return previous_feedback
