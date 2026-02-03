from typing import Dict, List

# 調解代理，協助人類
class MediatorAgent:

    system_prompt = "你是需求調解專家，任務是提供決策建議。"

    def __init__(self, model):
        self.model = model

    # 產生衝突報告
    def generate_conflict_report(self, conflict_groups: List[Dict]) -> List[Dict]:
    
        formatted_conflicts = []
        for idx, group in enumerate(conflict_groups, 1):
            conflict_text = f"{idx}. "
            
            # 顯示利害關係人的發言內容
            for stakeholder_name, text in group.get("texts", {}).items():
                conflict_text += f"{stakeholder_name}: {text}\n"
            
            # 顯示衝突理由
            conflict_text += f"衝突理由: {group.get('reason', '')}\n"
            formatted_conflicts.append(conflict_text)
        
        conflicts_text = "\n".join(formatted_conflicts)
        
        # 動態生成範例格式
        example_conflicts = []
        for idx in range(1, min(len(conflict_groups) + 1, 3)):  # 最多顯示2個範例
            example_conflicts.append(f"""{{{{
"id": "CR-{idx:02d}",
"stakeholder_names": ["利害關係人A", "利害關係人B"],
"title": "衝突標題（對應衝突組合 {idx}）",
"description": "詳細描述衝突組合 {idx} 的衝突內容",
"conflict_type": "類型 vs 類型"
}}}}""")
        
        examples_text = ",\n".join(example_conflicts)
        if len(conflict_groups) > 2:
            examples_text += ",\n...(依此類推，共 " + str(len(conflict_groups)) + " 個衝突)"
        
        user_prompt = f"""根據以下 {len(conflict_groups)} 個需求衝突分析結果，請為**每一個**衝突組合生成對應的衝突報告：
{conflicts_text}

對每個衝突組合，生成對應的衝突報告：
1. id: 衝突 ID（從 CR-01 開始編號，衝突組合 1 對應 CR-01，衝突組合 2 對應 CR-02，依此類推）
2. stakeholder_names: 涉及的利害關係人名稱列表（從上面的發言中提取）
3. title: 衝突標題（簡短概括該衝突的核心問題）
4. description: 詳細的衝突描述（基於利害關係人的發言和衝突理由）
5. conflict_type: 衝突類型（例如：效率 vs 成本、品質 vs 速度、彈性 vs 控制等）

**重要**：必須為所有 {len(conflict_groups)} 個衝突組合都生成報告！

輸出 JSON 格式:
{{{{
"conflicts": [
{examples_text}
]
}}}}"""
        response = self.model.generate_json(user_prompt)
        
        # 提取 conflicts 陣列
        if isinstance(response, dict) and "conflicts" in response:
            conflicts_list = response["conflicts"]
            return conflicts_list
        elif isinstance(response, list):
            return response
        else:
            # 如果格式不符合預期，返回空列表
            print(f"警告: 無法從回應中提取衝突列表，收到的格式: {type(response)}")
            return []

    # 產生決策選項
    def generate_decision_options(
        self, conflicts: List[Dict], feedback: List[Dict]
    ) -> List[Dict]:
        decision_options = []

        for conflict in conflicts:
            option = self.generate_decision(conflict, feedback)
            decision_options.append(option)

        return decision_options

    # 衝突產生決策選項
    def generate_decision(self, conflict: Dict, feedback: List[Dict]) -> Dict:
        conflict_text = f"""{conflict.get('id', 'N/A')}: {conflict.get('title', 'N/A')}
描述: {conflict.get('description', 'N/A')}
"""
        if feedback:
            feedback_lines = []
            for fb in feedback:
                fb_id = fb.get('id', '')
                fb_text = fb.get('text', [])
                fb_ref = fb.get('ref', [])
                
                feedback_lines.append(f"\n{fb_id}:")
                for text in fb_text:
                    feedback_lines.append(f"  • {text}")
            
            feedback_text = "\n".join(feedback_lines)
        else:
            feedback_text = "無專家建議"

        user_prompt = f"""根據已有衝突報告: {conflict_text}和已有專家建議: {feedback_text}。
請生成：
1. 至少提供 3 個決策選項，看情況增加
2. 每個選項都要包含：
   - option: 選項描述（簡潔明確）
   - rationale: 選擇該選項的理由
3. recommendation: 總體推薦，說明推薦哪個選項及為什麼

請以 JSON 格式回應：
{{{{
"options": [
    {{{{
        "option": "選項1的描述",
        "rationale": ""
    }}}},
    {{{{
        "option": "選項2的描述",
        "rationale": ""
    }}}},
    {{{{
        "option": "選項3的描述",
        "rationale": ""
    }}}}...(依此類推)
],
"recommendation": "推薦選項X，理由是..."
}}}}"""
        
        response = self.model.generate_json(user_prompt, self.system_prompt)
        
        # 轉換選項格式以符合原有介面
        options_list = []
        rationales_list = []
        for opt in response.get("options", []):
            if isinstance(opt, dict):
                options_list.append(opt.get("option", ""))
                rationales_list.append(opt.get("rationale", ""))
            else:
                # 向下兼容舊格式
                options_list.append(opt)
                rationales_list.append("")
        
        return {
            "title": conflict.get("title", "N/A"),
            "options": options_list,
            "rationales": rationales_list,
            "recommendation": response.get("recommendation", ""),
        }
