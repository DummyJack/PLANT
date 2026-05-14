import json
from pathlib import Path

ORDERED_NAMES = [
    "Stock Report Generation System",  # 股票分析報告系統
    "Hospital Management and Information System",  # 醫院管理與資訊系統
    "Bus and Railway Ticket Booking System",  # 公車與鐵路訂票系統
    "Adult Vocabulary Learning and Quiz System",  # 單字學習與測驗系統
    "Social Networking and Content Sharing Platform",  # 社群網路與內容分享平台
]


def main() -> None:
    base = Path(__file__).resolve().parent
    src = base / "ReqElicitBench.json"
    out_paths = [
        base.parent / "ReqElicitBench_5.json",
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
