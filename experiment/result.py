# 執行結果

import csv
import json
from pathlib import Path
from datetime import datetime

from baseline import BaselineModel
from metric import Metric

BENCHMARK_DIR = Path(__file__).parent / "benchmark"
RESULTS_DIR = Path(__file__).parent / "results"


# 執行 cn_pairs 衝突偵測測試
# count: 要做幾筆，0 為全做
def run_conflict(model: BaselineModel, count: int = 0):
    csv_path = BENCHMARK_DIR / "cn_pairs.csv"
    data = []
    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            data.append(row)

    if count > 0:
        data = data[:count]

    total = len(data)
    y_true = []
    y_pred = []
    records = []

    for i, row in enumerate(data):
        text1 = row["Text1"]
        text2 = row["Text2"]
        label = row["Class"]

        print(f"\r  conflict: {i + 1}/{total}", end="", flush=True)
        pred = model.detect_conflict(text1, text2)

        y_true.append(label)
        y_pred.append(pred)
        records.append({
            "text1": text1,
            "text2": text2,
            "true": label,
            "pred": pred,
        })

    print()

    # 計算指標
    # Macro: Conflict 和 Neutral 各自算再取平均
    metrics_conflict = Metric.precision_recall_f1(y_true, y_pred, positive="Conflict")
    metrics_neutral = Metric.precision_recall_f1(y_true, y_pred, positive="Neutral")
    macro = {
        "precision": round((metrics_conflict["precision"] + metrics_neutral["precision"]) / 2, 4),
        "recall": round((metrics_conflict["recall"] + metrics_neutral["recall"]) / 2, 4),
        "f1": round((metrics_conflict["f1"] + metrics_neutral["f1"]) / 2, 4),
    }

    result = {
        "task": "conflict_detection",
        "model": model.model_name,
        "total": total,
        "metrics": {
            "macro": macro,
            "conflict": metrics_conflict,
        },
        "records": records,
    }

    # 儲存
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%H%M%S")
    filepath = RESULTS_DIR / f"conflict_{model.model_name}_{ts}.json"
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"  已儲存: {filepath}")

    return result


# 執行 PlantUCD 類別圖生成測試
# count: 要做幾筆，0 為全做
def run_plantuml(model: BaselineModel, count: int = 0):
    json_path = BENCHMARK_DIR / "PlantUCD_dataset_test.json"
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    if count > 0:
        data = data[:count]

    total = len(data)
    records = []

    for i, item in enumerate(data):
        human_lang = item["HumanLang"]
        expected_plantuml = item.get("PlantUML", "")

        print(f"\r  plantuml: {i + 1}/{total}", end="", flush=True)
        pred = model.generate_plantuml(human_lang)

        records.append({
            "human_lang": human_lang,
            "expected_plantuml": expected_plantuml,
            "generated_plantuml": pred.get("plantuml", pred.get("PlantUML", "")),
        })

    print()

    result = {
        "task": "plantuml_generation",
        "model": model.model_name,
        "total": total,
        "records": records,
    }

    # 儲存
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%H%M%S")
    filepath = RESULTS_DIR / f"plantuml_{model.model_name}_{ts}.json"
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"  已儲存: {filepath}")

    return result


if __name__ == "__main__":
    model = BaselineModel()

    task = input("選擇以下實驗: ").strip()
    print()
    print("1. 做需求衝突")
    print("2. 做 UML Model")
    print("0. 全部都要做")

    if task in ("0", "1"):
        count = int(input("實驗幾筆資料 (0:全做): ").strip() or "0")
        run_conflict(model, count=count)

    if task in ("0", "2"):
        count = int(input("實驗幾筆資料 (0:全做): ").strip() or "0")
        run_plantuml(model, count=count)
