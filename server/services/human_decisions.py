import re
from typing import Any, Dict, List

from utils.human import STAKEHOLDER_CATEGORY_VALUES


def parse_stakeholder_response(
    response: Dict[str, Any],
    proposed: List[Dict[str, Any]],
    *,
    max_select: int,
) -> List[Dict[str, Any]]:
    structured = response.get("stakeholders")
    if not isinstance(structured, list) or not structured:
        raise ValueError("未選擇 stakeholder")

    selected: List[Dict[str, Any]] = []
    seen = set()
    for row in structured:
        if not isinstance(row, dict):
            continue
        name = str(row.get("name") or "").strip()
        stakeholder_type = str(row.get("type") or "").strip()
        if not name or name in seen:
            continue
        if stakeholder_type not in STAKEHOLDER_CATEGORY_VALUES:
            raise ValueError(f"stakeholder type is invalid: {name}")
        selected.append(
            {
                "name": name,
                "type": stakeholder_type,
                "reason": str(row.get("reason") or "使用者自訂").strip() or "使用者自訂",
            }
        )
        seen.add(name)

    if not selected:
        raise ValueError("未選擇合法 stakeholder")
    if len(selected) > max_select:
        raise ValueError(f"選擇超過 {max_select} 個 stakeholder")
    return selected


def _clean_option_title(value: Any) -> str:
    title = str(value or "").strip()
    return re.sub(r"^[A-Z]\s*[:：]\s*", "", title)


def _option_letter(index: int) -> str:
    if index < 1:
        return ""
    letters = ""
    value = index
    while value:
        value, rem = divmod(value - 1, 26)
        letters = chr(65 + rem) + letters
    return letters


def _option_display_label(value: Any) -> str:
    rows = [row.strip().upper() for row in str(value or "").split(",") if row.strip()]
    labels = []
    for row in rows:
        label = _option_letter(int(row)) if row.isdigit() else row
        if label:
            labels.append(f"選項 {label}")
    return "、".join(labels) if labels else "選項"


def _normalize_options(options: Any) -> List[Dict[str, Any]]:
    if isinstance(options, dict):
        best_options = options.get("best_options", []) or []
        compromise = options.get("compromise", {}) or {}
    elif isinstance(options, list):
        best_options = options
        compromise = {}
    else:
        best_options = []
        compromise = {}

    all_options: List[Dict[str, Any]] = []
    for opt in best_options:
        if not isinstance(opt, dict):
            continue
        option = dict(opt)
        index = len(all_options) + 1
        option_id = str(option.get("option_id") or "").strip().upper()
        if not re.fullmatch(r"[A-Z]+", option_id):
            option_id = _option_letter(index)
        option["option_id"] = option_id
        option["index"] = index
        option["title"] = _clean_option_title(opt.get("title", ""))
        all_options.append(option)

    if isinstance(compromise, dict) and compromise:
        option = dict(compromise)
        index = len(all_options) + 1
        option_id = str(option.get("option_id") or "").strip().upper()
        if not re.fullmatch(r"[A-Z]+", option_id):
            option_id = _option_letter(index)
        option["option_id"] = option_id
        option["index"] = index
        option["title"] = _clean_option_title(compromise.get("title", ""))
        all_options.append(option)

    return all_options


def _normalize_choice(value: Any, options: List[Dict[str, Any]]) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    if raw == "0":
        return "0"
    raw = raw.upper()
    for opt in options:
        option_id = str(opt.get("option_id") or "").strip().upper()
        if raw == option_id:
            return option_id
    return ""


def _selected_option_payload(opt: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "option_id": opt.get("option_id"),
        "index": opt.get("index"),
        "title": _clean_option_title(opt.get("title", "")),
        "description": str(opt.get("description") or "").strip(),
        "rationale": str(opt.get("rationale") or "").strip(),
    }


def normalize_decision_options_payload(options: Any) -> Any:
    normalized = _normalize_options(options)
    if not normalized:
        return options

    best_options = [
        _selected_option_payload(option)
        for option in normalized
    ]
    payload: Dict[str, Any] = {"best_options": best_options}

    source_recommendation = (
        options.get("recommendation", {})
        if isinstance(options, dict) and isinstance(options.get("recommendation"), dict)
        else {}
    )
    recommendation = dict(source_recommendation)
    if not recommendation:
        for option in normalized:
            if option.get("recommendation") is True:
                recommendation = {
                    "option_id": option.get("option_id"),
                    "rationale": str(
                        option.get("recommendation_rationale")
                        or option.get("recommended_rationale")
                        or option.get("rationale")
                        or ""
                    ).strip(),
                }
                break
    raw_recommended = recommendation.get("option_id")
    recommended_id = _normalize_choice(raw_recommended, normalized)
    if recommended_id:
        recommendation["option_id"] = recommended_id
        payload["recommendation"] = recommendation
    elif recommendation:
        payload["recommendation"] = recommendation

    return payload


def _empty_decision(summary: str = "人類選擇暫不裁決", **extra: Any) -> Dict[str, Any]:
    return {
        "summary": summary,
        "decision": "",
        "chosen_option_id": "",
        "chosen_option_title": "",
        **extra,
    }


def _option_text(option: Dict[str, Any]) -> str:
    title = _clean_option_title(option.get("title", ""))
    description = str(option.get("description") or "").strip()
    rationale = str(option.get("rationale") or "").strip()
    text = title
    if description and description != title:
        text = f"{title}，{description}" if title else description
    if rationale:
        text = f"{text}。理由：{rationale}" if text else f"理由：{rationale}"
    return text


def _decision_from_options(
    selected_options: List[Dict[str, Any]],
    *,
    empty_when_text_missing: bool,
    strip_summary: bool,
) -> Dict[str, Any]:
    decision_items = [text for option in selected_options if (text := _option_text(option))]
    if empty_when_text_missing and not decision_items:
        return _empty_decision()

    choice_label = ",".join(
        str(option.get("option_id"))
        for option in selected_options
        if option.get("option_id") is not None
    )
    title_label = "；".join(
        _clean_option_title(option.get("title", "")) for option in selected_options
    )
    decision_text = "\n".join(
        f"{index}. {text}" for index, text in enumerate(decision_items, 1)
    )
    summary = f"人類採納{_option_display_label(choice_label)}: {title_label}"
    return {
        "status": "human_decision",
        "summary": summary.strip() if strip_summary else summary,
        "decision": decision_text,
        "chosen_option_id": choice_label,
        "chosen_option_title": title_label,
        "chosen_options": selected_options,
    }


def _option_with_overrides(
    source: Dict[str, Any],
    overrides: Dict[str, Any],
    option_id: str,
) -> Dict[str, Any]:
    description = str(overrides.get("description") or "").strip()
    rationale = str(overrides.get("rationale") or "").strip()
    return _selected_option_payload(
        {
            **source,
            "option_id": option_id,
            "description": description
            or str(source.get("description") or "").strip(),
            "rationale": rationale or str(source.get("rationale") or "").strip(),
        }
    )


def _parse_structured_options(
    structured_options: List[Any],
    all_options: List[Dict[str, Any]],
) -> Dict[str, Any]:
    selected_options = []
    options_by_id = {
        str(option.get("option_id") or "").strip().upper(): option
        for option in all_options
    }
    for option in structured_options:
        if not isinstance(option, dict):
            continue
        option_id = _normalize_choice(option.get("option_id"), all_options)
        if not option_id:
            raise ValueError("invalid human decision choices")
        source = options_by_id.get(option_id, option)
        selected_options.append(_option_with_overrides(source, option, option_id))
    return _decision_from_options(
        selected_options,
        empty_when_text_missing=True,
        strip_summary=True,
    )


def _parse_choice_list(
    choices: List[Any],
    custom_decision: str,
    all_options: List[Dict[str, Any]],
) -> Dict[str, Any]:
    parsed_choices = []
    for item in choices:
        normalized = _normalize_choice(item, all_options)
        if not normalized:
            raise ValueError("invalid human decision choices")
        if normalized not in parsed_choices:
            parsed_choices.append(normalized)

    if "0" in parsed_choices and len(parsed_choices) > 1:
        raise ValueError("custom decision cannot be combined with other choices")
    if parsed_choices == ["0"]:
        if not custom_decision:
            return _empty_decision(
                "人類未輸入裁決",
                chosen_option_id="0",
                chosen_option_title="自行輸入裁決",
            )
        return {
            "status": "human_decision",
            "summary": f"由人類裁決: {custom_decision}",
            "decision": custom_decision,
            "chosen_option_id": "0",
            "chosen_option_title": "自行輸入裁決",
        }

    options_by_id = {
        str(option.get("option_id") or "").strip().upper(): option
        for option in all_options
    }
    try:
        chosen_options = [options_by_id[choice] for choice in parsed_choices]
    except KeyError as exc:
        raise ValueError("invalid human decision choices") from exc
    selected_options = [_selected_option_payload(option) for option in chosen_options]
    return _decision_from_options(
        selected_options,
        empty_when_text_missing=False,
        strip_summary=False,
    )


def parse_human_decision_response(
    response: Dict[str, Any],
    options: Any,
) -> Dict[str, Any]:
    if response.get("skipped") is True:
        return _empty_decision(skipped=True)

    all_options = _normalize_options(options)
    structured_options = response.get("chosen_options")
    if isinstance(structured_options, list) and structured_options:
        return _parse_structured_options(structured_options, all_options)

    custom_decision = str(response.get("custom_decision") or "").strip()
    choices = response.get("choices")
    if isinstance(choices, list) and choices:
        return _parse_choice_list(choices, custom_decision, all_options)

    if not custom_decision:
        return _empty_decision()
    return {
        "status": "human_decision",
        "summary": f"由人類裁決: {custom_decision}",
        "decision": custom_decision,
        "chosen_option_id": "custom",
        "chosen_option_title": "前端輸入裁決",
    }
