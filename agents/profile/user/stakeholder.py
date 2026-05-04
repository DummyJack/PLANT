# User stakeholder helpers: derive stakeholder roles and initial requirements.
from typing import Dict, List

from agents.base import user_requirement_cards, user_stakeholder_name_reason


class UserStakeholder:
    def propose_stakeholders(self, rough_idea: str) -> List[str]:
        user_prompt = f"""# 任務
根據初始想法: {rough_idea}，建議 5-8 位可能相關的利害關係人。

# 選擇優先順序
1. 核心使用者（直接使用系統的人）
2. 系統擁有者與管理者
3. 外部相關單位

# 約束
- 每位利害關係人須有明確且不同的角色職責
- 每位利害關係人必須直接存在於初始想法描述的產品情境中；不要加入和此產品無關的泛用企業角色
- 避免角色重疊
- name 只填名稱，不要用括號補充說明
- reason 選擇理由用一句話即可
- {user_stakeholder_name_reason()}

# 輸出 JSON
{{{{
    "proposed_stakeholders": [
        {{{{"name": "利害關係人名稱", "reason": "一句話選擇理由"}}}}
    ]
}}}}"""

        messages = self.build_direct_messages(user_prompt)
        response = self.chat_json(messages, temperature=1)
        return response.get("proposed_stakeholders", [])

    def generate_stakeholder_requirements(
        self, rough_idea: str, selected_stakeholders: List[str]
    ) -> List[Dict]:
        stakeholder_list = ", ".join(
            f"{i+1}. {sh}" for i, sh in enumerate(selected_stakeholders)
        )

        user_prompt = f"""# 任務
模擬以下利害關係人，以第一人稱、口語方式從各自的角度提出需求與期望。

# 利害關係人
{stakeholder_list}

# 背景（僅供參考）
{rough_idea}

# 發言指引
每位利害關係人請依以下面向發言：
1. 日常使用情境 — 你平常怎麼使用這個系統
2. 痛點與困擾 — 目前最讓你困擾的問題是什麼
3. 期望功能 — 你最希望系統能做到什麼
4. 擔心的事 — 你對這個系統有什麼顧慮

# 約束
- 每位利害關係人提出 3-5 條獨立需求（text 陣列）
- 以該角色的日常經驗出發
- 每條需求都必須直接扣回背景中的產品情境；不得把產品轉向其他系統或未列出的利害關係人場景
- 不得替未被選中的角色發言，也不得新增不在「利害關係人」清單中的角色
- {user_requirement_cards()}

# 輸出 JSON
{{{{
    "stakeholders": [
        {{{{
            "name": "利害關係人名稱",
            "text": ["發言1", "發言2", "發言3", ...]
        }}}}
    ]
}}}}"""

        try:
            messages = self.build_direct_messages(user_prompt)
            response = self.chat_json(messages, temperature=1)
            stakeholders = response.get("stakeholders", [])

            for sh in stakeholders:
                if not all(key in sh for key in ["name", "text"]):
                    raise ValueError(f"利害關係人格式錯誤: {sh}")
                if isinstance(sh["text"], str):
                    sh["text"] = [
                        s.strip() for s in sh["text"].split("\n") if s.strip()
                    ]
                if len(sh["text"]) < 3:
                    self.logger.warning(
                        f"{sh['name']} 只有 {len(sh['text'])} 條需求，不足 3 條"
                    )

            return stakeholders
        except Exception as e:
            raise RuntimeError(f"User 生成失敗: {e}")
