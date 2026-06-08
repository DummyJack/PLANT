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
- 本步只處理指定 pair_rows。
- 不新增 pair、不重新分組、不輸出 group conflict。
- 每筆輸出必須可由 pair_index 對回輸入 pair。
{rules}

# Input
{rows_label}:
{json.dumps(pair_rows, ensure_ascii=False, indent=2)}

# Output JSON
{{"conflicts":[...]}}

# Forbidden Output
- 不輸出 Markdown 說明。
- 不輸出 resolution options。
- 不輸出 group conflict。
- 不新增輸入 pair_rows 以外的 pair。
- 不新增、改寫、刪除 URL 或 REQ。
- 不輸出舊格式或 conflicts 以外的 wrapper。"""
