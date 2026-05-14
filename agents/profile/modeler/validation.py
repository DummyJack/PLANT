# Modeler validation: normalize model artifacts, diagram payloads, and impact outputs.
from typing import Any, Dict, List, Optional


ALLOWED_DIAGRAM_TYPES = {
    "context_diagram",
    "use_case_diagram",
    "activity_diagram",
    "data_flow_diagram",
    "sequence_diagram",
    "state_machine_diagram",
    "class_diagram",
}


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


def expected_maturity(diagram_type: str) -> str:
    return "tentative" if diagram_type == "class_diagram" else "requirement_level"


def plantuml_text(value: Any) -> str:
    text = clean_text(value)
    if "@startuml" not in text or "@enduml" not in text:
        return ""
    return text


def diagram_payload(
    raw: Any,
    *,
    expected_type: Optional[str] = None,
) -> Dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError("diagram output must be a JSON object")

    diagram_type = clean_text(raw.get("type") or expected_type)
    if diagram_type not in ALLOWED_DIAGRAM_TYPES:
        raise ValueError(f"diagram type is invalid: {diagram_type or '<empty>'}")
    if expected_type and diagram_type != expected_type:
        raise ValueError(f"diagram type must be {expected_type}, got {diagram_type}")

    plantuml = plantuml_text(raw.get("plantuml"))
    if not plantuml:
        raise ValueError("diagram plantuml must include @startuml and @enduml")

    name = clean_text(raw.get("name")) or diagram_type
    maturity = clean_text(raw.get("maturity")) or expected_maturity(diagram_type)
    if maturity not in {"requirement_level", "tentative"}:
        maturity = expected_maturity(diagram_type)
    if diagram_type == "class_diagram":
        maturity = "tentative"

    return {
        "name": name,
        "type": diagram_type,
        "plantuml": plantuml,
        "to_confirm": clean_list(raw.get("to_confirm")),
        "maturity": maturity,
    }


def model_artifact_payload(raw: Any) -> Dict[str, Any]:
    source = raw if isinstance(raw, dict) else {}
    models: List[Dict[str, Any]] = []
    for row in source.get("models") or []:
        try:
            models.append(diagram_payload(row))
        except ValueError:
            continue

    return {
        "model_summary": clean_text(source.get("model_summary")),
        "to_confirm": clean_list(source.get("to_confirm")),
        "assumptions": clean_list(source.get("assumptions")),
        "model_revision_mode": clean_text(source.get("model_revision_mode")),
        "revision_history": [
            row for row in (source.get("revision_history") or [])
            if isinstance(row, dict)
        ],
        "last_consistency_report": source.get("last_consistency_report")
        if isinstance(source.get("last_consistency_report"), dict)
        else {},
        "models": models,
    }


def impact_assessment_payload(raw: Any) -> Dict[str, Any]:
    source = raw if isinstance(raw, dict) else {}
    return {
        "models_to_update": diagram_types(source.get("models_to_update")),
        "models_to_create": diagram_types(source.get("models_to_create")),
        "impact_summary": clean_text(source.get("impact_summary")),
        "consistency_summary": clean_text(source.get("consistency_summary")),
        "gaps": clean_list(source.get("gaps")),
    }


def plantuml_fix_payload(raw: Any) -> Dict[str, str]:
    source = raw if isinstance(raw, dict) else {}
    plantuml = plantuml_text(source.get("plantuml"))
    if not plantuml:
        raise ValueError("fixed PlantUML output must include @startuml and @enduml")
    return {"plantuml": plantuml}
