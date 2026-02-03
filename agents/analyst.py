from typing import Dict, List, Any

import itertools
import json


# 分析師代理
class AnalystAgent:
    """
    - 對利害關係人需求做衝突分析
    - 產出衝突報告(report.md)、需求草稿(draft.json)
    """

    system_prompt = """你是一位系統分析師，負責進行需求分析與需求衝突檢測。

    你的任務包括：
    - 從利害關係人發言中整理候選需求
    - 分析需求的意圖與類型
    - 偵測並描述需求之間的潛在衝突

    請注意：
    - 你不得解決或裁決衝突
    - 你不得引入新的需求
    - 你不得套用領域規則（需交由專家）
    """

    def __init__(self, model):
        self.model = model

    # 對利害關係人需求進行衝突分析（支援多人組合）
    def analyze_groups(self, stakeholders: List[Dict]) -> List[Dict]:
        groups = []

        # 生成 2 人以上的所有組合
        for size in range(2, len(stakeholders) + 1):
            for combo in itertools.combinations(stakeholders, size):
                group_analysis = self.analyze_conflict(list(combo))
                groups.append(group_analysis)

        return groups

    # 衝突分析（支援多人）
    def analyze_conflict(self, stakeholder_group: List[Dict]) -> Dict:
        # 建立利害關係人發言列表
        stakeholder_texts = "\n\n".join(
            [
                f"利害關係人 {sh['name']} ({sh['id']}):\n{sh['text']}"
                for sh in stakeholder_group
            ]
        )

        user_prompt = f"""請針對以下利害關係人的發言進行需求分析與衝突辨識。

        {stakeholder_texts}

        請輸出：
        1. 候選需求
        2. 偵測到的需求衝突（若有，標記 Conflict，若無，標記 Neutral，請說明判斷理由）

        請以 JSON 格式回應：
        {{{{
        "candidates": [{{"id": "R-01", "text": "需求描述", "source": ["stakeholders_id"]}}],
        "label": "Conflict" or "Neutral",
        "reason": "判斷理由"
        }}}}"""

        response = self.model.generate_json(user_prompt, self.system_prompt)

        return {
            "stakeholder_ids": [sh["id"] for sh in stakeholder_group],
            "stakeholder_names": [sh["name"] for sh in stakeholder_group],
            "texts": {sh["id"]: sh["text"] for sh in stakeholder_group},
            "candidates": response.get("candidates"),
            "label": response.get("label"),
            "reason": response.get("reason"),
        }

    # 過濾衝突組合（僅返回標記為 Conflict 的）
    def filter_conflicts(self, groups: List[Dict]) -> List[Dict]:
        """過濾並返回有衝突的組合"""
        return [g for g in groups if g["label"] == "Conflict"]

    # 產生需求草稿
    def generate_draft(
        self, artifact: Dict[str, Any], draft_template: Dict[str, Any]
    ) -> Dict[str, Any]:
        artifact_text = json.dumps(artifact, ensure_ascii=False, indent=2)
        template_text = json.dumps(draft_template, ensure_ascii=False, indent=2)

        prompt = f"""請根據以下 artifact 資訊產生需求草稿（Draft）：

                Artifact：
                {artifact_text}

                草稿格式範本：
                {template_text}

                請按照範本結構產生完整的需求草稿，將 artifact 中的資訊對應到範本中。

                請以 JSON 格式回應，遵循範本結構。"""

        try:
            draft = self.model.generate_json(prompt, self.system_prompt)
            return draft
        except Exception as e:
            raise RuntimeError(f"Analyst 產生草稿失敗: {str(e)}")
