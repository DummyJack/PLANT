# 執行結果

import csv
import json
from pathlib import Path
from datetime import datetime

from baseline import BaselineModel
from metric import Metric

BENCHMARK_DIR = Path(__file__).parent / "benchmark"
RESULTS_DIR = Path(__file__).parent / "results"


# 衝突測試
def run_conflict(model: BaselineModel, count: int = 0, mode: str = "macro"):
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

    # 計算指標：conflict 永遠算，overall 根據 mode 決定
    conflict_metrics = Metric.precision_recall_f1(y_true, y_pred, positive="Conflict")
    if mode == "macro":
        overall = Metric.macro(y_true, y_pred)["macro"]
    elif mode == "micro":
        overall = Metric.micro(y_true, y_pred)

    metrics = {
        "mode": mode,
        "overall": overall,
        "conflict": conflict_metrics,
    }

    result = {
        "task": "conflict_detection",
        "model": model.model_name,
        "total": total,
        "count": {
            "conflict": y_true.count("Conflict"),
            "neutral": y_true.count("Neutral"),
        },
        "metrics": metrics,
        "records": records,
    }

    # 儲存
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%H%M%S")
    filepath = RESULTS_DIR / f"baseline_conflict_{model.model_name}_{ts}.json"
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"  已儲存: {filepath}")

    return result


# PlantUCD 類別圖生成測試
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

    print("1. 需求衝突")
    print("2. PlantUML 類別圖生成")
    print("0. 全部都要做")
    print()
    task = input("選擇實驗: ").strip()

    if task in ("0", "1"):
        count = int(input("實驗幾筆資料 (0:全做): ").strip() or "0")
        run_conflict(model, count=count)

    if task in ("0", "2"):
        count = int(input("實驗幾筆資料 (0:全做): ").strip() or "0")
        run_plantuml(model, count=count)
