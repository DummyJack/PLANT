# 實驗結果 — Plant 系統（Round 1 Analyst + Round 2 Step 0 多方討論）

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
from agents import AgentRegistry
from agents.profile import UserAgent, AnalystAgent, ExpertAgent, MediatorAgent
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


# 建立多 Agent 系統
def create_system(model_name="gpt-4o-mini", temperature=0):
    """建立 Analyst / Expert / Mediator / User，模擬 Flow 的 agent 配置"""
    model = create_model(provider="openai", model_name=model_name, temperature=temperature)
    registry = AgentRegistry()

    user_agent = UserAgent(model, registry=registry)
    analyst = AnalystAgent(model, registry=registry)
    expert = ExpertAgent(
        model, registry=registry,
        doc_dir="doc", enable_web_search=False,
    )
    mediator = MediatorAgent(model, registry=registry)

    registry.register("user", user_agent)
    registry.register("analyst", analyst)
    registry.register("expert", expert)
    registry.register("mediator", mediator)

    return {
        "analyst": analyst,
        "mediator": mediator,
        "user": user_agent,
        "expert": expert,
        "registry": registry,
    }


# 衝突偵測實驗
def run_conflict(system: dict, data: list, mode: str = "macro"):
    analyst = system["analyst"]
    mediator = system["mediator"]
    registry = system["registry"]
    total = len(data)
    y_true = []
    records = []

    # Round 1: Analyst 逐筆衝突分析（含 Reflection）
    print("Round 1: Analyst 衝突分析")
    round1_groups = []

    for i, row in enumerate(data):
        text1 = row["Text1"]
        text2 = row["Text2"]
        label = row["Class"]

        print(f"\r  R1: {i + 1}/{total}", end="", flush=True)

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
            result = {
                "texts": {"Stakeholder_A": text1, "Stakeholder_B": text2},
                "label": pred, "reason": reason,
            }

        y_true.append(label)
        round1_groups.append(result)
        records.append({
            "text1": text1, "text2": text2,
            "true": label, "r1_pred": pred, "r1_reason": reason,
        })

    print()

    # Round 1 指標
    y_pred_r1 = [g.get("label") or "Neutral" for g in round1_groups]
    r1_conflict = Metric.precision_recall_f1(y_true, y_pred_r1, positive="Conflict")
    if mode == "macro":
        r1_overall = Metric.macro(y_true, y_pred_r1)["macro"]
    else:
        r1_overall = Metric.micro(y_true, y_pred_r1)
    print(f"  R1 Overall F1={r1_overall['f1']:.4f}  Conflict F1={r1_conflict['f1']:.4f}")

    # 以 Round 1 分析結果為最終結果（無檢視修正）
    final_groups = round1_groups

    # 更新 records
    for i, g in enumerate(final_groups):
        records[i]["final_pred"] = g.get("label") or "Neutral"
        records[i]["final_reason"] = g.get("reason", "")

    # Final 指標
    y_pred_final = [g.get("label") or "Neutral" for g in final_groups]
    final_conflict = Metric.precision_recall_f1(y_true, y_pred_final, positive="Conflict")
    if mode == "macro":
        final_overall = Metric.macro(y_true, y_pred_final)["macro"]
    else:
        final_overall = Metric.micro(y_true, y_pred_final)
    print(f"  Final Overall F1={final_overall['f1']:.4f}  Conflict F1={final_conflict['f1']:.4f}")

    # 組裝結果
    metrics = {
        "mode": mode,
        "round1": {
            "overall": r1_overall,
            "conflict": r1_conflict,
        },
        "final": {
            "overall": final_overall,
            "conflict": final_conflict,
        },
    }

    result = {
        "task": "conflict_detection",
        "model": analyst.model.model_name,
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
    filepath = RESULTS_DIR / f"plant_conflict_{analyst.model.model_name}_{ts}.json"
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"\n  已儲存: {filepath}")

    return result


if __name__ == "__main__":
    count = int(input("實驗幾筆資料 (0:全做): ").strip() or "0")
    data = load_csv(count)
    system = create_system()
    result = run_conflict(system, data)
