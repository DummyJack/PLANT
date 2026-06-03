from __future__ import annotations

from pathlib import Path

from utils.clean import apply_entrypoint_bootstrap

apply_entrypoint_bootstrap()

import sys

import argparse
import json
from pathlib import Path
from typing import Any, Dict, Optional

EXP_DIR = Path(__file__).resolve().parent


def read_summary(path: Path) -> Dict[str, Any]:
    with path.open(encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError(f"{path} 必須為 JSON 物件")
    return data


# 從 summary 的 metrics 或 cost 區塊取出 { 鍵: mean }。
def nested_means(section: Any) -> Dict[str, float]:
    out: Dict[str, float] = {}
    if not isinstance(section, dict):
        return out
    for key, val in section.items():
        if isinstance(val, dict) and "mean" in val:
            try:
                out[str(key)] = float(val["mean"])
            except (TypeError, ValueError):
                continue
    return out


# 越大越好指標：(Plant − Baseline) / |Baseline| × 100。
def plant_over_baseline_pct(plant_mean: float, baseline_mean: float) -> Optional[float]:
    if baseline_mean == 0.0:
        return None
    b = abs(float(baseline_mean))
    return (float(plant_mean) - float(baseline_mean)) / b * 100.0


# 成本／token／時間：Plant 為 Baseline 的幾倍（Plant mean ÷ Baseline mean）。
def plant_over_baseline_ratio(plant_mean: float, baseline_mean: float) -> Optional[float]:
    if baseline_mean == 0.0:
        return None
    return round(float(plant_mean) / float(baseline_mean), 4)


def compare_section_triplets(
    plant: Dict[str, float],
    baseline: Dict[str, float],
    *,
    cost_section: bool,
) -> Dict[str, Any]:
    if cost_section:
        all_k = set(plant) | set(baseline)
        preferred = ["average_token", "average_cost(USD)", "average_run_time(s)"]
        keys = [k for k in preferred if k in all_k]
        keys.extend(sorted(k for k in all_k if k not in keys))
    else:
        keys = sorted(set(plant) | set(baseline))
    rows: Dict[str, Any] = {}
    for k in keys:
        pm = plant.get(k)
        bm = baseline.get(k)
        if pm is None or bm is None:
            if cost_section:
                rows[k] = {
                    "plant_mean": pm,
                    "baseline_mean": bm,
                    "plant_over_baseline_ratio": None,
                }
            else:
                rows[k] = {
                    "plant_mean": pm,
                    "baseline_mean": bm,
                    "plant_over_baseline_pct": None,
                }
            continue
        fp, fb = float(pm), float(bm)
        if cost_section:
            rows[k] = {
                "plant_mean": fp,
                "baseline_mean": fb,
                "plant_over_baseline_ratio": plant_over_baseline_ratio(fp, fb),
            }
        else:
            lift = plant_over_baseline_pct(fp, fb)
            rows[k] = {
                "plant_mean": fp,
                "baseline_mean": fb,
                "plant_over_baseline_pct": (
                    None if lift is None else round(float(lift), 4)
                ),
            }
    return rows


def run_pair(*, plant_path: Path, baseline_path: Path) -> Dict[str, Any]:
    if not plant_path.is_file():
        raise FileNotFoundError(f"找不到 Plant summary：{plant_path}")
    if not baseline_path.is_file():
        raise FileNotFoundError(f"找不到 Baseline summary：{baseline_path}")

    p = read_summary(plant_path)
    b = read_summary(baseline_path)

    return {
        "metrics": compare_section_triplets(
            nested_means(p.get("metrics")),
            nested_means(b.get("metrics")),
            cost_section=False,
        ),
        "cost": compare_section_triplets(
            nested_means(p.get("cost")),
            nested_means(b.get("cost")),
            cost_section=True,
        ),
    }


def run_pair_try(*, plant_path: Path, baseline_path: Path) -> Dict[str, Any]:
    try:
        return run_pair(plant_path=plant_path, baseline_path=baseline_path)
    except FileNotFoundError as exc:
        return {"skipped": True, "reason": str(exc)}


def main() -> None:
    parser = argparse.ArgumentParser(description="Plant vs Baseline summary mean 比較（RQ1 / RQ2）")
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=EXP_DIR / "plant_over_baseline.json",
        help="輸出 JSON 路徑（預設 experiment/plant_over_baseline.json）",
    )
    args = parser.parse_args()

    rq1_results = EXP_DIR / "RQ1" / "results"
    rq2_results = EXP_DIR / "RQ2" / "results"

    rq1 = run_pair_try(
        plant_path=rq1_results / "Plant" / "summary_Plant.json",
        baseline_path=rq1_results / "baseline" / "summary_Baseline.json",
    )
    rq2 = run_pair_try(
        plant_path=rq2_results / "Plant" / "summary_Plant.json",
        baseline_path=rq2_results / "baseline" / "summary_Baseline.json",
    )
    if rq1.get("skipped"):
        print(f"略過 RQ1：{rq1['reason']}", file=sys.stderr)
    if rq2.get("skipped"):
        print(f"略過 RQ2：{rq2['reason']}", file=sys.stderr)

    if rq1.get("skipped") and rq2.get("skipped"):
        print("錯誤：RQ1 與 RQ2 皆無法比較（缺少 summary 檔案）。", file=sys.stderr)
        sys.exit(1)

    payload: Dict[str, Any] = {"RQ1": rq1, "RQ2": rq2}

    out_path: Path = args.output
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
        f.write("\n")
    print(f"已寫入：{out_path}")


if __name__ == "__main__":
    main()
