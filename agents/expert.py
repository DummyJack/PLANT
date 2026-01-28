from typing import Dict, List
import json
from pathlib import Path
import logging

class ExpertAgent:
    """
    Expert Agent: 領域專家
        - 根據外部文件提供專業建議
        - 支援 RAG（檢索增強生成）
        - 支援文件格式：.txt, .md, .json, .pdf, .docx, .doc
        - 提供制度法規、資料安全與系統效能等領域建議
    """
    
    system_prompt = "你是領域專家，擅長透過外部文件提供專業意見。"
    
    def __init__(self, model, doc_dir: str = "doc"):
        self.model = model
        self.doc_dir = Path(doc_dir)
        self.doc_dir.mkdir(exist_ok=True)
        self.logger = logging.getLogger("Plant.ExpertAgent")
        
    def _load_external_docs(self) -> List[Dict[str, str]]:
        """載入 doc 資料夾中的外部文件"""
        docs = []
        
        # 支援的文件格式
        text_formats = ['.txt', '.md', '.json']
        
        if not self.doc_dir.exists():
            return docs
        
        for file_path in self.doc_dir.iterdir():
            if not file_path.is_file():
                continue
            
            try:
                content = None
                
                # 處理文字格式
                if file_path.suffix in text_formats:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        content = f.read()
                
                # 處理 PDF
                elif file_path.suffix == '.pdf':
                    try:
                        import PyPDF2
                        with open(file_path, 'rb') as f:
                            pdf_reader = PyPDF2.PdfReader(f)
                            content = ""
                            for page in pdf_reader.pages:
                                content += page.extract_text() + "\n"
                        print(f"✓ 載入 PDF: {file_path.name}")
                    except ImportError:
                        print(f"⚠️  需要安裝 PyPDF2 才能讀取 PDF 檔案")
                        print(f"   執行: pip install PyPDF2")
                        continue
                    except Exception as e:
                        print(f"⚠️  無法讀取 PDF {file_path.name}: {str(e)}")
                        continue
                
                # 處理 Word 文件
                elif file_path.suffix in ['.docx', '.doc']:
                    try:
                        from docx import Document
                        doc = Document(file_path)
                        content = "\n".join([para.text for para in doc.paragraphs])
                        print(f"✓ 載入 Word: {file_path.name}")
                    except ImportError:
                        print(f"⚠️  需要安裝 python-docx 才能讀取 Word 檔案")
                        print(f"   執行: pip install python-docx")
                        continue
                    except Exception as e:
                        print(f"⚠️  無法讀取 Word {file_path.name}: {str(e)}")
                        continue
                
                if content:
                    docs.append({
                        "filename": file_path.name,
                        "content": content,
                        "type": file_path.suffix[1:]  # 去掉點號
                    })
                    
            except Exception as e:
                print(f"⚠️  無法載入文件 {file_path.name}: {str(e)}")
        
        return docs
    
    
    def provide_feedback(
        self,
        system_description: str,
        conflicts: List[Dict]
    ) -> List[Dict]:
        """
        提供專家建議（使用 RAG）
        
        Args:
            system_description: 系統概述
            stakeholders: 利害關係人列表
            conflicts: 衝突報告列表
        
        Returns:
            List[Dict]: 專家建議列表，每個包含 id, text (List), ref (List)
        """
        # 載入外部文件（RAG）
        external_docs = self._load_external_docs()
        
        # 準備文件上下文
        doc_context = ""
        if external_docs:
            doc_context = "\n\n參考文件：\n"
            for doc in external_docs:
                doc_context += f"\n【{doc['filename']}】\n{doc['content'][:500]}...\n"
        
        # 準備衝突上下文
        conflict_text = "\n".join([
            f"- {c['id']}: {c['title']}"
            for c in conflicts
        ]) if conflicts else "無明顯衝突"
        
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
    
    def refine_feedback(
        self,
        previous_feedback: List[Dict],
    ) -> List[Dict]:
        """
        根據新資訊精煉專家建議（多輪時使用，支援外部文件）
        
        Args:
            previous_feedback: 先前的專家建議
        
        Returns:
            List[Dict]: 更新後的專家建議
        """
        # 載入外部文件（RAG）
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

                    請根據新資訊和參考文件，更新或補充專家建議。

                    請以 JSON 格式回應：
                    {{{{
                    "feedback": [
                        {{{{
                        "id": "FB-XX",
                        "text": ["意見1", "意見2"],
                        "ref": ["參考來源：文件名稱"]
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
            self.logger.error(f"精煉專家建議失敗: {e}")
            return previous_feedback
