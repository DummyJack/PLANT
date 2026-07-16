from typing import Any, Dict, List


ACTION_PLAN_OUTPUT_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "required": ["action", "params", "reasoning", "goal", "steps"],
    "properties": {
        "action": {"type": "string", "enum": ["done"]},
        "params": {"type": "object"},
        "reasoning": {"type": "string"},
        "goal": {"type": "string"},
        "steps": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "required": ["id", "action", "params", "reasoning"],
                "properties": {
                    "id": {"type": "string"},
                    "action": {"type": "string"},
                    "params": {"type": "object"},
                    "reasoning": {"type": "string"},
                },
            },
        },
    },
}

EXPERT_RESEARCH_PLAN_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "required": ["research_plan"],
    "properties": {
        "research_plan": {
            "type": "object",
            "required": ["action", "params", "reasoning", "goal", "steps"],
            "properties": {
                "action": {"type": "string", "enum": ["done"]},
                "params": {"type": "object", "properties": {}},
                "reasoning": {"type": "string"},
                "goal": {"type": "string"},
                "steps": {
                    "type": "array",
                    "items": {
                        "anyOf": [
                            {
                                "type": "object",
                                "required": ["action", "params"],
                                "properties": {
                                    "action": {"type": "string", "enum": ["read_reference_docs"]},
                                    "params": {
                                        "type": "object",
                                        "required": ["query"],
                                        "properties": {"query": {"type": "string"}},
                                    },
                                },
                            },
                            {
                                "type": "object",
                                "required": ["action", "params"],
                                "properties": {
                                    "action": {"type": "string", "enum": ["research_issue"]},
                                    "params": {
                                        "type": "object",
                                        "required": ["target_type", "target_ids", "query", "value_reason"],
                                        "properties": {
                                            "target_type": {"type": "string", "enum": ["URL", "REQ", "scope", "open_question", "issue"]},
                                            "target_ids": {"type": "array", "items": {"type": "string"}},
                                            "query": {"type": "string"},
                                            "value_reason": {"type": "string"},
                                        },
                                    },
                                },
                            },
                            {
                                "type": "object",
                                "required": ["action", "params"],
                                "properties": {
                                    "action": {"type": "string", "enum": ["update_feedback"]},
                                    "params": {"type": "object", "properties": {}},
                                },
                            },
                        ]
                    },
                },
            },
        }
    },
}


def _type_matches(value: Any, expected: str) -> bool:
    return {
        "object": isinstance(value, dict),
        "array": isinstance(value, list),
        "string": isinstance(value, str),
        "integer": isinstance(value, int) and not isinstance(value, bool),
        "number": isinstance(value, (int, float)) and not isinstance(value, bool),
        "boolean": isinstance(value, bool),
        "null": value is None,
    }.get(expected, True)


def validate_json_schema(value: Any, schema: Dict[str, Any], path: str = "$") -> None:
    options = schema.get("anyOf")
    if isinstance(options, list):
        errors = []
        for option in options:
            if not isinstance(option, dict):
                continue
            try:
                validate_json_schema(value, option, path)
                break
            except ValueError as exc:
                errors.append(str(exc))
        else:
            detail = errors[0] if errors else "no valid schema option"
            raise ValueError(f"{path} does not match any allowed shape: {detail}")

    expected = schema.get("type")
    expected_types: List[str] = expected if isinstance(expected, list) else [expected]
    expected_types = [item for item in expected_types if isinstance(item, str)]
    if expected_types and not any(_type_matches(value, item) for item in expected_types):
        raise ValueError(f"{path} must be {' or '.join(expected_types)}")

    enum = schema.get("enum")
    if isinstance(enum, list) and value not in enum:
        raise ValueError(f"{path} must be one of {enum}")

    if isinstance(value, dict):
        required = schema.get("required") if isinstance(schema.get("required"), list) else []
        missing = [key for key in required if key not in value]
        if missing:
            raise ValueError(f"{path} missing required fields: {', '.join(missing)}")
        properties = schema.get("properties") if isinstance(schema.get("properties"), dict) else {}
        for key, child_schema in properties.items():
            if key in value and isinstance(child_schema, dict):
                validate_json_schema(value[key], child_schema, f"{path}.{key}")

    if isinstance(value, list):
        minimum = schema.get("minItems")
        if isinstance(minimum, int) and len(value) < minimum:
            raise ValueError(f"{path} must contain at least {minimum} items")
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            for index, item in enumerate(value):
                validate_json_schema(item, item_schema, f"{path}[{index}]")
