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
    
    # 收集人類選擇的利害關係人
    def collect_stakeholder_selection(self, proposed: List[str]) -> List[str]:
        """
        收集人類選擇的利害關係人
        
        Args:
            proposed: 建議的利害關係人列表
        
        Returns:
            List[str]: 人類選擇的利害關係人
        """
        while True:
            print("\n建議的利害關係人：")
            for i, sh in enumerate(proposed, 1):
                print(f"{i}. {sh}")
            
            user_input = input("\n請選擇利害關係人(最多選擇 5 位，輸入編號，用逗號分隔，例如：1,3,5)：").strip()
            
            try:
                # 解析輸入
                selected_indices = [int(x.strip()) - 1 for x in user_input.split(',')]
                
                # 驗證編號是否有效
                invalid_indices = [i+1 for i in selected_indices if i < 0 or i >= len(proposed)]
                if invalid_indices:
                    print(f"\n❌ 錯誤：編號 {invalid_indices} 無效,請重新選擇")
                    continue
                
                # 取得選擇的利害關係人
                selected = [proposed[i] for i in selected_indices]
                
                # 驗證數量
                if len(selected) > 5:
                    print(f"\n⚠️  錯誤：選擇超過 5 個（已選 {len(selected)} 個）,請重新選擇")
                    continue
                
                if len(selected) == 0:
                    print(f"\n❌ 錯誤：至少需要選擇 1 個利害關係人,請重新選擇")
                    continue
                
                return selected
                
            except ValueError:
                print(f"\n❌ 錯誤：輸入格式不正確,請使用逗號分隔的數字（例如：1,3,5）")
                continue
    
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
    
    def _generate_single_decision(
        self,
        conflict: Dict,
        feedback: List[Dict]
    ) -> Dict:
        """為單一衝突產生決策選項"""
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
    
    # 收集人類決策
    def collect_human_decision(self, decision_option: Dict) -> Dict:
        """
        收集人類對單一衝突的決策
        
        Args:
            decision_option: 決策選項
        
        Returns:
            Dict: 包含 conflict_id, decision, rationale
        """
        print(f"\n衝突：{decision_option['conflict_title']}")
        print(f"\n選項：")
        for i, opt in enumerate(decision_option['options'], 1):
            print(f"{i}. {opt}")
        
        print(f"\n建議：{decision_option['recommendation']}")
        print("\n請選擇方案（輸入編號，或輸入 'skip' 跳過）：")
        
        user_input = input("> ").strip()
        
        if user_input.lower() == 'skip':
            return {
                "conflict_id": decision_option['conflict_id'],
                "decision": "跳過決策",
                "rationale": "人類選擇暫不處理此衝突"
            }
        
        try:
            choice_idx = int(user_input) - 1
            if 0 <= choice_idx < len(decision_option['options']):
                chosen = decision_option['options'][choice_idx]
                
                print("\n請說明選擇理由（可選，直接按 Enter 跳過）：")
                rationale = input("> ").strip()
                
                return {
                    "conflict_id": decision_option['conflict_id'],
                    "decision": chosen,
                    "rationale": rationale if rationale else "人類選擇此方案"
                }
            else:
                print("無效的選項，預設跳過")
                return {
                    "conflict_id": decision_option['conflict_id'],
                    "decision": "跳過決策",
                    "rationale": "無效輸入"
                }
        except ValueError:
            print("無效的輸入，預設跳過")
            return {
                "conflict_id": decision_option['conflict_id'],
                "decision": "跳過決策",
                "rationale": "無效輸入"
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
