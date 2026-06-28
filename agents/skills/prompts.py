# Shared prompts for skill selection and invocation.
import json
from typing import Any, Dict


def skill_selection_prompt(
    *,
    agent_name: str,
    skill_names: list[str],
    skill_summaries: Dict[str, Dict[str, str]],
    issue_summary: Dict[str, Any],
    policy_text: str = "",
) -> str:
    policy_section = (
        f"\n# 此 agent 的 skill 使用條件\n{policy_text.strip()}\n"
        if policy_text.strip()
        else ""
    )
    return (
        "你正在準備會議討論發言。請判斷是否需要先使用你自己的 skill 產生簡短參考。\n\n"
        f"# Agent\n{agent_name}\n\n"
        f"# 可用 skills\n{json.dumps(skill_names, ensure_ascii=False)}\n\n"
        f"# Skill 說明\n{json.dumps(skill_summaries, ensure_ascii=False, indent=2)}\n"
        f"{policy_section}\n"
        f"# 議題\n{json.dumps(issue_summary, ensure_ascii=False, indent=2)}\n\n"
        "# 判斷規則\n"
        "- 只有 skill 能明顯改善本輪發言品質時才使用。\n"
        "- 一次最多選一個 skill。\n"
        "- 若目前只需要一般角色判斷，不要使用 skill。\n"
        "- 不要為了形式而使用 skill。\n\n"
        "# 輸出 JSON\n"
        '{"use_skill": true/false, "skill_name": "可用 skill 名稱或空字串", "reason": "一句理由"}'
    )


def skill_reference_task() -> str:
    return (
        "請針對會議議題，依此 skill 產生本 agent 發言前可用的簡短參考。\n"
        "只輸出 1 到 4 點重點；包含必要依據、風險、限制或建議方向。\n"
        "不要產生最終決議，不要改寫 artifact，不要輸出 JSON。"
    )
