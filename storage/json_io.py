import json
import re

from pathlib import Path
from typing import Any, Dict, Union


_SCI_JSON_NUMBER = re.compile(r"-?\d+(?:\.\d+)?[eE][+-]?\d+")


def json_dumps_no_scientific(
    obj: Any,
    *,
    indent: int = 2,
    ensure_ascii: bool = False,
) -> str:
    """json.dumps 後將數字字面上的科學記號改為十進位（避免 1.98e-05）。"""
    text = json.dumps(obj, indent=indent, ensure_ascii=ensure_ascii)

    def repl(m: re.Match) -> str:
        v = float(m.group(0))
        if v == 0.0:
            return "0"
        s = format(v, ".15f").rstrip("0").rstrip(".")
        return s if s else "0"

    return _SCI_JSON_NUMBER.sub(repl, text)


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


def load_json_file(base_dir: Path, filepath: Union[str, Path]) -> Dict[str, Any]:
    path = Path(filepath)
    if not path.is_absolute():
        path = base_dir / filepath
    if not path.exists():
        raise FileNotFoundError(f"檔案不存在: {path}")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


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
