# Defines action prompts and output contracts.


# ========
# Defines suggest candidates function for this module workflow.
# ========
def suggest_stakeholders(*, scenario_context: str) -> str:
    return f"""# 任務
根據以下產品情境，建議真正會影響需求分析的利害關係人。

# 產品情境
{scenario_context}

- primary_user：每天直接操作系統、輸入資料、接收通知或完成任務的人。
- system_owner：負責派工、監督流程、營運決策、權限、資料品質、系統穩定性、安全或維護的人。
- external_party：外部會影響或受影響的單位。

- 保留上述三類分類，但不要為了湊滿分類或人數而產生不必要角色。
- 至少輸出 2 位利害關係人；沒有明確 external_party 時可以不輸出該類。
- 每位利害關係人必須直接存在於產品情境中，且會影響需求、限制、責任邊界、驗收或風險判斷。
- 每位利害關係人的使用情境與責任邊界要明確且不同。
- 避免使用情境重疊；若兩個角色需求視角幾乎相同，合併成一位即可。
- 輸出順序：primary_user → system_owner → external_party。
- name 只填名稱，不要用括號補充說明。
- type 只能是 primary_user、system_owner、external_party。
- reason 用一句話說明此角色為什麼需要納入需求分析。

{{
    "proposed_stakeholders": [
        {{"name": "利害關係人名稱", "type": "primary_user | system_owner | external_party", "reason": "一句話選擇理由"}}
    ]
}}"""


# ========
# Defines write stakeholder text function for this module workflow.
# ========
def write_stakeholder_text(
    *,
    stakeholder_list: str,
    scenario_context: str,
) -> str:
    return f"""# 任務
模擬以下利害關係人，以第一人稱、口語方式從各自角度提出需求。

# 利害關係人
{stakeholder_list}

# 產品情境
{scenario_context}

1. 日常使用情境
2. 痛點與困擾
3. 期望功能
4. 擔心的事
5. 最在意的限制、底線或不可接受情況
6. 與其他角色可能產生取捨的地方

- 每位利害關係人產生 3-5 條 text。
- 只根據該利害關係人的日常經驗。
- 不替未選中的角色發言。
- 每條 text 都必須能回扣產品情境。
- 請自然描述該角色的目標、擔憂、限制、底線與可接受/不可接受的取捨。
- 不要刻意製造衝突；只有在產品情境中合理時，才描述可能與其他角色目標拉扯的地方。

{{
    "stakeholders": [
        {{
            "name": "利害關係人名稱",
            "text": ["第一人稱需求發言"]
        }}
    ]
}}"""
