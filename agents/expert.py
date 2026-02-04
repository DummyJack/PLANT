import logging
import json
import PyPDF2

from typing import Dict, List
from pathlib import Path

# 領域專家
class ExpertAgent:

    system_prompt = """你是 Expert Agent（領域專家），你的角色是「提供非拘束性的專業建議（advisory decision support）」，而不是裁決需求或自動做決策。

你的核心任務是：
- 協助人類理解需求衝突可能涉及的專業風險、法規、標準與最佳實務
- 以「可查證的證據」支撐你的建議
- 提供決策參考，而非強制結論

=== 核心原則（必須遵守） ===

1) Advisory only（僅提供建議）
- 你不得裁決需求是否正確或可接受
- 你不得否決任何需求
- 你的所有輸出都必須以「建議」「可能」「應考量」等語氣呈現

2) Evidence-first（證據優先）
- 你只能根據以下來源提供建議：
  a) 系統提供的外部文件內容（doc/ 資料夾）
  b) 或經明確指示允許的、可查證的公開來源
- 你不得捏造或臆測不存在的標準、法規或規範
- 若缺乏足夠證據，你必須明確說明「資訊不足」

3) Traceable references（可追蹤引用）
- 每一條專業建議都必須對應至少一個可查證的參考來源
- 參考來源必須是「具體內容頁面」，而非首頁、入口頁或索引頁
- 參考來源必須能直接支持你所提出的建議內容
- 若無可靠來源，請不要提供該建議

4) No fabricated web knowledge（禁止虛構網路內容）
- 你不得假設自己「已經查詢過網路」
- 你不得生成看似合理但實際不存在或無法驗證的網址
- 若系統未提供實際查詢結果，你只能：
  - 提出「需要查證的主張」
  - 或說明目前無法提供具證據的建議

5) Conflict-aware but non-judgmental（理解衝突，但不裁決）
- 你應理解需求衝突的背景與影響
- 但你不得選擇衝突解法或偏向任何利害關係人
- 你的角色是「風險揭露與選項輔助」

=== 建議輸出要求 ===

- 建議內容應清楚說明：
  - 建議本身
  - 適用範圍與前提條件
  - 可能帶來的效益
  - 潛在成本或風險
- 所有建議必須附上對應的參考來源（文件名稱或具體網址）
- 若資訊不足，請列出需要補充或查證的問題，而非猜測

請始終記住：
你是「專業顧問」，不是「裁決者」。
你的價值來自於可查證的知識與清楚的風險說明，而不是結論本身。"""

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

        # 衝突報告上下文
        if conflicts:
            conflict_lines = []
            for c in conflicts:
                conflict_lines.append(f"{c.get('id', 'N/A')}: {c.get('title', 'N/A')}")
                conflict_lines.append(f"描述: {c.get('description', 'N/A')}")
            conflict_text = ",".join(conflict_lines)
        else:
            conflict_text = "沒有衝突"

        # 準備外部文件說明
        external_docs_text = ""
        if external_docs:
            external_docs_text = f"""
以下內容來自系統提供的外部文件，請僅依據其內容提出建議，並在 ref 中標示對應的文件名稱：
{doc_context}
"""
        
        # 準備網路搜尋說明
        web_search_text = ""
        if use_web_search:
            web_search_text = """請僅在你能提出「具體且可查證的內容頁面」時，才引用公開來源。若無可靠可查證來源，請明確標示「資訊不足」，不要勉強提供建議或網址。
"""
        
        user_prompt = f"""提供「非拘束性的專家建議」。
背景資訊:
- 粗略想法: {rough_idea}
- 已識別的需求衝突摘要:
{conflict_text}
{external_docs_text}
{web_search_text}

任務:
1. 針對上述需求衝突，提供專業層面的「風險、考量事項或最佳實務建議」。
2. 所有建議必須是「非強制性、非裁決性」的（僅供人類決策參考）。
3. 不要替人類選擇解法，也不要否定需求本身。
4. 若資訊不足以形成可靠建議，請直接說明「資訊不足」與原因。

參考來源規則:
- 每一組建議必須附上對應的 ref。
- ref 可以是：
  a) 系統提供的外部文件名稱；或
  b) 「具體內容頁面」的公開網址（不是首頁、入口頁或索引頁）。
- ref 中的內容必須能直接支持你提出的建議。
- 若找不到符合上述條件的來源，請在 ref 中填寫「資訊不足」。

輸出 JSON:
{{{{
  "feedback": [
    {{{{
      "id": "FB-01",
      "text": [
        "具體、可理解的專業建議或風險說明",
        "（如有需要，可補充第二點）"
      ],
      "ref": [
        "外部文件名稱 或 具體內容頁面網址 或 資訊不足"
      ]
    }}}}
    // 可重複多組 feedback
  ]
}}}}
"""
        # 顯示資訊來源
        if external_docs:
            print(f"✓ 已參考 {len(external_docs)} 份外部文件")
        elif use_web_search:
            print(f"✓ 已啟用網路搜索模式")

        response = self.model.generate_json(user_prompt, self.system_prompt, temperature=1)
        
        feedback_list = response.get("feedback", [])

        # 驗證格式
        for fb in feedback_list:
            if not all(key in fb for key in ["id", "text", "ref"]):
                raise ValueError(f"專家建議格式錯誤: {fb}")
            if not isinstance(fb["text"], list):
                fb["text"] = [fb["text"]]
            if not isinstance(fb["ref"], list):
                fb["ref"] = [fb["ref"]] if fb["ref"] else []

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

        # 衝突報告上下文
        if conflicts:
            conflict_lines = []
            for c in conflicts:
                conflict_lines.append(f"{c.get('id', 'N/A')}: {c.get('title', 'N/A')}")
                conflict_lines.append(f"描述: {c.get('description', 'N/A')}")
            conflict_text = ",".join(conflict_lines)
        else:
            conflict_text = "沒有衝突"

        feedback_text = json.dumps(previous_feedback, ensure_ascii=False, indent=2)
        
        # 準備外部文件說明
        external_docs_text = ""
        if external_docs:
            external_docs_text = f"""
以下內容來自系統提供的外部文件，請以此為主要依據提出/修正建議，並在 ref 中標示對應文件名稱：
{doc_context}
"""
        
        # 準備網路搜尋說明
        web_search_text = ""
        if use_web_search:
            web_search_text = """請僅在你能提出「具體且可查證的內容頁面」時，才引用公開來源。若無可靠可查證來源，請在 ref 中填寫「資訊不足」，不要勉強提供網址。
"""

        user_prompt = f"""
進行「第二輪（含後續輪次）的專家建議精煉」。提供「非拘束性建議」：不裁決、不否決、不替人類做決策。

先前的專家建議:
{feedback_text}

已識別的需求衝突摘要:
{conflict_text}
{external_docs_text}
{web_search_text}

任務(保持精簡、可追蹤):

1) 回應額外想法（若有）：
- 評估可行性、風險與挑戰
- 提供實作建議或注意事項（非裁決）
- 若需要法規/標準支撐，必須有可查證來源，否則標示資訊不足

2) 精煉原有建議：
- 修正不清楚、不可驗證、或缺乏證據支撐的表述
- 將過度武斷的語氣改為 advisory 語氣（建議/應考量/可能）
- 盡量合併重複建議，避免碎片化

3) 提出新建議（可選）：
- 僅在確有必要時新增（例如：新風險、補充最佳實務、或針對新想法的專業提醒）
- 新增建議請使用新的 id（例如 FB-XX）

參考來源規則:
- 一個 ref（文件名稱或網址）可以對應多條 text，但不要重複塞相同 ref
- ref 可以是：
  a) 外部文件名稱（doc/中的檔名）；或
  b) 「具體內容頁面」的公開網址（不是首頁、入口頁、索引頁）
- ref 必須能直接支持你提出的建議；若做不到，請填「資訊不足」
- 不要假裝你已經查過網路；若沒有可查證來源，就說資訊不足

輸出 JSON:

{{
  "feedback": [
    {{
      "id": "FB-01",
      "text": ["精煉後的原有意見（可多點）"],
      "ref": ["外部文件名稱 或 具體內容頁面網址 或 資訊不足"]
    }},
    {{
      "id": "FB-XX",
      "text": ["新增的專業意見"],
      "ref": ["外部文件名稱 或 具體內容頁面網址 或 資訊不足"]
    }}
  ]
}}
"""
        try:
            # 顯示資訊來源
            if external_docs:
                print(f"✓ 已參考 {len(external_docs)} 份外部文件")
            elif use_web_search:
                print(f"✓ 已啟用網路搜索模式")

            response = self.model.generate_json(user_prompt, self.system_promt, temperature=1)

            return response.get("feedback", previous_feedback)
        except Exception as e:
            self.logger.error(f"Expert 建議失敗: {e}")
            return previous_feedback
