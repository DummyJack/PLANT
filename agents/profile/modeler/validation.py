# Validates and normalizes agent output data formats.
import re
from typing import Any, Dict, List, Optional


diagram_type_set = {
    "context_diagram",
    "use_case_diagram",
    "activity_diagram",
    "sequence_diagram",
    "state_machine",
    "class_diagram",
}

model_type_set = diagram_type_set | {"use_case_text"}
model_op_set = {"create", "update"}
max_model_targets = 4
primitive_type_re = re.compile(
    r"^([+#~\-\s]*[^:\n{}()]+):\s*(string|str|int|integer|decimal|float|double|number|datetime|date|time|boolean|bool)\s*$",
    re.IGNORECASE,
)
generic_interface_values = {
    "平台前台",
    "平台前台（app或web）",
    "平台前台(app或web)",
    "平台後台",
    "平台後台（app或web）",
    "平台後台(app或web)",
    "平台管理後台",
    "管理後台",
    "app",
    "web",
    "app或web",
}
generic_interface_prefixes = {
    "平台前台",
    "平台前台app或web",
    "平台後台",
    "平台後台app或web",
    "平台管理後台",
    "管理後台",
    "app或web",
}
interface_entry_re = re.compile(r"^[^－-]+[－-].+入口(?:（.*）)?$")


# ========
# Defines clean text function for this module workflow.
# ========
def clean_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return "、".join(clean_text(item) for item in value if clean_text(item))
    if isinstance(value, dict):
        return "、".join(
            f"{clean_text(key)}：{clean_text(item)}"
            for key, item in value.items()
            if clean_text(key) and clean_text(item)
        )
    return str(value).strip()


# ========
# Defines compact text key function for this module workflow.
# ========
def compact_text_key(value: Any) -> str:
    return re.sub(r"[\s　,，、（）()]+", "", clean_text(value).lower())


# ========
# Defines use case interface pages function for this module workflow.
# ========
def use_case_interface_pages(actor: str, name: str, interface: str = "") -> str:
    actor_text = clean_text(actor)
    name_text = clean_text(name)
    interface_text = clean_text(interface)
    value = f"{actor_text} {name_text} {interface_text}"

    if "瀏覽" in value or "搜尋" in value:
        if "餐廳" in value:
            return "首頁搜尋列、餐廳列表頁、餐廳詳情頁"
        return "搜尋頁、結果列表頁、詳情頁"
    if "購物車" in value or "加點" in value:
        return "餐廳菜單頁、購物車頁"
    if "建立" in value or "下單" in value or "訂單" in value and "管理" in value and "消費" in actor_text:
        return "購物車頁、結帳頁、訂單確認頁、訂單列表頁"
    if "付款" in value or "退款" in value or "金流" in value:
        return "結帳頁、支付頁面（整合第三方金流介面）、退款狀態頁"
    if "申訴" in value or "異常" in value or "客訴" in value:
        if "外送" in actor_text:
            return "外送員配送任務頁、配送狀態回報頁、異常回報頁"
        return "訂單詳情頁、異常回報頁、申訴處理進度頁"
    if "聯絡" in value:
        return "訂單詳情頁、外送員聯絡頁"
    if "新訂單" in value or "備餐" in value:
        return "餐廳後台訂單列表頁、訂單詳情頁、備餐狀態頁"
    if "菜單" in value or "庫存" in value:
        return "餐廳後台菜單管理頁、庫存管理頁、餐點編輯頁"
    if "取餐" in value:
        if "外送" in actor_text and "路線" in value:
            return "外送員配送任務頁、取餐資訊頁、路線地圖頁"
        return "餐廳後台訂單詳情頁、取餐通知介面"
    if "接收" in value and "外送" in actor_text:
        return "外送員任務列表頁、配送任務詳情頁"
    if "路線" in value:
        return "外送員配送任務頁、路線地圖頁"
    if "回報" in value and "外送" in actor_text:
        return "外送員配送任務頁、配送狀態回報頁、異常回報頁"
    if "監控" in value or "營運數據" in value:
        return "營運後台儀表板、訂單監控頁、營運報表頁"
    if "活動" in value or "促銷" in value:
        return "營運後台活動管理頁、通知規則設定頁"
    if ("追蹤" in value or "進度" in value or "配送" in value) and "消費" in actor_text:
        return "訂單追蹤頁（顯示地圖與狀態列）、訂單詳情頁"
    if "通知" in value:
        channels = [
            hint for hint in ("App 推播", "簡訊", "Email")
            if hint.replace(" ", "") in interface_text.replace(" ", "") or hint in interface_text
        ]
        suffix = "、" + "、".join(dict.fromkeys(channels)) if channels else ""
        return f"通知中心、訂單詳情頁、通知偏好設定頁{suffix}"
    if "合作夥伴" in value or "表現" in value:
        return "營運後台合作夥伴管理頁、餐廳表現頁、外送員表現頁"
    if "糾紛" in value or "濫用" in value:
        return "營運後台申訴案件頁、交易糾紛處理頁、濫用風險審查頁"
    if "穩定" in value or "彈性" in value or "維護" in value:
        return "營運後台系統狀態頁、服務監控頁、維護設定頁"
    if "餐廳" in actor_text:
        return f"餐廳後台{name_text}頁"
    if "外送" in actor_text:
        return f"外送員{name_text}頁"
    if "營運" in actor_text or "主管" in actor_text:
        return f"營運後台{name_text}頁"
    return f"{name_text}頁"


# ========
# Defines normalize use case interface function for this module workflow.
# ========
def normalize_use_case_interface(actor: str, name: str, interface: str) -> str:
    actor_text = clean_text(actor)
    name_text = clean_text(name)
    interface_text = clean_text(interface)
    value = f"{actor_text} {name_text} {interface_text}"
    if "餐廳" in actor_text and "取餐" in value:
        return "餐廳後台訂單詳情頁、取餐通知介面"
    if "外送" in actor_text and "回報" in value:
        return "外送員配送任務頁、配送狀態回報頁、異常回報頁"
    if "外送" in actor_text and "路線" in value:
        return "外送員配送任務頁、取餐資訊頁、路線地圖頁"
    if ("營運" in actor_text or "主管" in actor_text) and ("活動" in value or "促銷" in value):
        return "營運後台活動管理頁、通知規則設定頁"
    compact = compact_text_key(interface_text)
    is_generic = compact in generic_interface_values or any(
        compact.startswith(prefix) for prefix in generic_interface_prefixes
    ) or bool(interface_entry_re.match(interface_text))
    if interface_text and not is_generic:
        return interface_text
    return use_case_interface_pages(actor, name, interface)


# ========
# Defines clean list function for this module workflow.
# ========
def clean_list(values: Any) -> List[Any]:
    if values is None:
        return []
    if not isinstance(values, list):
        values = [values]
    rows: List[Any] = []
    seen = set()
    for value in values:
        if value is None:
            continue
        if isinstance(value, dict):
            row = {str(k): v for k, v in value.items() if v not in (None, "", [], {})}
            key = str(sorted(row.items()))
            if row and key not in seen:
                rows.append(row)
                seen.add(key)
            continue
        text = clean_text(value)
        if text and text not in seen:
            rows.append(text)
            seen.add(text)
    return rows


# ========
# Defines clean model types function for this module workflow.
# ========
def clean_model_types(values: Any) -> List[str]:
    out: List[str] = []
    for value in values or []:
        model_type = clean_text(value)
        if model_type in model_type_set and model_type not in out:
            out.append(model_type)
    return out


# ========
# Defines model targets function for this module workflow.
# ========
def model_targets(values: Any) -> List[Dict[str, str]]:
    if not isinstance(values, list):
        return []
    out: List[Dict[str, str]] = []
    seen = set()
    for idx, item in enumerate(values, 1):
        if isinstance(item, str):
            raise ValueError(f"model_targets[{idx}] must be an object with explicit operation")
        elif isinstance(item, dict):
            target = {
                "operation": clean_text(item.get("operation")).lower(),
                "type": clean_text(item.get("type")),
                "target_model_id": clean_text(item.get("target_model_id") or item.get("id")),
                "name": clean_text(item.get("name")),
                "reason": clean_text(item.get("reason")),
                "value_reason": clean_text(item.get("value_reason")),
                "related_requirement_ids": [
                    clean_text(value)
                    for value in (item.get("related_requirement_ids") or [])
                    if clean_text(value)
                ],
            }
        else:
            continue
        if target.get("type") not in diagram_type_set:
            continue
        if target.get("type") == "use_case_text":
            continue
        if target.get("operation") not in model_op_set:
            raise ValueError(
                f"model_targets[{idx}] operation must be create or update"
            )
        if target.get("operation") == "update" and not (
            target.get("target_model_id") or (target.get("type") and target.get("name"))
        ):
            raise ValueError(
                f"model_targets[{idx}] update requires target_model_id or type + name"
            )
        if target.get("operation") == "create" and not target.get("name"):
            raise ValueError(f"model_targets[{idx}] create requires name")
        if not target.get("value_reason"):
            raise ValueError(f"model_targets[{idx}] requires value_reason")
        clean_target = {
            key: value for key, value in target.items()
            if value not in (None, "", [], {})
        }
        key = (
            clean_target.get("operation"),
            clean_target.get("type"),
            clean_target.get("target_model_id"),
            clean_target.get("name"),
        )
        if key in seen:
            continue
        seen.add(key)
        out.append(clean_target)
        if len(out) >= max_model_targets:
            break
    return out


# ========
# Defines valid plantuml function for this module workflow.
# ========
def valid_plantuml(value: Any) -> str:
    text = clean_text(value)
    if "@startuml" not in text or "@enduml" not in text:
        return ""
    return text


# ========
# Defines clean class plantuml function for this module workflow.
# ========
def clean_class_plantuml(plantuml: str) -> str:
    return plantuml


element_decl_re = re.compile(
    r'^\s*(?P<kind>actor|usecase|class|state|participant|boundary|control|entity|database|collections|queue)\s+'
    r'(?:"(?P<quoted>[^"]+)"|(?P<plain>[\w\u4e00-\u9fff][^\s]*))\s+as\s+'
    r'(?P<alias>[A-Za-z_][A-Za-z0-9_]*)\s*$'
)
self_relation_re = re.compile(
    r'^\s*(?P<left>[A-Za-z_][A-Za-z0-9_]*)\s+[-.<ox]*[->]+[-.<ox]*\s+(?P=left)\b'
)


# ========
# Defines dedupe elements function for this module workflow.
# ========
def dedupe_elements(plantuml: str) -> str:
    lines = plantuml.splitlines()
    label_to_alias: Dict[tuple[str, str], str] = {}
    alias_redirects: Dict[str, str] = {}
    kept_lines: List[str] = []

    for line in lines:
        match = element_decl_re.match(line)
        if not match:
            kept_lines.append(line)
            continue
        kind = clean_text(match.group("kind")).lower()
        label = clean_text(match.group("quoted") or match.group("plain"))
        alias = clean_text(match.group("alias"))
        if not label or not alias:
            kept_lines.append(line)
            continue
        key = (kind, label)
        if key in label_to_alias:
            alias_redirects[alias] = label_to_alias[key]
            continue
        label_to_alias[key] = alias
        kept_lines.append(line)

    if not alias_redirects:
        return plantuml

    normalized_lines: List[str] = []
    seen_relation_lines = set()
    for line in kept_lines:
        new_line = line
        for old_alias, new_alias in alias_redirects.items():
            new_line = re.sub(rf"\b{re.escape(old_alias)}\b", new_alias, new_line)
        if new_line != line and self_relation_re.match(new_line):
            continue
        relation_key = re.sub(r"\s+", " ", new_line.strip())
        if relation_key and relation_key in seen_relation_lines:
            continue
        if "--" in new_line or "->" in new_line or "<-" in new_line:
            seen_relation_lines.add(relation_key)
        normalized_lines.append(new_line)
    return "\n".join(normalized_lines)


# ========
# Defines parse diagram model function for this module workflow.
# ========
def parse_diagram_model(
    raw: Any,
    *,
    expected_type: Optional[str] = None,
    source: str = "",
) -> Dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError("diagram output must be a JSON object")

    diagram_type = clean_text(raw.get("type"))
    if diagram_type not in diagram_type_set:
        raise ValueError(f"diagram type is invalid: {diagram_type or '<empty>'}")
    if expected_type and diagram_type != expected_type:
        raise ValueError(f"diagram type must be {expected_type}, got {diagram_type}")

    plantuml = valid_plantuml(raw.get("plantuml"))
    if not plantuml:
        raise ValueError("diagram plantuml must include @startuml and @enduml")
    if diagram_type == "class_diagram":
        plantuml = clean_class_plantuml(plantuml)
    if diagram_type in {
        "context_diagram",
        "use_case_diagram",
        "class_diagram",
        "sequence_diagram",
        "state_machine",
    }:
        plantuml = dedupe_elements(plantuml)

    name = clean_text(raw.get("name"))
    if not name:
        raise ValueError("diagram name is required")

    row = {
        "name": name,
        "type": diagram_type,
        "plantuml": plantuml,
    }
    model_id = clean_text(raw.get("id"))
    if model_id:
        row["id"] = model_id
    related_requirement_ids = [
        clean_text(value)
        for value in (raw.get("related_requirement_ids") or [])
        if clean_text(value)
    ]
    if related_requirement_ids:
        row["related_requirement_ids"] = related_requirement_ids
    description = clean_text(raw.get("description"))
    if not description:
        raise ValueError("diagram description is required")
    if description:
        row["description"] = description
    text_rows = raw.get("text") or raw.get("use_case_text")
    if diagram_type == "use_case_diagram" and isinstance(text_rows, list):
        clean_rows: List[Dict[str, Any]] = []
        seen_text = set()
        for idx, item in enumerate(text_rows, 1):
            if not isinstance(item, dict):
                continue
            row_id = clean_text(item.get("id"))
            if not row_id:
                raise ValueError(f"use case text[{idx}] id is required")
            text_row = {
                "id": row_id,
                "actor": clean_text(item.get("actor")),
                "name": clean_text(item.get("name")),
                "purpose": clean_text(item.get("purpose")),
                "related_requirement_ids": [
                    clean_text(value)
                    for value in (item.get("related_requirement_ids") or [])
                    if clean_text(value)
                ],
            }
            text_row["interface"] = normalize_use_case_interface(
                text_row["actor"],
                text_row["name"],
                item.get("interface"),
            )
            if not text_row["name"] or not text_row["purpose"]:
                continue
            key = (text_row["actor"], text_row["name"], text_row["purpose"])
            if key in seen_text:
                continue
            seen_text.add(key)
            clean_rows.append(text_row)
        if clean_rows:
            row["text"] = clean_rows
    source_text = clean_text(raw.get("source"))
    if source_text:
        row["source"] = source_text
    return row


# ========
# Defines parse use case function for this module workflow.
# ========
def parse_use_case(raw: Any, *, source: str = "") -> Dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError("use case text output must be a JSON object")
    model_type = clean_text(raw.get("type"))
    if model_type != "use_case_text":
        raise ValueError(f"model type must be use_case_text, got {model_type}")
    rows: List[Dict[str, Any]] = []
    seen = set()
    for idx, item in enumerate(raw.get("text") or [], 1):
        if not isinstance(item, dict):
            continue
        row_id = clean_text(item.get("id"))
        if not row_id:
            raise ValueError(f"use_case_text[{idx}] id is required")
        row = {
            "id": row_id,
            "actor": clean_text(item.get("actor")),
            "name": clean_text(item.get("name")),
            "purpose": clean_text(item.get("purpose")),
            "related_requirement_ids": [
                clean_text(value)
                for value in (item.get("related_requirement_ids") or [])
                if clean_text(value)
            ],
        }
        row["interface"] = normalize_use_case_interface(
            row["actor"],
            row["name"],
            item.get("interface"),
        )
        if not row["name"] or not row["purpose"]:
            continue
        key = (row["actor"], row["name"], row["purpose"])
        if key in seen:
            continue
        seen.add(key)
        rows.append(row)
    if not rows:
        raise ValueError("use_case_text must include text")
    result = {
        "type": "use_case_text",
        "text": rows,
    }
    model_id = clean_text(raw.get("id"))
    if model_id:
        result["id"] = model_id
    source_text = clean_text(raw.get("source"))
    if source_text:
        result["source"] = source_text
    return result


# ========
# Defines parse model function for this module workflow.
# ========
def parse_model(raw: Any, *, source: str = "") -> Dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError("model output must be a JSON object")
    model_type = clean_text(raw.get("type"))
    if model_type == "use_case_text":
        return parse_use_case(raw, source=source)
    return parse_diagram_model(raw, source=source)


# ========
# Defines parse model list function for this module workflow.
# ========
def parse_model_list(raw: Any, *, source: str = "") -> List[Dict[str, Any]]:
    if not isinstance(raw, list):
        raise ValueError("model output must be a JSON list")
    models: List[Dict[str, Any]] = []
    for idx, row in enumerate(raw, 1):
        try:
            models.append(parse_model(row, source=source))
        except ValueError as exc:
            raise ValueError(f"models[{idx}] invalid: {exc}") from exc
    return models


# ========
# Defines parse impact assessment function for this module workflow.
# ========
def parse_impact_assessment(raw: Any) -> Dict[str, Any]:
    source = raw if isinstance(raw, dict) else {}
    if not isinstance(source.get("model_plan"), dict):
        raise ValueError("model plan output must contain model_plan object")
    plan_source = source["model_plan"]
    targets = model_targets(plan_source.get("model_targets"))
    return {
        "model_plan": {
            "phase_decision": clean_text(plan_source.get("phase_decision")),
            "model_targets": targets,
            "skipped_targets": clean_list(plan_source.get("skipped_targets")),
            "impact_summary": clean_text(plan_source.get("impact_summary")),
            "consistency_summary": clean_text(plan_source.get("consistency_summary")),
            "gaps": clean_list(plan_source.get("gaps")),
        }
    }


# ========
# Defines parse plantuml fix function for this module workflow.
# ========
def parse_plantuml_fix(raw: Any) -> Dict[str, str]:
    source = raw if isinstance(raw, dict) else {}
    plantuml = valid_plantuml(source.get("plantuml"))
    if not plantuml:
        raise ValueError("fixed PlantUML output must include @startuml and @enduml")
    return {"plantuml": plantuml}
