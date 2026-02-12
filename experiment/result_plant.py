# 實驗結果 — Plant 系統（AnalystAgent）

import csv
import json
import sys
from pathlib import Path
from datetime import datetime

from dotenv import load_dotenv

# 載入環境變數 & 設定 import 路徑
BASE_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(BASE_DIR))
load_dotenv(dotenv_path=BASE_DIR / "config" / ".env")

from model import create_model
from agents.memory import Memory
from team.analyst import AnalystAgent
from metric import Metric

BENCHMARK_DIR = Path(__file__).parent / "benchmark"
RESULTS_DIR = Path(__file__).parent / "results"


# 載入 CSV 資料
def load_csv(count=0):
    csv_path = BENCHMARK_DIR / "cn_pairs.csv"
    data = []
    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            data.append(row)
    if count > 0:
        data = data[:count]
    return data


# 建立 AnalystAgent
def create_analyst(model_name="gpt-4o-mini", temperature=0):
    model = create_model(provider="openai", model_name=model_name, temperature=temperature)
    memory = Memory(model)
    analyst = AnalystAgent(model, memory=memory)
    return analyst


# 計算指標
def compute_metrics(y_true, y_pred):
    metrics_conflict = Metric.precision_recall_f1(y_true, y_pred, positive="Conflict")
    metrics_neutral = Metric.precision_recall_f1(y_true, y_pred, positive="Neutral")
    macro = {
        "precision": round((metrics_conflict["precision"] + metrics_neutral["precision"]) / 2, 4),
        "recall": round((metrics_conflict["recall"] + metrics_neutral["recall"]) / 2, 4),
        "f1": round((metrics_conflict["f1"] + metrics_neutral["f1"]) / 2, 4),
    }
    return {"macro": macro, "conflict": metrics_conflict}


# 衝突偵測實驗
def run_conflict(analyst: AnalystAgent, data: list):
    total = len(data)
    y_true = []
    y_pred = []
    records = []

    for i, row in enumerate(data):
        text1 = row["Text1"]
        text2 = row["Text2"]
        label = row["Class"]

        print(f"\r  conflict: {i + 1}/{total}", end="", flush=True)

        # 每筆清除短期記憶
        analyst.memory.clear_short_term()

        stakeholder_group = [
            {"name": "Stakeholder_A", "text": text1},
            {"name": "Stakeholder_B", "text": text2},
        ]

        try:
            result = analyst.analyze_conflict(stakeholder_group)
            pred = result.get("label") or "Neutral"
            reason = result.get("reason", "")
        except Exception as e:
            print(f"\n  [Error] Row {i}: {e}")
            pred = "Neutral"
            reason = f"error: {e}"

        y_true.append(label)
        y_pred.append(pred)
        records.append({
            "text1": text1,
            "text2": text2,
            "true": label,
            "pred": pred,
            "reason": reason,
        })

    print()

    # 計算指標
    metrics = compute_metrics(y_true, y_pred)

    result = {
        "task": "conflict_detection",
        "model": analyst.model.model_name,
        "total": total,
        "metrics": metrics,
        "records": records,
    }

    # 儲存
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%H%M%S")
    filepath = RESULTS_DIR / f"plant_{analyst.model.model_name}_{ts}.json"
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"  已儲存: {filepath}")

    return result


if __name__ == "__main__":
    count = int(input("實驗幾筆資料 (0:全做): ").strip() or "0")
    data = load_csv(count)
    print(f"  載入 {len(data)} 筆資料\n")

    analyst = create_analyst()
    result = run_conflict(analyst, data)