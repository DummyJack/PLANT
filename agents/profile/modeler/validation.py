# Modeler validation: normalize model artifacts, diagram payloads, and impact outputs.
import re
from typing import Any, Dict, List, Optional


ALLOWED_DIAGRAM_TYPES = {
    "context_diagram",
    "use_case_diagram",
    "activity_diagram",
    "sequence_diagram",
    "state_machine",
    "class_diagram",
}

ALLOWED_MODEL_TYPES = ALLOWED_DIAGRAM_TYPES | {"use_case_text"}
ALLOWED_MODEL_OPERATIONS = {"create", "update"}


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


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


def diagram_types(values: Any) -> List[str]:
    out: List[str] = []
    for value in values or []:
        diagram_type = clean_text(value)
        if diagram_type in ALLOWED_DIAGRAM_TYPES and diagram_type not in out:
            out.append(diagram_type)
    return out


def model_types(values: Any) -> List[str]:
    out: List[str] = []
    for value in values or []:
        model_type = clean_text(value)
        if model_type in ALLOWED_MODEL_TYPES and model_type not in out:
            out.append(model_type)
    return out


def model_targets(values: Any) -> List[Dict[str, str]]:
    if not isinstance(values, list):
        return []
    out: List[Dict[str, str]] = []
    seen = set()
    for item in values:
        if isinstance(item, str):
            target = {
                "operation": "update",
                "type": clean_text(item),
            }
        elif isinstance(item, dict):
            target = {
                "operation": clean_text(item.get("operation")).lower() or "update",
                "type": clean_text(item.get("type")),
                "target_model_id": clean_text(item.get("target_model_id") or item.get("id")),
                "name": clean_text(item.get("name")),
                "reason": clean_text(item.get("reason")),
            }
        else:
            continue
        if target.get("type") not in ALLOWED_DIAGRAM_TYPES:
            continue
        if target.get("type") == "use_case_text":
            continue
        if target.get("operation") not in ALLOWED_MODEL_OPERATIONS:
            target["operation"] = "update"
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
    return out


def valid_plantuml(value: Any) -> str:
    text = clean_text(value)
    if "@startuml" not in text or "@enduml" not in text:
        return ""
    return text


NAMED_ELEMENT_DECL_RE = re.compile(
    r'^\s*(?P<kind>actor|usecase|class|state|participant|boundary|control|entity|database|collections|queue)\s+'
    r'(?:"(?P<quoted>[^"]+)"|(?P<plain>[\w\u4e00-\u9fff][^\s]*))\s+as\s+'
    r'(?P<alias>[A-Za-z_][A-Za-z0-9_]*)\s*$'
)
SELF_RELATION_RE = re.compile(
    r'^\s*(?P<left>[A-Za-z_][A-Za-z0-9_]*)\s+[-.<ox]*[->]+[-.<ox]*\s+(?P=left)\b'
)


def normalize_duplicate_named_elements(plantuml: str) -> str:
    """Merge duplicate named PlantUML elements that use different aliases for the same label."""
    lines = plantuml.splitlines()
    label_to_alias: Dict[tuple[str, str], str] = {}
    alias_redirects: Dict[str, str] = {}
    kept_lines: List[str] = []

    for line in lines:
        match = NAMED_ELEMENT_DECL_RE.match(line)
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
        if new_line != line and SELF_RELATION_RE.match(new_line):
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
) -> Dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError("diagram output must be a JSON object")

    diagram_type = clean_text(raw.get("type") or expected_type)
    if diagram_type not in ALLOWED_DIAGRAM_TYPES:
        raise ValueError(f"diagram type is invalid: {diagram_type or '<empty>'}")
    if expected_type and diagram_type != expected_type:
        raise ValueError(f"diagram type must be {expected_type}, got {diagram_type}")

    plantuml = valid_plantuml(raw.get("plantuml"))
    if not plantuml:
        raise ValueError("diagram plantuml must include @startuml and @enduml")
    if diagram_type in {
        "context_diagram",
        "use_case_diagram",
        "class_diagram",
        "sequence_diagram",
        "state_machine",
    }:
        plantuml = normalize_duplicate_named_elements(plantuml)

    name = clean_text(raw.get("name")) or diagram_type

    row = {
        "name": name,
        "type": diagram_type,
        "plantuml": plantuml,
    }
    model_id = clean_text(raw.get("id"))
    if model_id:
        row["id"] = model_id
    description = clean_text(raw.get("description"))
    if diagram_type == "use_case_diagram":
        description = ""
    elif not description:
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
            text_row = {
                "id": clean_text(item.get("id")) or f"UC-{idx}",
                "actor": clean_text(item.get("actor")),
                "name": clean_text(item.get("name")),
                "purpose": clean_text(item.get("purpose")),
                "interface": clean_text(item.get("interface")),
                "related_requirements": [
                    clean_text(value)
                    for value in (item.get("related_requirements") or [])
                    if clean_text(value)
                ],
            }
            if not text_row["name"] or not text_row["purpose"]:
                continue
            key = (text_row["actor"], text_row["name"], text_row["purpose"])
            if key in seen_text:
                continue
            seen_text.add(key)
            clean_rows.append(text_row)
        if clean_rows:
            row["text"] = clean_rows
    source_text = clean_text(raw.get("source") or source)
    if source_text:
        row["source"] = source_text
    return row


def parse_use_case_text(raw: Any, *, source: str = "") -> Dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError("use case text output must be a JSON object")
    model_type = clean_text(raw.get("type")) or "use_case_text"
    if model_type != "use_case_text":
        raise ValueError(f"model type must be use_case_text, got {model_type}")
    rows: List[Dict[str, Any]] = []
    seen = set()
    for idx, item in enumerate(raw.get("text") or [], 1):
        if not isinstance(item, dict):
            continue
        row = {
            "id": clean_text(item.get("id")) or f"UC-{idx}",
            "actor": clean_text(item.get("actor")),
            "name": clean_text(item.get("name")),
            "purpose": clean_text(item.get("purpose")),
            "interface": clean_text(item.get("interface")),
            "related_requirements": [
                clean_text(value)
                for value in (item.get("related_requirements") or [])
                if clean_text(value)
            ],
        }
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
    source_text = clean_text(raw.get("source") or source)
    if source_text:
        result["source"] = source_text
    return result


def parse_model(raw: Any, *, source: str = "") -> Dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError("model output must be a JSON object")
    model_type = clean_text(raw.get("type"))
    if model_type == "use_case_text":
        return parse_use_case_text(raw, source=source)
    return parse_diagram_model(raw, source=source)


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


def parse_impact_assessment(raw: Any) -> Dict[str, Any]:
    source = raw if isinstance(raw, dict) else {}
    targets = model_targets(source.get("model_targets"))
    if not targets:
        targets = [
            {"operation": "update", "type": model_type}
            for model_type in model_types(source.get("models_to_update"))
        ] + [
            {"operation": "create", "type": model_type}
            for model_type in model_types(source.get("models_to_create"))
        ]
    return {
        "model_targets": targets,
        "models_to_update": [
            target.get("type")
            for target in targets
            if target.get("operation") == "update" and target.get("type")
        ],
        "models_to_create": [
            target.get("type")
            for target in targets
            if target.get("operation") == "create" and target.get("type")
        ],
        "impact_summary": clean_text(source.get("impact_summary")),
        "consistency_summary": clean_text(source.get("consistency_summary")),
        "gaps": clean_list(source.get("gaps")),
    }


def parse_plantuml_fix(raw: Any) -> Dict[str, str]:
    source = raw if isinstance(raw, dict) else {}
    plantuml = valid_plantuml(source.get("plantuml"))
    if not plantuml:
        raise ValueError("fixed PlantUML output must include @startuml and @enduml")
    return {"plantuml": plantuml}
