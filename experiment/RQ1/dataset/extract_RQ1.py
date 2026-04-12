import json
from pathlib import Path

ORDERED_NAMES = [
    "Stock Report Generation System",
    "Online Mathematical Calculation System",
    "DMV Practice Test and Exam Simulation System",
    "Custom Shirt E-Commerce Design and Ordering System",
    "Prize Wheel Management System",
    "Baseball Simulation and Team Management System",
    "Texas Hold'em Online Poker Platform",
    "Online Trivia Contest Platform",
    "Online Chess Game Platform",
    "Online Polling System",
]


def main() -> None:
    base = Path(__file__).resolve().parent
    src = base / "ReqElicitBench.json"
    out = base / "ReqElicitBench_10.json"

    with src.open(encoding="utf-8") as f:
        data = json.load(f)

    if not isinstance(data, list):
        raise TypeError("ReqElicitBench.json 頂層應為陣列")

    # 來源檔可能含重複 name；同一 name 只保留第一筆（與既有資料集相容）
    by_name: dict[str, dict] = {}
    for item in data:
        if not isinstance(item, dict) or "name" not in item:
            continue
        name = item["name"]
        if name not in by_name:
            by_name[name] = item

    missing = [n for n in ORDERED_NAMES if n not in by_name]
    if missing:
        raise KeyError(f"找不到以下 name: {missing}")

    subset = [by_name[n] for n in ORDERED_NAMES]

    with out.open("w", encoding="utf-8") as f:
        json.dump(subset, f, ensure_ascii=False, indent=2)
        f.write("\n")

    print(f"已寫入 {len(subset)} 筆 -> {out}")


if __name__ == "__main__":
    main()
