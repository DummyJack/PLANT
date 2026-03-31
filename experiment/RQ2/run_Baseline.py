# 基準方法衝突辨識實驗結果

import csv
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from datetime import datetime

RQ2_DIR = Path(__file__).resolve().parent
BASE_DIR = RQ2_DIR.parent.parent
sys.path.insert(0, str(BASE_DIR))
from baseline import BaselineModel
from metric import Metric
from utils import json_dump_no_scientific

# 資料與結果路徑
DATA_DIR = RQ2_DIR
RESULTS_DIR = RQ2_DIR / "results"

# Baseline 專用模型：openai 或 gemini
BASELINE_PROVIDER = "openai"
BASELINE_MODEL = "gpt-4o-mini"
BASELINE_TEMPERATURE = 0


def build_baseline_cost_payload(model: BaselineModel) -> dict:
    agent = model.cost_tracker.export_summary_dict()
    return {
        "method": "Baseline",
        "agents": {"baseline": agent},
        "totals": {
            "input_tokens": agent["input_tokens"],
            "output_tokens": agent["output_tokens"],
            "total_tokens": agent["total_tokens"],
            "run_time(s)": agent["run_time(s)"],
            "estimated_cost(USD)": agent["estimated_cost(USD)"],
        },
    }


# 衝突測試
def run_conflict(model: BaselineModel, count: int = 0):
    csv_path = DATA_DIR / "cn_pairs.csv"
    data = []
    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            data.append(row)

    if count > 0:
        data = data[:count]

    total = len(data)
    y_true = [row["Class"] for row in data]
    results_by_idx = {}
    max_workers = min(6, total) or 1

    def run(idx: int, row: dict) -> tuple:
        text1 = row["Text1"]
        text2 = row["Text2"]
        pred = model.detect_conflict(text1, text2)
        return (
            idx,
            pred,
            {"text1": text1, "text2": text2, "true": row["Class"], "pred": pred},
        )

    done = 0
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_idx = {
            executor.submit(run, i, row): i for i, row in enumerate(data)
        }
        for future in as_completed(future_to_idx):
            idx = future_to_idx[future]
            try:
                i, pred, rec = future.result()
                results_by_idx[i] = (pred, rec)
            except Exception as e:
                results_by_idx[idx] = (
                    None,
                    {
                        "text1": data[idx]["Text1"],
                        "text2": data[idx]["Text2"],
                        "true": data[idx]["Class"],
                        "pred": None,
                    },
                )
            done += 1
            print(f"\r  conflict: {done}/{total}", end="", flush=True)

    y_pred = []
    for i in range(total):
        pred = results_by_idx[i][0]
        y_pred.append(pred if pred is not None else "Neutral")
    records = [results_by_idx[i][1] for i in range(total)]
    print()

    # 計算指標
    # 1. 整體：資料不平衡用 macro，平衡用 precision_recall_f1（各類 P/R/F1）
    n_conflict = y_true.count("Conflict")
    n_neutral = y_true.count("Neutral")
    minor_ratio = min(n_conflict, n_neutral) / total if total else 0
    is_balanced = minor_ratio >= 0.3  # 少數類佔比 >= 30% 視為平衡
    mode = "precision_recall_f1" if is_balanced else "macro"
    print(f"  整體計算方式: {mode} (少數類佔比 {minor_ratio:.1%})")

    if mode == "macro":
        overall = Metric.macro(y_true, y_pred)["macro"]
    else:
        labels = sorted(set(y_true) | set(y_pred))
        overall = {
            label: Metric.precision_recall_f1(y_true, y_pred, label=label)
            for label in labels
        }

    # 2. Conflict class 的 precision / recall / f1
    conflict_metrics = Metric.precision_recall_f1(y_true, y_pred, label="Conflict")

    metrics = {
        "mode": mode,
        "overall": overall,
        "conflict": conflict_metrics,
    }

    result = {
        "task": "conflict_detection",
        "model": f"{getattr(model, 'provider', 'openai')}_{model.model_name}",
        "total": total,
        "count": {
            "conflict": n_conflict,
            "neutral": n_neutral,
            "minority_ratio": round(min(n_conflict, n_neutral) / total, 4) if total else 0.0,
        },
        "metrics": metrics,
    }

    # 儲存：結果、records、成本
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%H%M%S")
    result_path = RESULTS_DIR / f"result_Baseline_{ts}.json"
    record_path = RESULTS_DIR / f"record_Baseline_{ts}.json"
    cost_path = RESULTS_DIR / f"cost_Baseline_{ts}.json"
    with open(result_path, "w", encoding="utf-8") as f:
        json_dump_no_scientific(result, f, indent=2, ensure_ascii=False)
    with open(record_path, "w", encoding="utf-8") as f:
        json_dump_no_scientific(records, f, indent=2, ensure_ascii=False)
    with open(cost_path, "w", encoding="utf-8") as f:
        json_dump_no_scientific(
            build_baseline_cost_payload(model), f, indent=2, ensure_ascii=False
        )
    print(f"  已儲存: {result_path}")
    print(f"  已儲存: {record_path}")
    print(f"  已儲存: {cost_path}")

    return result


if __name__ == "__main__":
    model = BaselineModel(
        provider=BASELINE_PROVIDER,
        model_name=BASELINE_MODEL,
        temperature=float(BASELINE_TEMPERATURE),
    )
    print(f"Baseline provider={model.provider} model={model.model_name}")

    count = int(input("實驗幾筆資料 (0:全做): ").strip() or "0")
    run_conflict(model, count=count)
