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
    if isinstance(structured, list) and structured:
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

    selections = response.get("selections")
    if isinstance(selections, list) and selections:
        selected = []
        seen = set()
        for row in selections:
            if not isinstance(row, dict):
                continue
            if "index" in row:
                idx = int(row["index"]) - 1
                if 0 <= idx < len(proposed):
                    candidate = dict(proposed[idx])
                    name = str(candidate.get("name") or "").strip()
                    stakeholder_type = str(candidate.get("type") or "").strip()
                    if stakeholder_type not in STAKEHOLDER_CATEGORY_VALUES:
                        raise ValueError(f"proposed stakeholder type is invalid: {name}")
                    if name and name not in seen:
                        selected.append(candidate)
                        seen.add(name)
                continue
            name = str(row.get("name") or "").strip()
            stakeholder_type = str(row.get("type") or "primary_user").strip()
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
        return selected[:max_select]

    raw = str(response.get("text") or response.get("selection") or "").strip()
    if not raw:
        raise ValueError("未選擇 stakeholder")

    custom_types = response.get("custom_types")
    if not isinstance(custom_types, dict):
        custom_types = {}

    selected = []
    seen = set()
    for part in [item.strip() for item in re.split(r"[,，\s]+", raw) if item.strip()]:
        try:
            idx = int(part) - 1
            if 0 <= idx < len(proposed):
                row = proposed[idx]
                name = str(row.get("name") or "").strip()
                stakeholder_type = str(row.get("type") or "").strip()
                if stakeholder_type not in STAKEHOLDER_CATEGORY_VALUES:
                    raise ValueError(f"proposed stakeholder type is invalid: {name}")
                if name and name not in seen:
                    selected.append(row)
                    seen.add(name)
            continue
        except ValueError as exc:
            if "proposed stakeholder" in str(exc):
                raise
        name = part.strip()
        if not name or name in seen:
            continue
        stakeholder_type = str(custom_types.get(name) or "primary_user").strip()
        if stakeholder_type not in STAKEHOLDER_CATEGORY_VALUES:
            raise ValueError(f"stakeholder type is invalid: {name}")
        selected.append(
            {
                "name": name,
                "type": stakeholder_type,
                "reason": "使用者自訂",
            }
        )
        seen.add(name)

    if not selected:
        raise ValueError("未選擇合法 stakeholder")
    return selected[:max_select]


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
        option_id = str(option.get("option_id") or option.get("id") or "").strip().upper()
        if not re.fullmatch(r"[A-Z]+", option_id):
            option_id = _option_letter(index)
        option["id"] = option_id
        option["option_id"] = option_id
        option["index"] = index
        option["title"] = _clean_option_title(opt.get("title", ""))
        all_options.append(option)

    if isinstance(compromise, dict) and compromise:
        option = dict(compromise)
        index = len(all_options) + 1
        option_id = str(option.get("option_id") or option.get("id") or "").strip().upper()
        if not re.fullmatch(r"[A-Z]+", option_id):
            option_id = _option_letter(index)
        option["id"] = option_id
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
        option_id = str(opt.get("id") or "").strip().upper()
        if raw == option_id:
            return option_id
    return ""


def _selected_option_payload(opt: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": opt.get("id"),
        "option_id": opt.get("option_id") or opt.get("id"),
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
    raw_recommended = (
        recommendation.get("option_id")
        or recommendation.get("id")
        or recommendation.get("choice")
        or recommendation.get("option")
    )
    recommended_id = _normalize_choice(raw_recommended, normalized)
    if recommended_id:
        recommendation["option_id"] = recommended_id
        payload["recommendation"] = recommendation
    elif recommendation:
        payload["recommendation"] = recommendation

    return payload


def parse_human_decision_response(
    response: Dict[str, Any],
    options: Any,
) -> Dict[str, Any]:
    if response.get("skipped") is True:
        return {
            "summary": "人類選擇暫不裁決",
            "decision": "",
            "chosen_option_id": "",
            "chosen_option_title": "",
        }

    structured_options = response.get("chosen_options")
    if isinstance(structured_options, list) and structured_options:
        decision_items = []
        selected_options = []
        all_options = _normalize_options(options)
        for opt in structured_options:
            if not isinstance(opt, dict):
                continue
            normalized_id = _normalize_choice(opt.get("id"), all_options)
            if not normalized_id:
                raise ValueError("invalid human decision choices")
            source = next(
                (
                    row for row in all_options
                    if str(row.get("id") or "").strip().upper() == normalized_id
                ),
                opt,
            )
            title = _clean_option_title(source.get("title", ""))
            desc = str(opt.get("description") or "").strip()
            if not desc:
                desc = str(source.get("description") or "").strip()
            rationale = str(opt.get("rationale") or "").strip()
            if not rationale:
                rationale = str(source.get("rationale") or "").strip()
            option_text = title
            if desc and desc != title:
                option_text = f"{title}，{desc}" if title else desc
            if rationale:
                option_text = (
                    f"{option_text}。理由：{rationale}" if option_text else f"理由：{rationale}"
                )
            if option_text:
                decision_items.append(option_text)
            selected_options.append(_selected_option_payload({
                **source,
                "id": normalized_id or source.get("id") or opt.get("id"),
                "description": desc,
                "rationale": rationale,
            }))
        if not decision_items:
            return {
                "summary": "人類選擇暫不裁決",
                "decision": "",
                "chosen_option_id": "",
                "chosen_option_title": "",
            }
        decision_text = "\n".join(
            f"{index}. {text}" for index, text in enumerate(decision_items, 1)
        )
        choice_label = ",".join(
            str(opt.get("id")) for opt in selected_options if opt.get("id") is not None
        )
        title_label = "；".join(
            _clean_option_title(opt.get("title", "")) for opt in selected_options
        )
        return {
            "status": "human_decision",
            "summary": f"人類採納方案 {choice_label}: {title_label}".strip(),
            "decision": decision_text,
            "chosen_option_id": choice_label,
            "chosen_option_title": title_label,
            "chosen_options": selected_options,
        }

    custom_decision = str(response.get("custom_decision") or "").strip()
    choices = response.get("choices")
    all_options = _normalize_options(options)

    if isinstance(choices, list) and choices:
        parsed_choices = []
        for item in choices:
            normalized = _normalize_choice(item, all_options)
            if not normalized:
                raise ValueError("invalid human decision choices")
            parsed_choices.append(normalized)
        parsed_choices = list(dict.fromkeys(parsed_choices))
        if "0" in parsed_choices and len(parsed_choices) > 1:
            raise ValueError("custom decision cannot be combined with other choices")
        if parsed_choices == ["0"]:
            if not custom_decision:
                return {
                    "summary": "人類未輸入裁決",
                    "decision": "",
                    "chosen_option_id": "0",
                    "chosen_option_title": "自行輸入裁決",
                }
            return {
                "status": "human_decision",
                "summary": f"由人類裁決: {custom_decision}",
                "decision": custom_decision,
                "chosen_option_id": "0",
                "chosen_option_title": "自行輸入裁決",
            }
        chosen_options = [
            opt for choice in parsed_choices for opt in all_options if opt.get("id") == choice
        ]
        if len(chosen_options) != len(parsed_choices):
            raise ValueError("invalid human decision choices")
        decision_items = []
        selected_options = []
        for opt in chosen_options:
            title = _clean_option_title(opt.get("title", ""))
            desc = str(opt.get("description") or "").strip()
            rationale = str(opt.get("rationale") or "").strip()
            option_text = title
            if desc and desc != title:
                option_text = f"{title}，{desc}" if title else desc
            if rationale:
                option_text = (
                    f"{option_text}。理由：{rationale}" if option_text else f"理由：{rationale}"
                )
            if option_text:
                decision_items.append(option_text)
            selected_options.append(
                {
                    "id": opt.get("id"),
                    "index": opt.get("index"),
                    "title": title,
                    "description": desc,
                    "rationale": rationale,
                }
            )
        decision_text = "\n".join(
            f"{index}. {text}" for index, text in enumerate(decision_items, 1)
        )
        choice_label = ",".join(str(choice) for choice in parsed_choices)
        title_label = "；".join(
            _clean_option_title(opt.get("title", "")) for opt in chosen_options
        )
        return {
            "status": "human_decision",
            "summary": f"人類採納方案 {choice_label}: {title_label}",
            "decision": decision_text,
            "chosen_option_id": choice_label,
            "chosen_option_title": title_label,
            "chosen_options": selected_options,
        }

    decision = str(response.get("text") or response.get("decision") or custom_decision).strip()
    if not decision:
        return {
            "summary": "人類選擇暫不裁決",
            "decision": "",
            "chosen_option_id": "",
            "chosen_option_title": "",
        }
    return {
        "status": "human_decision",
        "summary": f"由人類裁決: {decision}",
        "decision": decision,
        "chosen_option_id": response.get("chosen_option_id", "custom"),
        "chosen_option_title": response.get("chosen_option_title", "前端輸入裁決"),
    }
