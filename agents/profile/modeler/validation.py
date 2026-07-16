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
missing_interface_marker = "待補充"


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


def compact_text_key(value: Any) -> str:
    return re.sub(r"[\s　,，、（）()]+", "", clean_text(value).lower())


def normalize_use_case_interface(_actor: str, _name: str, interface: str) -> str:
    interface_text = clean_text(interface)
    compact = compact_text_key(interface_text)
    is_generic = compact in generic_interface_values or any(
        compact.startswith(prefix) for prefix in generic_interface_prefixes
    ) or bool(interface_entry_re.match(interface_text))
    if interface_text and not is_generic:
        return interface_text
    return missing_interface_marker


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


def validate_model_requirement_references(
    model: Dict[str, Any],
    allowed_requirement_ids: Optional[set[str]],
) -> None:
    if allowed_requirement_ids is None:
        return
    referenced = {
        clean_text(value)
        for value in (model.get("related_requirement_ids") or [])
        if clean_text(value)
    }
    for row in model.get("text") or []:
        if isinstance(row, dict):
            referenced.update(
                clean_text(value)
                for value in (row.get("related_requirement_ids") or [])
                if clean_text(value)
            )
    unknown = sorted(referenced - allowed_requirement_ids)
    if unknown:
        raise ValueError(
            "related_requirement_ids contain unknown requirement IDs: "
            + ", ".join(unknown)
        )


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
                "target_model_id": clean_text(item.get("target_model_id")),
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


def valid_plantuml(value: Any) -> str:
    text = clean_text(value)
    if "@startuml" not in text or "@enduml" not in text:
        return ""
    return text


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


def parse_diagram_model(
    raw: Any,
    *,
    expected_type: Optional[str] = None,
    source: str = "",
    allowed_requirement_ids: Optional[set[str]] = None,
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
    text_rows = raw.get("text")
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
    validate_model_requirement_references(row, allowed_requirement_ids)
    return row


def parse_use_case(
    raw: Any,
    *,
    source: str = "",
    allowed_requirement_ids: Optional[set[str]] = None,
) -> Dict[str, Any]:
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
    validate_model_requirement_references(result, allowed_requirement_ids)
    return result


def parse_model(
    raw: Any,
    *,
    source: str = "",
    allowed_requirement_ids: Optional[set[str]] = None,
) -> Dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError("model output must be a JSON object")
    model_type = clean_text(raw.get("type"))
    if model_type == "use_case_text":
        return parse_use_case(
            raw,
            source=source,
            allowed_requirement_ids=allowed_requirement_ids,
        )
    return parse_diagram_model(
        raw,
        source=source,
        allowed_requirement_ids=allowed_requirement_ids,
    )


def parse_model_list(
    raw: Any,
    *,
    source: str = "",
    allowed_requirement_ids: Optional[set[str]] = None,
) -> List[Dict[str, Any]]:
    if not isinstance(raw, list):
        raise ValueError("model output must be a JSON list")
    models: List[Dict[str, Any]] = []
    for idx, row in enumerate(raw, 1):
        try:
            models.append(
                parse_model(
                    row,
                    source=source,
                    allowed_requirement_ids=allowed_requirement_ids,
                )
            )
        except ValueError as exc:
            raise ValueError(f"models[{idx}] invalid: {exc}") from exc
    return models


def parse_impact_assessment(
    raw: Any,
    *,
    allowed_requirement_ids: Optional[set[str]] = None,
    allowed_model_ids: Optional[set[str]] = None,
) -> Dict[str, Any]:
    source = raw if isinstance(raw, dict) else {}
    if not isinstance(source.get("model_plan"), dict):
        raise ValueError("model plan output must contain model_plan object")
    plan_source = source["model_plan"]
    targets = model_targets(plan_source.get("model_targets"))
    for index, target in enumerate(targets, 1):
        related_ids = {
            clean_text(value)
            for value in (target.get("related_requirement_ids") or [])
            if clean_text(value)
        }
        if allowed_requirement_ids is not None:
            unknown_requirements = sorted(related_ids - allowed_requirement_ids)
            if unknown_requirements:
                raise ValueError(
                    f"model_targets[{index}] contains unknown requirement IDs: "
                    + ", ".join(unknown_requirements)
                    + "; allowed IDs: "
                    + ", ".join(sorted(allowed_requirement_ids))
                )
        target_model_id = clean_text(target.get("target_model_id"))
        if (
            target.get("operation") == "update"
            and target_model_id
            and allowed_model_ids is not None
            and target_model_id not in allowed_model_ids
        ):
            raise ValueError(
                f"model_targets[{index}] references unknown target_model_id: "
                f"{target_model_id}; allowed IDs: "
                + ", ".join(sorted(allowed_model_ids))
            )
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


def parse_plantuml_fix(raw: Any) -> Dict[str, str]:
    source = raw if isinstance(raw, dict) else {}
    plantuml = valid_plantuml(source.get("plantuml"))
    if not plantuml:
        raise ValueError("fixed PlantUML output must include @startuml and @enduml")
    return {"plantuml": plantuml}
