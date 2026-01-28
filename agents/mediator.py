from typing import Dict, List, Any
import json

class MediatorAgent:
    """
    Mediator Agent: 雜事代理
        - 產生利害關係人建議
        - 產生決策選項供人類裁決
        - 將 artifact.json 轉為 draft.json
    """
    
    stakeholder_system_prompt = "你是需求工程專家，擅長根據初始的想法，寫成系統概述，之後識別該系統的利害關係人。"

    def __init__(self, model):
        self.model = model
    
    # 產生利害關係人建議
    def propose_stakeholders(self, system_description: str) -> List[str]:
        user_prompt = f"""根據以下系統概述，建議 5-8 位可能的利害關係人(核心使用者優先考慮，再來考慮系統所有者與管理者與外部相關單位)，附上選擇理由。
        
                系統概述：{system_description}

                請以 JSON 格式回應：
                {{{{
                "proposed_stakeholders": [
                "利害關係人名稱，選擇理由: 理由"
                ]
                }}}}"""
        
        response = self.model.generate_json(user_prompt, self.stakeholder_system_prompt)
        return response.get("proposed_stakeholders", [])
    
    # 產生系統概述
    def generate_system_description(self, rough_idea: str) -> str:
        user_prompt = f"根據初始想法: {rough_idea}，產生一個清晰的系統概述，用 2-3 段文字描述系統的主要目的、範圍和關鍵功能。"
        
        try:
            return self.model.generate(user_prompt, self.stakeholder_system_prompt)
        except Exception as e:
            raise RuntimeError(f"MediatorAgent 產生系統概述失敗，原因: {str(e)}")
    
    # 產生決策選項
    def generate_decision_options(
        self,
        conflicts: List[Dict],
        feedback: List[Dict]
    ) -> List[Dict]:
        """
        根據衝突報告和專家建議，產生決策選項
        
        Args:
            conflicts: 衝突報告列表
            feedback: 專家建議列表
        
        Returns:
            List[Dict]: 決策選項列表，每個包含 conflict_id, options, recommendation
        """
        decision_options = []
        
        for conflict in conflicts:
            option = self._generate_single_decision(conflict, feedback)
            decision_options.append(option)
        
        return decision_options
    
    # 為單一衝突產生決策選項
    def _generate_single_decision(
        self,
        conflict: Dict,
        feedback: List[Dict]
    ) -> Dict:
        # 準備專家建議
        feedback_text = "\n".join([
            f"- {fb['id']}: {'; '.join(fb['text'])}"
            for fb in feedback
        ])

        decision_system_prompt = "你是需求調解專家,擅長根據衝突報告提供決策建議。"
        user_prompt = f"""衝突 {conflict['id']}: {conflict['title']}
        
                涉及利害關係人: {', '.join(conflict['stakeholder_name'])}

                衝突描述:
                {conflict['description']}

                可能的解決方案:
                {chr(10).join(f'{i}. {sol}' for i, sol in enumerate(conflict['solutions'], 1))}

                專家建議:
                {feedback_text}

                請為這個衝突整理出清晰的決策選項,並提供建議。

                請以 JSON 格式回應：
                {{{{
                "options": ["選項A: ...", "選項B: ...", "選項C: ..."],
                "recommendation": "建議選擇哪個選項及理由"
                }}}}"""
        
        response = self.model.generate_json(user_prompt, decision_system_prompt)
        return {
            "conflict_id": conflict['id'],
            "conflict_title": conflict['title'],
            "options": response.get("options"),
            "recommendation": response.get("recommendation")
        }
    
    # 產生需求草稿
    def generate_draft(
        self,
        artifact: Dict[str, Any],
        draft_template: Dict[str, Any]
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
            draft = self.model.generate_json(prompt)
            return draft
        except Exception as e:
            raise RuntimeError(f"MediatorAgent 產生草稿失敗: {str(e)}")
