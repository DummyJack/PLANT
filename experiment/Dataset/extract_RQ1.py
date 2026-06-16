import json
import sys
from pathlib import Path

# 讓此腳本可從任意工作目錄直接執行（含 python experiment/...）
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from utils.clean import apply_entrypoint_bootstrap

apply_entrypoint_bootstrap()

ORDERED_NAMES = [
    "Stock Report Generation System",
    "Hospital Management and Information System",
    "Bus and Railway Ticket Booking System",
    "Adult Vocabulary Learning and Quiz System",
]


def main() -> None:
    base = Path(__file__).resolve().parent
    src = base / "ReqElicitBench.json"
    out_paths = [
        base / "ReqElicitBench_5.json",
    ]

    with src.open(encoding="utf-8") as f:
        data = json.load(f)

    by_name: dict[str, dict] = {}
    for item in data:
        if not isinstance(item, dict) or "name" not in item:
            continue
        name = str(item["name"])
        if name not in by_name:
            by_name[name] = item

    missing = [n for n in ORDERED_NAMES if n not in by_name]
    if missing:
        raise KeyError(f"找不到以下 name（須與來源 JSON 完全一致）: {missing}")

    subset = [by_name[n] for n in ORDERED_NAMES]

    payload = json.dumps(subset, ensure_ascii=False, indent=2) + "\n"
    for out in out_paths:
        out.write_text(payload, encoding="utf-8")

    print(f"已寫入 {len(subset)} 筆 -> {', '.join(str(p) for p in out_paths)}")


if __name__ == "__main__":
    main()
