from typing import Dict, Any
from store import Store

# 系統建模者，需求草稿產生系統模型（PlantUML 程式碼、AST 結構化資料）
class ModelerAgent:

    system_prompt = "你是系統建模專家，任務根據需求草稿轉換系統模型。"

    def __init__(self, model, store):
        self.model = model
        self.store = store

    # 根據需求草稿產生系統模型
    def generate_system_model(self, draft: Dict[str, Any]) -> Dict[str, Any]:
        
        # 格式化需求草稿內容
        formatted_draft = self.store.generate_draft_markdown(draft)

        user_prompt = f"""根據以下需求草稿產生 UML 系統模型：

{formatted_draft}

請產生以下 UML 模型：

1. **Use Case Diagram（使用案例圖）**
   - 識別系統的主要參與者（Actor）：從 System Stakeholders 中提取
   - 識別主要使用案例（Use Case）：從 User Requirements 和 System Requirements 中提取
   - 定義參與者與使用案例之間的關係

2. **Class Diagram（類別圖）**
   - 識別系統的主要類別：從 System Requirements 中提取實體
   - 定義類別的屬性和方法
   - 定義類別之間的關係（關聯、繼承、組合等）

3. **Sequence Diagram（序列圖）** (選擇性)
   - 針對關鍵功能流程
   - 展示物件之間的互動順序

4. **AST 結構化資料**
   - components: 系統的主要組件
   - relationships: 組件之間的關係

輸出 JSON 格式:
{{{{
"models": [
    {{{{
    "name": "系統名稱 Use Case Diagram",
    "type": "use_case_diagram",
    "plantuml": "@startuml\\n...\\n@enduml"
    }}}},
    {{{{
    "name": "系統名稱 Class Diagram",
    "type": "class_diagram",
    "plantuml": "@startuml\\n...\\n@enduml"
    }}}}
],
"ast": {{{{
    "components": [
        {{{{
            "id": "C-01",
            "name": "組件名稱",
            "type": "entity/service/interface",
            "attributes": ["屬性1", "屬性2"],
            "methods": ["方法1", "方法2"]
        }}}}
    ],
    "relationships": [
        {{{{
            "from": "C-01",
            "to": "C-02",
            "type": "association/inheritance/dependency",
            "description": "關係描述"
        }}}}
    ]
}}}}
}}}}"""
        
        response = self.model.generate_json(user_prompt, self.system_prompt)
        return response

    # 第二輪以上，原有基礎上繼續調整模型
    def refine_model(
        self, current_model: Dict[str, Any], draft: Dict[str, Any]
    ) -> Dict[str, Any]:
        
        # 格式化需求草稿
        formatted_draft = self.store.generate_draft_markdown(draft)
        
        # 格式化當前模型
        import json
        current_model_json = json.dumps(current_model, ensure_ascii=False, indent=2)

        user_prompt = f"""## 當前系統模型（uml.json）

```json
{current_model_json}
```

## 新的需求草稿

{formatted_draft}

## 評估任務

請評估新的需求草稿，判斷是否需要調整系統模型：

### 評估步驟
1. **分析變更**：比較新需求草稿與當前模型（uml.json）
2. **識別影響**：找出哪些模型元素需要調整
3. **判斷必要性**：只在真正需要時才修改
4. **執行調整**：
   - **新增**：新的組件、類別或關係
   - **修改**：調整現有結構的屬性或行為
   - **刪除**：移除不再需要的部分

### 重要原則
- 保持模型的一致性和完整性
- 避免不必要的變動
- 如果沒有實質性的需求變更，保持原有模型不變

### 輸出 JSON 格式

{{{{
"models": [
    {{{{
    "name": "模型名稱",
    "type": "use_case_diagram/class_diagram/sequence_diagram",
    "plantuml": "@startuml\\n...\\n@enduml"
    }}}}
],
"ast": {{{{
    "components": [...],
    "relationships": [...]
}}}}
}}}}"""
        try:
            response = self.model.generate_json(user_prompt, self.system_prompt)
            return response
        except Exception as e:
            print(f"警告: 模型精煉失敗，保留原有模型。錯誤: {str(e)}")
            return current_model
    
