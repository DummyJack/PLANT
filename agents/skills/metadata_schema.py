from typing import Any, Dict, List, Tuple


REQUIRED_TOP_LEVEL_FIELDS = [
    "name",
    "description",
    "triggers",
    "inputs",
    "tools",
    "workflow",
    "outputs",
    "integration",
    "quality",
]


def validate_skill_metadata(metadata: Dict[str, Any]) -> Tuple[bool, List[str]]:
    """驗證統一 skill metadata schema（v1）。"""
    errors: List[str] = []
    for key in REQUIRED_TOP_LEVEL_FIELDS:
        if key not in metadata:
            errors.append(f"missing field: {key}")

    if "inputs" in metadata:
        for key in ("required", "optional"):
            if key not in metadata["inputs"]:
                errors.append(f"inputs missing: {key}")
    if "tools" in metadata:
        for key in ("allowed", "external", "prerequisites"):
            if key not in metadata["tools"]:
                errors.append(f"tools missing: {key}")
    if "workflow" in metadata and "steps" not in metadata["workflow"]:
        errors.append("workflow missing: steps")
    if "outputs" in metadata and "artifacts" not in metadata["outputs"]:
        errors.append("outputs missing: artifacts")
    if "integration" in metadata:
        for key in ("upstream", "downstream", "related"):
            if key not in metadata["integration"]:
                errors.append(f"integration missing: {key}")
    if "quality" in metadata and "acceptance_criteria" not in metadata["quality"]:
        errors.append("quality missing: acceptance_criteria")

    return (len(errors) == 0, errors)
