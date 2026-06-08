# Defines action usage timing and output rules.

import json
from typing import Any, Dict, List, Optional

from agents.profile.base import question_rules
from agents.profile.base import conflict_review_text_hint


# ========
# Defines response actions function for this module workflow.
# ========
def response_actions() -> Dict[str, str]:
    return {
        "answer_question": "使用時機：議題是 OQ（待回答 open question）或 expected_actions 指定 user 回答特定問題。不要使用：一般議題發言。寫回或影響：只回覆問題文字，補 `reply_to_question`、`reply_to_agent` 與 `speaking_as`，不主動更新需求。",
        "respond_issue": "使用時機：在一般正式會議中代表被指定或最相關利害關係人給出立場、顧慮、底線與可接受條件。不要使用：回答 open question。寫回或影響：只回應發言內容，不直接更新需求。",
    }


# ========
# Defines stakeholder contract function for this module workflow.
# ========
def stakeholder_contract(
    *,
    related_context: Optional[Dict[str, Any]],
    stakeholders: List[Dict[str, Any]],
) -> str:
    rough_idea = ""
    if isinstance(related_context, dict):
        rough_idea = str(related_context.get("rough_idea") or "").strip()
    role_parts = []
    allowed_names: List[str] = []
    for sh in stakeholders or []:
        name = str(sh.get("name") or "").strip()
        if not name:
            continue
        allowed_names.append(name)
        texts = sh.get("text") or []
        if isinstance(texts, list):
            needs = "\n".join(f"  - {str(t).strip()}" for t in texts if str(t).strip())
        else:
            needs = f"  - {str(texts).strip()}" if str(texts).strip() else ""
        role_parts.append(f"【{name}】\n{needs or '  - 待補'}")
    if not role_parts:
        return ""
    return (
        "\n# 利害關係人回答約束（必須遵守）\n"
        f"原始產品情境：{rough_idea or '（未提供）'}\n\n"
        "只能代表本專案已選定的情境利害關係人發言；不得新增其他回答身份或轉向其他產品情境。\n\n"
        + "\n\n".join(role_parts)
        + "\n\n規則：\n"
        "- 每個需求、顧慮、例外情境都必須能明確回扣原始產品情境。\n"
        "- 若問題很泛，請主動拉回上述產品情境與已選利害關係人日常使用場景。\n"
        "- 不得代表未列出的利害關係人發言；不得把產品轉成資料權限、人資、薪資、通用內部管理等無關系統。\n"
        f"- speaking_as 只能從這些名稱選擇：{', '.join(allowed_names)}。\n"
    )


# ========
# Defines category hint function for this module workflow.
# ========
def category_hint(
    *,
    issue: Dict[str, Any],
    issue_category: str,
    is_pair_review: bool,
    known_pair_ids: List[str],
) -> str:
    if issue_category in {"clarify_requirement", "formalize_requirement"}:
        if str(issue.get("title") or "").strip() == "需求正式化":
            return (
                "\n# 本議題特別說明（需求正式化）\n"
                "先閱讀前面 Analyst 產生或更新的 REQ-* 整理結果，再以 speaking_as 身份檢查："
                "是否漏掉重要使用情境、業務規則或例外條件；"
                "驗收條件是否可接受；優先級是否符合實際需要；"
                "限制、風險或假設是否正確。"
            )
        return (
            f"\n# 本議題特別說明（{issue_category}）\n"
            "聚焦需求語意、使用條件、成功結果、例外情境與可接受的驗收方式。"
        )
    if issue_category == "define_boundary":
        return (
            "\n# 本議題特別說明（define_boundary）\n"
            "說明此需求在實際使用上應由本系統、外部服務、人工流程或哪個角色負責。"
        )
    if issue_category == "tradeoff":
        return (
            "\n# 本議題特別說明（tradeoff）\n"
            "比較可接受與不可接受方案，說明取捨底線與推薦方向。"
        )
    if issue_category == "align_model":
        return (
            "\n# 本議題特別說明（align_model）\n"
            "從使用者/利害關係人角度確認流程、狀態、actor 或責任分工是否符合實際情境。"
        )
    if issue_category != "resolve_conflict":
        return ""
    if is_pair_review:
        return (
            "\n# 本議題特別說明（resolve_conflict）\n"
            "從實際使用情境說明兩項需求是否衝突、重複、可共存或資訊不足。\n"
            "- 外層輸出只包含 text 欄位的 JSON object。\n"
            "- text 必須是 JSON object 字串，不是巢狀 object。\n"
            "- text JSON 結構必須為 {\"pair_reviews\":[...]}。\n"
            "- pair_reviews 必須逐筆涵蓋 本輪必須涵蓋的 pair id 中每個 id，不能遺漏、不能新增未知 id。\n"
            "- 每筆 pair_reviews 都必須有 id、proposed_label、reason。\n"
            "- proposed_label 只能是 Conflict 或 Neutral。\n"
            f"- 本輪必須涵蓋的 pair id：{json.dumps(known_pair_ids, ensure_ascii=False)}"
        )
    return (
        "\n# 本議題特別說明（resolve_conflict）\n"
        "逐一針對 conflict report 中列出的 URL 需求與既有 resolution option 表態。\n"
        "- 不泛談整體平台感受。\n"
        "- 明確說出哪些 URL 的內容可以合併、保留、改寫或不可接受。\n"
        "- 說明此 speaking_as 的最低可接受條件、不能被刪掉的語意，以及需要保留的例外情境。\n"
        "- 不提出 open_questions；資訊不足時直接說明目前可接受的保守處理方式。"
    )


# ========
# Defines open question rule function for this module workflow.
# ========
def open_question_rule(*, is_elicitation: bool, is_answer_question: bool) -> str:
    if is_answer_question:
        return "- open_questions 預設輸出空陣列；只有問題本身無法回答且答案會影響本議題結論時才提出。\n"
    return "" if is_elicitation else question_rules + "\n"


# ========
# Defines stance rule function for this module workflow.
# ========
def stance_rule(*, suppress_stance: bool) -> str:
    if suppress_stance:
        return ""
    return (
        "- stance.state 表示本輪 speaking_as 身份的討論狀態："
        "ready_to_close=資訊已足夠且可結束本議題；"
        "needs_more_discussion=還需要其他參與者補充或回應。\n"
        "- 若 stance.state 是 needs_more_discussion，必須在 stance.proposal 提供 proposal，說明建議如何處理此議題。\n"
        "- ready_to_close 表示本輪已足以產生下一版 draft、resolution 或 human decision options；不代表所有細節都已完美。\n"
        "- needs_more_discussion 必須同時提供最小可行 proposal，說明目前建議如何處理，以及仍缺哪個關鍵答案。\n"
    )


# ========
# Defines stance json function for this module workflow.
# ========
def stance_json(*, suppress_stance: bool) -> str:
    if suppress_stance:
        return ""
    return ', "stance": {"state": "ready_to_close | needs_more_discussion", "proposal": {"summary": "建議方案", "rationale": "理由", "tradeoffs": ["取捨或限制"]}}'


# ========
# Defines response json function for this module workflow.
# ========
def response_json(
    *,
    need_speaking_as: bool,
    is_elicitation: bool,
    is_answer_question: bool,
    is_pair_review: bool,
) -> str:
    if is_pair_review:
        return conflict_review_text_hint()
    if is_answer_question:
        if need_speaking_as:
            return '"speaking_as": ["本輪回答身份名稱"], "text": "直接回答問題", "open_questions": []'
        return '"text": "直接回答問題", "open_questions": []'
    if need_speaking_as:
        text = '"speaking_as": ["本輪發言身份名稱"], "text": "完整發言內容"'
    else:
        text = '"text": "針對此議題的完整發言內容"'
    if not is_elicitation:
        text += ', "open_questions": [{"to": "目標參與者名稱", "question": "會影響本議題結論的具體問題", "reason": "此答案會如何影響需求、驗收、風險、邊界或可接受條件"}]'
    return text


# ========
# Defines response flow function for this module workflow.
# ========
def response_flow(
    *,
    need_speaking_as: bool,
    answer_all_questions: bool,
    is_answer_question: bool,
) -> str:
    if is_answer_question:
        return "以議題規劃指定的 speaking_as 身份，直接回答 description 中的問題。"
    if answer_all_questions:
        return (
            "逐題回答前面每一位參與者提出的問題；text 內請用「發問者 → 回答身份」分段，"
            "每題都要明確回答，不要只回最後一題。"
        )
    if need_speaking_as:
        return "依議題規劃指定的 speaking_as，說明該身份在此議題上的立場、需求與底線。"
    return "以第一人稱撰寫一段完整發言，說明立場、需求與底線。"
