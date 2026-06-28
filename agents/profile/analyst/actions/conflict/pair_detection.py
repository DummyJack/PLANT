# Defines action prompts and output contracts.
import json

def pair_detection(
    *,
    base_task: str,
    heading: str,
    rules: str,
    rows_label: str,
    pair_rows: list,
) -> str:
    return f"""{base_task}

# {heading}
- 本步處理指定 pair_rows。
- 每筆輸出必須可由 pair_index 對回輸入 pair。
- Output key 使用 conflicts，語意是「所有輸入 pair 的分類結果」。
- conflicts array 必須逐筆涵蓋所有輸入 pair_rows；即使 final_label 是 Neutral 也必須輸出。
{rules}

# Input
{rows_label}:
{json.dumps(pair_rows, ensure_ascii=False, indent=2)}

# Output JSON
{{
  "conflicts": [
    {{
      "pair_index": 0,
      "final_label": "Conflict",
      "final_type": "scope",
      "reason": "一句繁中判斷理由"
    }},
    {{
      "pair_index": 1,
      "final_label": "Neutral",
      "reason": "一句繁中判斷理由"
    }}
  ]
}}

# Output Contract
- 輸出 JSON object。
- conflicts 必須是 array，且長度必須等於輸入 pair_rows 數量。
- 每筆必須包含 pair_index、final_label、reason。
- pair_index 必須使用輸入 pair_rows 中的原始數字。
- final_label 只能是 "Conflict" 或 "Neutral"。
- final_label 是 "Conflict" 時必須包含 final_type。
- final_label 是 "Neutral" 時包含 pair_index、final_label、reason。"""
