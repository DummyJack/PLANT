import traceback
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from dotenv import load_dotenv
from flow.setup import Flow

from .config import build_flow, build_plant_cost_payload, load_rq2_config
from .utils import (
    build_type_rough_idea,
    build_type_stakeholders,
    build_pair_changed_flags,
    default_csv_path,
    extract_pair_preds_with_missing,
    extract_pair_review_preds_with_missing,
    extract_pre_meeting_details,
    incorrect_label_for,
    inject_supplemented_conflicts,
    load_rq2_dataset,
    print_multi_run_summary,
    supplement_missing_pair_predictions,
    sync_config_language,
)
from .records import (
    build_rq2_record_by_type,
    build_rq2_result_payload,
    scalar_metrics_for_summary,
    write_rq2_outputs,
)

RQ2_DIR = Path(__file__).resolve().parent.parent
BASE_DIR = RQ2_DIR.parent.parent
RESULTS_DIR = RQ2_DIR / "results"

load_dotenv(BASE_DIR / ".env")

def run_type_group_batch(
    flow: Flow,
    items: List[Tuple[int, Dict[str, Any]]],
    *,
    type_name: str,
    results_by_idx: Dict[int, Tuple[Optional[str], Dict[str, Any]]],
    meetings_by_type: Dict[str, Any],
) -> None:
    """同一 type 內：一次 pairwise 辨識 → 會前衝突複核。

    會議紀錄只會寫入 ``meetings_by_type[type_name]`` 一次；各資料列的 record 僅含 pairs。
    """
    n = len(items)
    if n == 0:
        return
    pair_id_prefix = "PAIR"
    max_stakeholders = int(flow.config.get("max_stakeholders", 5) or 5)
    stakeholders = build_type_stakeholders(type_name, max_stakeholders)

    requirements: List[Dict[str, Any]] = []
    for k in range(n):
        _, row = items[k]
        sh_a = stakeholders[(2 * k) % len(stakeholders)]["name"]
        sh_b = stakeholders[(2 * k + 1) % len(stakeholders)]["name"]
        requirements.append(
            {
                "id": f"{pair_id_prefix}-P{k}-a",
                "text": str(row.get("Text1") or ""),
                "proposed_by": "benchmark",
                "source_stakeholder": sh_a,
            }
        )
        requirements.append(
            {
                "id": f"{pair_id_prefix}-P{k}-b",
                "text": str(row.get("Text2") or ""),
                "proposed_by": "benchmark",
                "source_stakeholder": sh_b,
            }
        )

    artifact: Dict[str, Any] = {
        "rough_idea": build_type_rough_idea(type_name),
        "stakeholders": stakeholders,
        "scope": {"in_scope": [], "out_of_scope": [], "description": ""},
        "requirements": requirements,
        "conflicts": [],
        "feedback": {},
        "system_models": {},
        "open_questions": [],
        "decisions": [],
        "discussions": [],
        "meta": {
            "pairwise_only": True,
            "pair_count": n,
            "pair_id_prefix": pair_id_prefix,
            "enable_all_conflict_check": False,
            "requirements_proposed_by": "benchmark",
            "requirement_owner_type": type_name,
        },
    }
    sync_config_language(artifact)

    updated = flow.analyst_agent.run_conflict_detection(artifact)
    if not isinstance(updated, dict):
        raise TypeError(
            "flow.analyst_agent.run_conflict_detection 必須回傳 dict，"
            f"實得 {type(updated).__name__}"
        )
    analyst_preds, missing_before_supplement = extract_pair_preds_with_missing(updated, n)
    supplemented_labels: Dict[int, str] = {}
    unresolved_missing: List[int] = []
    if missing_before_supplement:
        supplemented_labels, unresolved_missing = supplement_missing_pair_predictions(
            flow, items, missing_before_supplement
        )
        for k, lb in supplemented_labels.items():
            if 0 <= k < n:
                analyst_preds[k] = lb
        inject_supplemented_conflicts(
            updated,
            pair_id_prefix=pair_id_prefix,
            supplemented_labels=supplemented_labels,
        )
        print(
            "Analyst: 漏判補判 "
            f"(missing={len(missing_before_supplement)}, "
            f"supplemented={len(supplemented_labels)}, "
            f"unresolved={len(unresolved_missing)})",
            flush=True,
        )
        if unresolved_missing:
            for k in unresolved_missing:
                if 0 <= k < n:
                    analyst_preds[k] = incorrect_label_for(items[k][1].get("Class"))
    analyst_conflict = sum(1 for p in analyst_preds if p == "Conflict")
    analyst_neutral = sum(1 for p in analyst_preds if p == "Neutral")
    print(
        f"Analyst: 衝突辨識（Conflict={analyst_conflict}, Neutral={analyst_neutral}）",
        flush=True,
    )
    updated = flow.meeting.run_pre_meeting_conflict_review(updated, round_num=1)
    if not isinstance(updated, dict):
        raise TypeError(
            "flow.meeting.run_pre_meeting_conflict_review 必須回傳 dict，"
            f"實得 {type(updated).__name__}"
        )

    preds, missing_pair_reviews, pair_reviews_by_index = extract_pair_review_preds_with_missing(updated, n)
    if missing_pair_reviews:
        fallback_preds, _ = extract_pair_preds_with_missing(updated, n)
        for k in missing_pair_reviews:
            if 0 <= k < n:
                preds[k] = fallback_preds[k]
    for k in unresolved_missing:
        if 0 <= k < n:
            preds[k] = incorrect_label_for(items[k][1].get("Class"))
            pair_reviews_by_index[k] = {
                "error": "unresolved_after_supplement",
                "forced_wrong_prediction": True,
                "final_label": preds[k],
            }
    changed_flags = build_pair_changed_flags(updated, n, preds)
    meeting_details = extract_pre_meeting_details(updated, round_num=1)
    if missing_before_supplement:
        meeting_details["missing_before_supplement"] = list(missing_before_supplement)
        meeting_details["supplemented_pair_indices"] = sorted(supplemented_labels.keys())
        meeting_details["supplement_unresolved_pair_indices"] = sorted(unresolved_missing)
    meetings_by_type[type_name] = meeting_details
    print("會前衝突再審查會議：", flush=True)
    decisions = meeting_details.get("decisions") or []
    if isinstance(decisions, list) and decisions:
        print("  會議決定：", flush=True)
        for dec in decisions:
            if not isinstance(dec, dict):
                continue
            cid = str(dec.get("id") or "").strip() or "-"
            to_label = str(dec.get("to_label") or dec.get("new_label") or "").strip() or "-"
            result = str(dec.get("result") or "").strip() or "-"
            reason = str(dec.get("reason") or "").strip()
            print(
                f"    - {cid}: {to_label} ({result})"
                + (f"；理由：{reason}" if reason else ""),
                flush=True,
            )
    else:
        print("  會議決定：（無）", flush=True)
    print("", flush=True)
    for k in range(n):
        gi, row = items[k]
        tkey = str(row.get("types") or type_name)
        results_by_idx[gi] = (
            preds[k],
            {
                tkey: {
                    "pairs": [
                        {
                            "text1": row["Text1"],
                            "text2": row["Text2"],
                            "is_changed": changed_flags[k],
                            "true": row["Class"],
                            "pred": preds[k],
                            "details": pair_reviews_by_index.get(k, {}),
                        }
                    ],
                },
            },
        )

def run_conflict(
    flow: Flow,
    model_name: str,
    count: int = 0,
    *,
    data_path: Optional[Path] = None,
):
    """執行衝突辨識實驗。

    - 依 CSV/JSON 的 types 分組；**同一 type 內**整批做一次 pairwise 辨識，再全組一次會前衝突複核。
    - data_path 為 None：使用預設 cn_100.csv（或 cn_pairs.csv）；亦可傳入 .json 陣列。
    - count > 0：只取前 count 筆。
    - record 輸出為 **陣列**：每個元素為 ``{ "<type 名稱>": { …, "pairs": [ … ] } }``，同一 type 僅一筆；
      會議欄位保留 round / changed_count / discussion_mode / participants / conversation，
      pair 決策理由整理到 pairs[].description 與 details。
    """
    try:
        if data_path is not None:
            data, data_file_label = load_rq2_dataset(Path(data_path).resolve())
        else:
            p = default_csv_path()
            if not p.exists():
                print(f"錯誤：找不到資料檔 {p}")
                return None
            data, data_file_label = load_rq2_dataset(p)
    except (OSError, ValueError) as e:
        print(f"錯誤：無法載入資料：{e}")
        return None

    if count > 0:
        data = data[:count]

    total = len(data)
    y_true = [row["Class"] for row in data]
    results_by_idx = {}
    grouped: Dict[str, list[tuple[int, dict]]] = {}
    for i, row in enumerate(data):
        g = str(row.get("types") or "Unknown")
        grouped.setdefault(g, []).append((i, row))

    meetings_by_type: Dict[str, Any] = {}
    for g, items in grouped.items():
        print(
            f"========== 類型：{g}（{len(items)} 筆）==========",
            flush=True,
        )
        try:
            run_type_group_batch(
                flow,
                items,
                type_name=str(g),
                results_by_idx=results_by_idx,
                meetings_by_type=meetings_by_type,
            )
        except Exception as e:
            print(f"\n✗ 類型「{g}」整批失敗: {e}", flush=True)
            print("  ✗ Traceback:", flush=True)
            print(traceback.format_exc().rstrip(), flush=True)
            fail_meeting = {
                "round": 1,
                "changed_count": 0,
                "discussion_mode": "",
                "participants": [],
                "conversation": [],
                "decisions": [],
                "error": str(e),
            }
            meetings_by_type.setdefault(str(g), fail_meeting)
            for i, row in items:
                results_by_idx[i] = (
                    None,
                    {
                        str(row.get("types") or g): {
                            "pairs": [
                                {
                                    "text1": row["Text1"],
                                    "text2": row["Text2"],
                                    "is_changed": False,
                                    "true": row["Class"],
                                    "pred": None,
                                    "details": {},
                                    "error": str(e),
                                }
                            ],
                        },
                    },
                )

    y_pred = []
    for i in range(total):
        pred = results_by_idx[i][0]
        y_pred.append(pred if pred is not None else "Neutral")
    record_by_type = build_rq2_record_by_type(
        grouped, meetings_by_type, results_by_idx
    )

    result = build_rq2_result_payload(
        model_name=str(model_name),
        data_file_label=data_file_label,
        y_true=y_true,
        y_pred=y_pred,
        grouped=grouped,
    )
    metrics = result.get("metrics", {}) if isinstance(result.get("metrics"), dict) else {}
    overall = metrics.get("overall", {}) if isinstance(metrics.get("overall"), dict) else {}
    conflict_class = metrics.get("conflict", {}) if isinstance(metrics.get("conflict"), dict) else {}
    by_type = (
        result.get("metrics_by_type", {})
        if isinstance(result.get("metrics_by_type"), dict)
        else {}
    )

    def _m(v: Any) -> float:
        try:
            return float(v or 0.0)
        except (TypeError, ValueError):
            return 0.0

    cost_payload = build_plant_cost_payload(flow)
    paths = write_rq2_outputs(
        prefix="Plant",
        results_dir=RESULTS_DIR,
        result=result,
        record=record_by_type,
        cost=cost_payload,
    )

    print("\n=== 執行結果 ===")
    print("【整體】")
    print(f"  總資料量: {total}")
    print(
        "  Overall : "
        f"P={_m(overall.get('precision')):.4f}, "
        f"R={_m(overall.get('recall')):.4f}, "
        f"F1={_m(overall.get('f1')):.4f}"
    )
    print(
        "  Conflict: "
        f"P={_m(conflict_class.get('precision')):.4f}, "
        f"R={_m(conflict_class.get('recall')):.4f}, "
        f"F1={_m(conflict_class.get('f1')):.4f}"
    )
    print("")
    print("【各 type 表現】")
    for g in sorted(by_type.keys()):
        row = by_type[g]
        o = row.get("overall", {})
        c = row.get("conflict", {})
        cnt = row.get("count", {})
        print(
            f"- {g} (n={row.get('total', 0)}, "
            f"C={int(cnt.get('conflict', 0) or 0)}, "
            f"N={int(cnt.get('neutral', 0) or 0)})"
        )
        print(
            "    Overall : "
            f"P={_m(o.get('precision')):.4f}, "
            f"R={_m(o.get('recall')):.4f}, "
            f"F1={_m(o.get('f1')):.4f}"
        )
        print(
            "    Conflict: "
            f"P={_m(c.get('precision')):.4f}, "
            f"R={_m(c.get('recall')):.4f}, "
            f"F1={_m(c.get('f1')):.4f}"
        )
    print("輸出檔案：")
    print(f"- result: {paths['result']}")
    print(f"- record: {paths['record']}")
    print(f"- cost:   {paths['cost']}")
    return {
        "result": result,
        "cost": cost_payload,
        "paths": paths,
    }

def run_experiments(
    *,
    count: int,
    runs: int,
    data_path: Optional[Path] = None,
) -> None:
    try:
        rq2_config = load_rq2_config()
    except Exception as e:
        print(f"錯誤：無法讀取 Plant/config.json：{e}")
        raise SystemExit(1) from e

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    run_scalar_metrics: List[Dict[str, float]] = []
    run_costs_usd: List[float] = []
    run_total_tokens: List[int] = []
    run_total_runtime_s: List[float] = []

    for run_idx in range(runs):
        print(f"\n=== Run {run_idx + 1}/{runs} ===")
        flow = build_flow(config=deepcopy(rq2_config))
        model_name = getattr(flow.agent_models.get("analyst"), "model_name", "unknown")
        run_output = run_conflict(flow, model_name, count=count, data_path=data_path)
        result = run_output.get("result", {}) if isinstance(run_output, dict) else {}
        cost_payload = run_output.get("cost", {}) if isinstance(run_output, dict) else {}
        run_scalar_metrics.append(scalar_metrics_for_summary(result))
        run_costs_usd.append(
            float(cost_payload.get("totals", {}).get("estimated_cost(USD)", 0.0) or 0.0)
        )
        run_total_tokens.append(
            int(cost_payload.get("totals", {}).get("total_tokens", 0) or 0)
        )
        run_total_runtime_s.append(
            float(cost_payload.get("totals", {}).get("run_time(s)", 0.0) or 0.0)
        )

    print_multi_run_summary(
        runs=runs,
        run_scalar_metrics=run_scalar_metrics,
        run_costs_usd=run_costs_usd,
        run_total_tokens=run_total_tokens,
        run_total_runtime_s=run_total_runtime_s,
    )
