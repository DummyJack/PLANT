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
from agents import Memory, AgentRegistry
from team import UserAgent, AnalystAgent, ExpertAgent, MediatorAgent
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

    memories = {
        "user": Memory(model),
        "analyst": Memory(model),
        "expert": Memory(model),
        "mediator": Memory(model),
    }

    user_agent = UserAgent(model, memory=memories["user"], registry=registry)
    analyst = AnalystAgent(model, memory=memories["analyst"], registry=registry)
    expert = ExpertAgent(
        model, memory=memories["expert"], registry=registry,
        doc_dir="doc", enable_web_search=False,
    )
    mediator = MediatorAgent(model, memory=memories["mediator"], registry=registry)

    registry.register("user", user_agent, "利害關係人模擬專家")
    registry.register("analyst", analyst, "需求分析師，負責衝突分析")
    registry.register("expert", expert, "領域專家")
    registry.register("mediator", mediator, "需求調解主持人")

    # 讀取 config 中的 reflection 設定
    config_path = BASE_DIR / "config" / "config.json"
    if config_path.exists():
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)
        for agent in [user_agent, analyst, expert, mediator]:
            agent.react_max_steps = config.get("react_max_steps", 3)
            agent.reflection_max_retries = config.get("reflection_max_retries", 1)

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

    # Round 2 Step 0: Analyst 重新檢視 + 多方討論修正
    print("\nRound 2 Step 0: Analyst 重新檢視 + 多方討論")
    analyst.memory.clear_short_term()
    concerns = analyst.review_analysis(round1_groups)
    corrections = []

    if concerns:
        print(f"  Analyst 提出 {len(concerns)} 項疑慮，進入討論")

        for ci, concern in enumerate(concerns, 1):
            idx = concern.get("index", "?")
            original = concern.get("original_label", "?")
            suggested = concern.get("suggested_label", "?")
            reason = concern.get("reason", "")

            print(f"\r  R2 討論: {ci}/{len(concerns)} [{idx}] {original}→{suggested}", end="", flush=True)

            topic = {
                "id": f"Review-{ci:02d}",
                "title": f"衝突分析檢視：第 {idx} 筆（{original} → {suggested}?）",
                "description": (
                    f"Analyst 認為第 {idx} 筆分析結果可能有誤。\n"
                    f"原判斷: {original}\n建議修正為: {suggested}\n理由: {reason}"
                ),
                "type": "refinement",
                "discussion_mode": "sequential",
                "participants": ["user", "analyst", "expert"],
                "speaking_order": ["user", "analyst", "expert"],
            }

            try:
                contrib = mediator.moderate_sequential(topic, registry)
                resolution = mediator.synthesize_and_resolve(topic, contrib)

                if resolution.get("resolution") == "agreed":
                    corrections.append({
                        "index": idx,
                        "corrected_label": suggested,
                        "corrected_reason": resolution.get("summary", reason),
                    })
            except Exception as e:
                print(f"\n  [Error] Discussion {ci}: {e}")

        print()
    else:
        print("  Analyst 無疑慮")

    # 套用修正
    if corrections:
        final_groups = analyst.apply_corrections(round1_groups, corrections)
        print(f"  套用 {len(corrections)} 筆修正")
    else:
        final_groups = round1_groups
        print("  無修正")

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
        "corrections_count": len(corrections),
        "concerns_count": len(concerns) if concerns else 0,
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
