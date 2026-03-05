"""
使用 Plant 的 Analyst（conflict-analyzer skill）做需求衝突辨識評估。
與 result_baseline.py 相同：讀取 experiment/benchmark/cn_pairs.csv，逐筆預測 Conflict/Neutral，
計算 precision/recall/F1 並寫入 experiment/results/。
"""
import csv
import json
import sys
from pathlib import Path
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from dotenv import load_dotenv
from model import create_model
from store import Store
from agents.profile.analyst import AnalystAgent
from metric import Metric

BENCHMARK_DIR = Path(__file__).parent / "benchmark"
RESULTS_DIR = Path(__file__).parent / "results"

load_dotenv(BASE_DIR / "config" / ".env")


def get_analyst():
    """建立 Analyst（使用 config 的 model）。"""
    store = Store(BASE_DIR)
    config = store.load_config()
    model = create_model(
        provider=config.get("provider"),
        model_name=config.get("model"),
        temperature=config.get("temperature"),
    )
    return AnalystAgent(model), config.get("model", "unknown")


def _predict_one(analyst: AnalystAgent, idx: int, row: dict) -> tuple:
    """單筆：用 Text1/Text2 組出兩方 stakeholder 的 artifact，跑衝突辨識，推得 Conflict/Neutral。"""
    text1 = row["Text1"]
    text2 = row["Text2"]
    artifact = {
        "stakeholders": [
            {"name": "A", "text": [text1]},
            {"name": "B", "text": [text2]},
        ],
        "requirements": [],
        "system_models": {},
    }
    updated = analyst.run_conflict_detection(artifact)
    conflicts = [c for c in updated.get("conflicts", []) if (c.get("label") or "").strip() == "Conflict"]
    pred = "Conflict" if conflicts else "Neutral"
    return (
        idx,
        pred,
        {"text1": text1, "text2": text2, "true": row["Class"], "pred": pred},
    )


def run_conflict(analyst: AnalystAgent, model_name: str, count: int = 0, mode: str = "macro"):
    """與 result_baseline 相同流程：讀 cn_pairs.csv，逐筆預測，算指標，寫 results。"""
    csv_path = BENCHMARK_DIR / "cn_pairs.csv"
    if not csv_path.exists():
        print(f"錯誤：找不到 {csv_path}")
        return None

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

    def task(idx, row):
        return _predict_one(analyst, idx, row)

    done = 0
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_idx = {executor.submit(task, i, row): i for i, row in enumerate(data)}
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
                        "error": str(e),
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

    conflict_metrics = Metric.precision_recall_f1(y_true, y_pred, positive="Conflict")
    if mode == "macro":
        overall = Metric.macro(y_true, y_pred)["macro"]
    else:
        overall = Metric.micro(y_true, y_pred)

    metrics = {
        "mode": mode,
        "overall": overall,
        "conflict": conflict_metrics,
    }

    result = {
        "task": "conflict_detection",
        "model": f"plant_analyst_{model_name}",
        "total": total,
        "count": {
            "conflict": y_true.count("Conflict"),
            "neutral": y_true.count("Neutral"),
        },
        "metrics": metrics,
        "records": records,
    }

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%H%M%S")
    filepath = RESULTS_DIR / f"analyst_conflict_{model_name}_{ts}.json"
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"  已儲存: {filepath}")

    return result


if __name__ == "__main__":
    analyst, model_name = get_analyst()
    print("Analyst 衝突辨識評估（benchmark: cn_pairs.csv）")
    print()
    count_input = input("實驗幾筆資料 (0:全做): ").strip() or "0"
    count = int(count_input)
    run_conflict(analyst, model_name, count=count)
