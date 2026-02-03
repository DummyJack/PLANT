import itertools
import json

from typing import Dict, List, Any

# 分析師代理
class AnalystAgent:

    system_prompt = "你是一個專業的系統分析師，任務有進行需求分析、衝突辨識和草稿產生。"

    def __init__(self, model):
        self.model = model

    # 對利害關係人需求進行衝突分析
    def analyze_groups(self, stakeholders: List[Dict]) -> List[Dict]:
        groups = []

        # 1. 兩兩分析（不產生 candidates）
        for combo in itertools.combinations(stakeholders, 2):
            group_analysis = self.analyze_conflict(list(combo), is_all_analysis=False)
            groups.append(group_analysis)

        # 2. 全部一起分析（產生 candidates）
        if len(stakeholders) > 2:
            all_analysis = self.analyze_conflict(stakeholders, is_all_analysis=True)
            groups.append(all_analysis)

        return groups

    # 衝突分析
    def analyze_conflict(self, stakeholder_group: List[Dict], is_all_analysis: bool = False) -> Dict:
        # 建立利害關係人發言列表
        stakeholder_texts = "\n\n".join(
            [
                f"{sh['name']}: {sh['text']}"
                for sh in stakeholder_group
            ]
        )

        # 根據是否為全部分析，決定是否產生候選需求
        if is_all_analysis:
            user_prompt = f"""請針對以下利害關係人的發言進行需求分析與衝突辨識。
{stakeholder_texts}

請輸出：
1. 候選需求
2. 偵測到的需求衝突（若有，標記 Conflict，若無，標記 Neutral），請說明判斷理由

輸出 JSON:
{{{{
"candidates": [{{"id": "R-01", "text": "需求描述", "source": ["stakeholder_name"]}}],
"label": "Conflict" or "Neutral",
"reason": "判斷理由"
}}}}"""
        else:
            user_prompt = f"""請針對以下利害關係人的發言進行需求衝突辨識。
{stakeholder_texts}

請輸出偵測到的需求衝突(若有衝突，標記 Conflict。反之，標記 Neutral)，並說明判斷理由

輸出 JSON:
{{{{
"label": "Conflict" or "Neutral",
"reason": "判斷理由"
}}}}"""

        response = self.model.generate_json(user_prompt, self.system_prompt)

        result = {
            "texts": {sh["name"]: sh["text"] for sh in stakeholder_group},
            "label": response.get("label"),
            "reason": response.get("reason"),
        }
        
        # 只在全部分析時加入 candidates
        if is_all_analysis:
            result["candidates"] = response.get("candidates", [])
        
        return result

    # 產生需求草稿
    def generate_draft(
        self, artifact: Dict[str, Any], draft_template: Dict[str, Any]
    ) -> Dict[str, Any]:

        selected_artifact = {
            "rough_idea": artifact.get("rough_idea", ""),
            "stakeholders": artifact.get("stakeholders", []),
            "candidates": self.extract_candidates(artifact.get("analyse", [])),
            "reports": artifact.get("report", []),
            "feedback": artifact.get("feedback", []),
            "options": artifact.get("options", []),
            "decisions": artifact.get("decisions", [])
        }

        selected_artifact_text = json.dumps(selected_artifact, ensure_ascii=False, indent=2)
        draft_template_text = json.dumps(draft_template, ensure_ascii=False, indent=2)

        user_prompt = f"""請根據以下中間產物內容產生需求草稿:
中間產物內容:
{selected_artifact_text}

重要對應關係：
1. "reports" 對應到模板中的 "4. Conflicting Requirements"
   - reports 中的 id: title, stakeholder_names, description 應映射到 Conflicting Requirements 的 id, stakeholder_name, description
   
2. "options" 中的 options 對應到 "Conflicting Requirements" 的 solutions
   - 每個衝突的決策選項 (options.options) 
   - 應轉換為該衝突的可能解決方案 (solutions)

請輸出 JSON，遵循以下結構:
draft: {draft_template_text}"""

        print(user_prompt)

        try:
            draft = self.model.generate_json(user_prompt, self.system_prompt)
            return draft
        except Exception as e:
            raise RuntimeError(f"Analyst 產生草稿失敗: {str(e)}")
    
    # 從 analyse 中提取所有 candidates
    def extract_candidates(self, analyse: list) -> list:
        all_candidates = []
        for group in analyse:
            if "candidates" in group:
                all_candidates.extend(group["candidates"])
        return all_candidates
