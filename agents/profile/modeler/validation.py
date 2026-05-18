# Modeler validation: normalize model artifacts, diagram payloads, and impact outputs.
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


def valid_plantuml(value: Any) -> str:
    text = clean_text(value)
    if "@startuml" not in text or "@enduml" not in text:
        return ""
    return text


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

    name = clean_text(raw.get("name")) or diagram_type

    row = {
        "name": name,
        "type": diagram_type,
        "plantuml": plantuml,
    }
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
    return {
        "models_to_update": model_types(source.get("models_to_update")),
        "models_to_create": model_types(source.get("models_to_create")),
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
