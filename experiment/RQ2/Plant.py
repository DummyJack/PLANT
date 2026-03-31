# Plant 衝突辨識實驗結果（使用 Flow 與 RQ2 config）

import csv
import json
import sys
import tempfile
import traceback
from pathlib import Path
from datetime import datetime
from typing import Any, Dict

RQ2_DIR = Path(__file__).resolve().parent
EXP_DIR = RQ2_DIR.parent
BASE_DIR = EXP_DIR.parent
sys.path.insert(0, str(RQ2_DIR))
sys.path.insert(0, str(BASE_DIR))

from dotenv import load_dotenv
from flow import Flow
from metric import Metric
from utils import json_dump_no_scientific

DATA_DIR = RQ2_DIR
RESULTS_DIR = RQ2_DIR / "results"
CONFIG_PATH = RQ2_DIR / "config_RQ2.json"

load_dotenv(BASE_DIR / ".env")


class ExperimentLogger:
    """實驗用無輸出 logger（不寫 log 檔）。"""

    def info(self, *args, **kwargs):
        pass

    def warning(self, *args, **kwargs):
        pass

    def error(self, *args, **kwargs):
        pass


class ExperimentStore:
    """實驗用無 I/O store（不產生 project id 與 artifacts）。"""

    def __init__(self) -> None:
        self.project_id = "rq2_experiment"
        # AgendaRunner 會讀取 output_dir；不指向 repo 根目錄，避免誤讀既有 design_rationale.md
        self.output_dir = Path(tempfile.gettempdir()) / "plant_rq2_experiment_store"
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.project_dir = self.output_dir

    def save_artifact(self, data: Dict[str, Any]):
        pass

    def save_json(self, data: Dict[str, Any], filepath: str, indent: int = 2):
        pass

    def save_markdown(self, content: str, filename: str):
        pass

    def save_plantuml_files(self, model_data: Dict[str, Any]):
        pass

    def save_draft(self, content: str, version: int):
        pass

    def get_draft_version(self) -> int:
        return -1

    def load_draft(self, version: int):
        return None


def build_flow() -> Flow:
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        config = json.load(f)
    check_provider_model_mismatch(config)
    return Flow(config=config, store=ExperimentStore(), logger=ExperimentLogger())


def check_provider_model_mismatch(config: Dict[str, Any]) -> None:
    """檢查 provider/model 是否明顯不匹配；任一不匹配即拋 ValueError 中止。"""

    def _looks_openai(model: str) -> bool:
        m = (model or "").lower()
        return m.startswith("gpt-") or m.startswith("o")

    def _looks_gemini(model: str) -> bool:
        return (model or "").lower().startswith("gemini")

    mismatches: list[str] = []
    model_cfg = (config.get("agent_models") or {})
    for agent, info in model_cfg.items():
        if not isinstance(info, dict):
            continue
        provider = (info.get("provider") or "").lower()
        model = info.get("model") or ""
        if not provider or not model:
            continue
        bad = (
            (provider == "openai" and _looks_gemini(model))
            or (provider == "gemini" and _looks_openai(model))
        )
        if bad:
            mismatches.append(
                f"agent_models.{agent}: provider={provider!r}, model={model!r}"
            )

    if not mismatches:
        return
    detail = "\n".join(f"  - {line}" for line in mismatches)
    msg = f"provider/model 明顯不匹配（請修正 config 的 agent_models）：\n{detail}"
    raise ValueError(msg)


def sync_config_language(flow: Flow, artifact: Dict[str, Any]) -> None:
    """與完整 Flow.run 一致：依 config 設定各 agent 與 artifact.meta 語系。"""
    from utils import resolve_output_language

    lang = resolve_output_language(flow.config)
    flow.sync_output_language(lang, artifact)


def build_plant_cost_payload(flow: Flow) -> Dict[str, Any]:
    """彙總 Flow 內各 LLM 的 CostTracker（與 flow.finalize 的 cost_summary 結構相近）。"""
    cost_by_agent: Dict[str, Any] = {}
    for agent_name, m in flow.agent_models.items():
        if not hasattr(m, "costTracker"):
            continue
        cost_by_agent[agent_name] = m.costTracker.export_summary_dict()
    if not cost_by_agent:
        return {
            "method": "Plant",
            "project_id": getattr(flow.store, "project_id", ""),
            "agents": {},
            "totals": {
                "input_tokens": 0,
                "output_tokens": 0,
                "total_tokens": 0,
                "run_time(s)": 0.0,
                "estimated_cost(USD)": 0.0,
            },
        }
    totals = {
        "input_tokens": sum(int(v.get("input_tokens", 0) or 0) for v in cost_by_agent.values()),
        "output_tokens": sum(int(v.get("output_tokens", 0) or 0) for v in cost_by_agent.values()),
        "total_tokens": sum(int(v.get("total_tokens", 0) or 0) for v in cost_by_agent.values()),
        "run_time(s)": round(
            sum(float(v.get("run_time(s)", 0.0) or 0.0) for v in cost_by_agent.values()),
            3,
        ),
        "estimated_cost(USD)": round(
            sum(float(v.get("estimated_cost(USD)", 0.0) or 0.0) for v in cost_by_agent.values()),
            8,
        ),
    }
    return {
        "method": "Plant",
        "project_id": getattr(flow.store, "project_id", ""),
        "agents": cost_by_agent,
        "totals": totals,
    }


def run_flow_after_conflict_detection(flow: Flow, artifact: Dict[str, Any]) -> Dict[str, Any]:
    """沿用 Flow Phase 0 中 run_conflict_detection 之後的流程。"""
    mi = flow.config.get("max_iterations") or {}

    print(
        f"    → Expert：Phase0 複審 (expert_phase0 ≤ {mi.get('expert_phase0', 10)} 輪)"
    )
    review = flow.expert_agent.run_review_loop(
        artifact,
        max_iterations=mi.get("expert_phase0", 10),
    )
    if not isinstance(review, dict):
        raise TypeError(
            "flow.expert_agent.run_review_loop 必須回傳 dict，"
            f"實得 {type(review).__name__}"
        )
    review_issues = review.get("pending_issues", [])
    if review_issues:
        for issue in review_issues:
            if not isinstance(issue, dict):
                continue
            artifact.setdefault("open_questions", []).append(
                {
                    "from_agent": "expert",
                    "question": issue.get("description", ""),
                    "status": "pending",
                    "type": issue.get("type", "compliance_risk"),
                }
            )

    print(
        f"    → Modeler：系統模型 (modeler_phase0 ≤ {mi.get('modeler_phase0', 15)} 輪)"
    )
    model_data = flow.modeler_agent.generate_system_model(
        artifact["requirements"],
        artifact.get("stakeholders", []),
        max_iterations=mi.get("modeler_phase0", 15),
    )
    artifact["system_models"] = model_data

    print("    → Analyst：會前衝突複核 (run_pre_discussion_conflict_reassessment)")
    artifact = flow.run_pre_discussion_conflict_reassessment(
        artifact, stage="phase0_pre_meeting"
    )

    if flow.config.get("skip_phase0_draft"):
        print("    → Analyst：略過需求草稿 v0 (skip_phase0_draft)")
    else:
        print("    → Analyst：需求草稿 v0 (create_draft)")
        draft_md = flow.analyst_agent.create_draft(
            artifact,
            draft_version=0,
            recent_decisions_limit=flow.config.get("agenda_items", 5),
        )
        flow.store.save_draft(draft_md, version=0)
    return artifact


def predict_one(flow: Flow, idx: int, row: dict, *, total_samples: int) -> tuple:
    """單筆：requirements 先做衝突辨識，再跑該點之後的 Flow。"""
    print(f"\n── 樣本 {idx + 1}/{total_samples} ──")
    text1 = row["Text1"]
    text2 = row["Text2"]
    artifact = {
        "rough_idea": "RQ2 conflict detection",
        "stakeholders": [],
        "scope": {"in_scope": [], "out_of_scope": [], "description": ""},
        "requirements": [
            {"text": text1},
            {"text": text2},
        ],
        "conflicts": [],
        "feedback": {},
        "system_models": {},
        "open_questions": [],
        "decisions": [],
        "discussions": [],
        "meta": {},
    }
    print("  • 同步輸出語系 (sync_output_language)")
    sync_config_language(flow, artifact)
    print("  • Analyst：衝突辨識 (run_conflict_detection)")
    updated = flow.analyst_agent.run_conflict_detection(artifact)
    if not isinstance(updated, dict):
        raise TypeError(
            "flow.analyst_agent.run_conflict_detection 必須回傳 dict，"
            f"實得 {type(updated).__name__}"
        )
    updated = run_flow_after_conflict_detection(flow, updated)
    if not isinstance(updated, dict):
        raise TypeError(
            "run_flow_after_conflict_detection 必須回傳 dict，"
            f"實得 {type(updated).__name__}"
        )
    rounds = int(flow.config.get("rounds", 1) or 1)
    for round_num in range(1, rounds + 1):
        print(f"  • Round {round_num}/{rounds}：開會 (run_meeting_round)")
        updated = flow.run_meeting_round(updated, round_num)
        if not isinstance(updated, dict):
            raise TypeError(
                "flow.run_meeting_round 必須回傳 dict，"
                f"實得 {type(updated).__name__}"
            )

    labels = [
        (c.get("label") or "").strip()
        for c in (updated.get("conflicts", []) or [])
        if isinstance(c, dict)
    ]
    if any(lb == "Conflict" for lb in labels):
        pred = "Conflict"
    elif any(lb == "Neutral" for lb in labels):
        pred = "Neutral"
    else:
        pred = "Unknown"
    return idx, pred, {
        "text1": text1,
        "text2": text2,
        "true": row["Class"],
        "pred": pred,
        "labels": labels,
        "rounds_executed": rounds,
    }


def run_conflict(flow: Flow, model_name: str, count: int = 0):
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
        data = data[:count]

    total = len(data)
    y_true = [row["Class"] for row in data]
    results_by_idx = {}
    for i, row in enumerate(data):
        try:
            idx, pred, rec = predict_one(flow, i, row, total_samples=total)
            results_by_idx[idx] = (pred, rec)
        except Exception as e:
            print(f"\n── 樣本 {i + 1}/{total} ──\n  ✗ 錯誤: {e}")
            print("  ✗ Traceback:")
            print(traceback.format_exc().rstrip())
            results_by_idx[i] = (
                None,
                {
                    "text1": row["Text1"],
                    "text2": row["Text2"],
                    "true": row["Class"],
                    "pred": None,
                    "error": str(e),
                },
            )

    y_pred = []
    for i in range(total):
        pred = results_by_idx[i][0]
        y_pred.append(pred if pred is not None else "Unknown")
    records = [results_by_idx[i][1] for i in range(total)]

    n_conflict = y_true.count("Conflict")
    n_neutral = y_true.count("Neutral")
    n_unknown_pred = y_pred.count("Unknown")
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

    conflict_metrics = Metric.precision_recall_f1(y_true, y_pred, label="Conflict")
    metrics = {"mode": mode, "overall": overall, "conflict": conflict_metrics}

    result = {
        "task": "conflict_detection",
        "model": f"plant_flow_analyst_{model_name}",
        "total": total,
        "count": {
            "conflict": n_conflict,
            "neutral": n_neutral,
            "pred_unknown": n_unknown_pred,
            "minority_ratio": round(min(n_conflict, n_neutral) / total, 4) if total else 0.0,
        },
        "metrics": metrics,
    }

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%H%M%S")
    result_path = RESULTS_DIR / f"result_Plant_{ts}.json"
    record_path = RESULTS_DIR / f"record_Plant_{ts}.json"
    cost_path = RESULTS_DIR / f"cost_Plant_{ts}.json"
    with open(result_path, "w", encoding="utf-8") as f:
        json_dump_no_scientific(result, f, indent=2, ensure_ascii=False)
    with open(record_path, "w", encoding="utf-8") as f:
        json_dump_no_scientific(records, f, indent=2, ensure_ascii=False)
    with open(cost_path, "w", encoding="utf-8") as f:
        json_dump_no_scientific(
            build_plant_cost_payload(flow), f, indent=2, ensure_ascii=False
        )
    print(f"  已儲存: {result_path}")
    print(f"  已儲存: {record_path}")
    print(f"  已儲存: {cost_path}")
    return result


if __name__ == "__main__":
    flow = build_flow()
    model_name = getattr(flow.agent_models.get("analyst"), "model_name", "unknown")
    print("Flow(Analyst) 衝突辨識評估（benchmark: cn_pairs.csv）")
    print()
    count_input = input("實驗幾筆資料 (0:全做): ").strip() or "0"
    count = int(count_input)
    run_conflict(flow, model_name, count=count)
