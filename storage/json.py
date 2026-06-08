# Handles json logic for project artifact storage and file export behavior.
import json
import re

from pathlib import Path
from typing import Any, Dict, Union


SCI_JSON_NUMBER = re.compile(r"-?\d+(?:\.\d+)?[eE][+-]?\d+")


# ========
# Defines json dumps no scientific function for this module workflow.
# ========
def json_dumps_no_scientific(
    obj: Any,
    *,
    indent: int = 2,
    ensure_ascii: bool = False,
) -> str:
    text = json.dumps(obj, indent=indent, ensure_ascii=ensure_ascii)

    def repl(m: re.Match) -> str:
        v = float(m.group(0))
        if v == 0.0:
            return "0"
        s = format(v, ".15f").rstrip("0").rstrip(".")
        return s if s else "0"

    return SCI_JSON_NUMBER.sub(repl, text)


# ========
# Defines json dump no scientific function for this module workflow.
# ========
def json_dump_no_scientific(
    obj: Any,
    fp,
    *,
    indent: int = 2,
    ensure_ascii: bool = False,
) -> None:
    fp.write(
        json_dumps_no_scientific(obj, indent=indent, ensure_ascii=ensure_ascii)
    )


# ========
# Defines parse first json function for this module workflow.
# ========
def parse_first_json(raw: str) -> Dict[str, Any]:
    if not raw or not isinstance(raw, str):
        raise ValueError("Agent output must be a valid JSON object.")
    text = raw.strip()
    candidates = [text]
    if "```" in text:
        for part in text.split("```"):
            value = part.strip()
            if value.lower().startswith("json"):
                value = value[4:].strip()
            if value.startswith("{") and value.endswith("}"):
                candidates.append(value)
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        candidates.append(text[start : end + 1])

    last_error = None
    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError as e:
            last_error = e
            continue
        if isinstance(parsed, dict):
            return parsed
    if last_error is not None:
        raise ValueError(f"Agent output must be a valid JSON object: {last_error}") from last_error
    raise ValueError("Agent output must be a JSON object.")


# ========
# Defines load json file function for this module workflow.
# ========
def load_json_file(base_dir: Path, filepath: Union[str, Path]) -> Dict[str, Any]:
    path = Path(filepath)
    if not path.is_absolute():
        path = base_dir / filepath
    if not path.exists():
        raise FileNotFoundError(f"檔案不存在: {path}")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


# ========
# Defines save json file function for this module workflow.
# ========
def save_json_file(
    base_dir: Path,
    data: Dict[str, Any],
    filepath: Union[str, Path],
    indent: int = 2,
) -> None:
    path = Path(filepath)
    if not path.is_absolute():
        path = base_dir / filepath
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=indent)
