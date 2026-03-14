# Plant 衝突辨識實驗結果

import csv
import json
import random
import sys
from pathlib import Path
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

# 專案根目錄（Plant）與 RQ2、experiment 目錄
RQ2_DIR = Path(__file__).resolve().parent
EXP_DIR = RQ2_DIR.parent   # experiment
BASE_DIR = EXP_DIR.parent  # Plant
sys.path.insert(0, str(BASE_DIR))
sys.path.insert(0, str(EXP_DIR))  # 供 metric 等 experiment 模組

from dotenv import load_dotenv
from model import create_model
from agents.profile.analyst import AnalystAgent
from metric import Metric

# 資料與結果路徑（cn_pairs.csv、config 在 RQ2 目錄下）
DATA_DIR = RQ2_DIR
RESULTS_DIR = RQ2_DIR / "results"
CONFIG_PATH = RQ2_DIR / "config_RQ2.json"

load_dotenv(BASE_DIR / "config" / ".env")


def get_analyst():
    """建立 Analyst（使用 RQ2 的 config_RQ2.json）。"""
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        config = json.load(f)
    model = create_model(
        provider=config.get("provider"),
        model_name=config.get("model"),
        temperature=config.get("temperature"),
    )
    return AnalystAgent(model), config.get("model", "unknown")


def _predict_one(analyst: AnalystAgent, idx: int, row: dict) -> tuple:
    """單筆：用 Text1/Text2 當兩筆需求放進 requirements，跑衝突辨識，推得 Conflict/Neutral。"""
    text1 = row["Text1"]
    text2 = row["Text2"]
    artifact = {
        "stakeholders": [],
        "requirements": [
            {"id": "R1", "text": text1},
            {"id": "R2", "text": text2},
        ],
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


def run_conflict(analyst: AnalystAgent, model_name: str, count: int = 0):
    """與 result_baseline 相同流程：讀 cn_pairs.csv，逐筆預測，算指標，寫 results。"""
    csv_path = DATA_DIR / "cn_pairs.csv"
    if not csv_path.exists():
        print(f"錯誤：找不到 {csv_path}")
        return None

    data = []
    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            data.append(row)

    if count > 0:
        sample_mode = input("取樣方式 (1:前N筆, 2:隨機N筆) [1]: ").strip() or "1"
        if sample_mode == "2":
            data = random.sample(data, min(count, len(data)))
        else:
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

    # 整體：資料不平衡用 macro，平衡用 precision_recall_f1（各類 P/R/F1）
    n_conflict = y_true.count("Conflict")
    n_neutral = y_true.count("Neutral")
    minor_ratio = min(n_conflict, n_neutral) / total if total else 0
    is_balanced = minor_ratio >= 0.3
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

    # Conflict class 的 precision / recall / f1
    conflict_metrics = Metric.precision_recall_f1(y_true, y_pred, label="Conflict")

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
            "conflict": n_conflict,
            "neutral": n_neutral,
            "minority_ratio": round(min(n_conflict, n_neutral) / total, 4) if total else 0.0,
        },
        "metrics": metrics,
    }

    # 儲存：結果與 records 分開
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%H%M%S")
    result_path = RESULTS_DIR / f"result_Plant_{ts}.json"
    record_path = RESULTS_DIR / f"record_Plant_{ts}.json"
    with open(result_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    with open(record_path, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)
    print(f"  已儲存: {result_path}")
    print(f"  已儲存: {record_path}")

    return result


if __name__ == "__main__":
    analyst, model_name = get_analyst()
    print("Analyst 衝突辨識評估（benchmark: cn_pairs.csv）")
    print()
    count_input = input("實驗幾筆資料 (0:全做): ").strip() or "0"
    count = int(count_input)
    run_conflict(analyst, model_name, count=count)
