#!/usr/bin/env python3
"""組合抽樣輸出 cn_100.csv。

規則：
1) pure_clean_pairs.csv 抽 20 筆（10 Conflict + 10 Neutral）
2) open_coss_clean_pairs.csv 抽 10 筆（5 Conflict + 5 Neutral）
3) world_vista_clean_pairs.csv 抽 30 筆（15 Conflict + 15 Neutral）
4) cn_pairs.csv 依四個子系統各抽 10 筆（5 Conflict + 5 Neutral）
   - Bird Feeder Control System
   - Viewer Application
   - Aviary System Software
   - Communication Management Software

輸出欄位：ID, types, Text1, Text2, Class
"""

from __future__ import annotations

import csv
import random
from collections import Counter
from pathlib import Path

SEED = 20260412

BASE_DIR = Path(__file__).resolve().parent
OUT_PATH = BASE_DIR / "cn_100.csv"

PURE_PATH = BASE_DIR / "pure_clean_pairs.csv"
OPEN_COSS_PATH = BASE_DIR / "open_coss_clean_pairs.csv"
WORLD_VISTA_PATH = BASE_DIR / "world_vista_clean_pairs.csv"
CN_PATH = BASE_DIR / "cn_pairs.csv"

FIELDS_OUT = ["ID", "types", "Text1", "Text2", "Class"]


def read_rows(path: Path) -> list[dict]:
    with path.open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    return rows


def balanced_pick(rows: list[dict], n: int, rng: random.Random) -> list[dict]:
    """從 rows 抽 n 筆，且 Conflict/Neutral 各半。"""
    if n % 2 != 0:
        raise ValueError(f"n 必須為偶數：{n}")
    need = n // 2
    conflict = [r for r in rows if (r.get("Class") or "").strip() == "Conflict"]
    neutral = [r for r in rows if (r.get("Class") or "").strip() == "Neutral"]
    if len(conflict) < need or len(neutral) < need:
        raise RuntimeError(
            f"樣本不足：Conflict={len(conflict)}, Neutral={len(neutral)}, need={need}"
        )
    rng.shuffle(conflict)
    rng.shuffle(neutral)
    picked = conflict[:need] + neutral[:need]
    rng.shuffle(picked)
    return picked


def to_row(row: dict, typ: str) -> dict:
    return {
        "types": typ,
        "Text1": row.get("Text1", ""),
        "Text2": row.get("Text2", ""),
        "Class": (row.get("Class") or "").strip(),
    }


def classify_cn_subsystem(row: dict) -> str:
    text = f"{row.get('Text1', '')} {row.get('Text2', '')}".lower()
    if any(k in text for k in ("bird feeder", "pilot controller", "pilot station")):
        return "UAV Control System"
    if any(k in text for k in ("viewer", "remote viewer")):
        return "UAV Monitoring and Visualization System"
    if any(
        k in text
        for k in ("communication", "secure", "snooping", "eavesdropping", "network")
    ):
        return "UAV Communication Security System"
    return "UAV Mission Management System"


def pick_cn_subsystems(rows: list[dict], rng: random.Random) -> list[dict]:
    target_types = [
        "UAV Control System",
        "UAV Monitoring and Visualization System",
        "UAV Mission Management System",
        "UAV Communication Security System",
    ]
    out: list[dict] = []
    for typ in target_types:
        subset = [r for r in rows if classify_cn_subsystem(r) == typ]
        picked = balanced_pick(subset, n=10, rng=rng)
        out.extend([to_row(r, typ) for r in picked])
    return out


def write_rows(rows: list[dict], out_path: Path) -> None:
    with out_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS_OUT)
        writer.writeheader()
        for idx, row in enumerate(rows):
            out = dict(row)
            out["ID"] = str(idx)  # ID 重新從 0 開始
            writer.writerow(out)


def main() -> None:
    for p in (PURE_PATH, OPEN_COSS_PATH, WORLD_VISTA_PATH, CN_PATH):
        if not p.is_file():
            raise FileNotFoundError(f"找不到來源檔案：{p}")

    rng = random.Random(SEED)
    final_rows: list[dict] = []

    pure_rows = read_rows(PURE_PATH)
    open_rows = read_rows(OPEN_COSS_PATH)
    world_rows = read_rows(WORLD_VISTA_PATH)
    cn_rows = read_rows(CN_PATH)

    final_rows.extend(
        [to_row(r, "Thermodynamic Analysis System") for r in balanced_pick(pure_rows, n=20, rng=rng)]
    )
    final_rows.extend(
        [
            to_row(r, "Safety-Critical Certification System")
            for r in balanced_pick(open_rows, n=10, rng=rng)
        ]
    )
    final_rows.extend(
        [
            to_row(r, "Health Management System")
            for r in balanced_pick(world_rows, n=30, rng=rng)
        ]
    )
    final_rows.extend(pick_cn_subsystems(cn_rows, rng=rng))

    if len(final_rows) != 100:
        raise RuntimeError(f"輸出筆數異常：{len(final_rows)}（預期 100）")

    write_rows(final_rows, OUT_PATH)

    cls = Counter(r["Class"] for r in final_rows)
    typ = Counter(r["types"] for r in final_rows)
    print(f"已輸出：{OUT_PATH}")
    print(f"總筆數：{len(final_rows)}")
    print(f"Class 分布：Conflict={cls['Conflict']}, Neutral={cls['Neutral']}")
    print("types 分布：")
    for t, n in typ.items():
        print(f"  - {t}: {n}")


if __name__ == "__main__":
    main()
