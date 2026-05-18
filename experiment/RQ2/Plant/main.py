import traceback
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from dotenv import load_dotenv
from flow.setup import Flow
from storage.artifact import conflict_payload, requirements_payload

from .config import build_flow, build_plant_cost_payload, load_rq2_config
from .utils import (
    build_type_rough_idea,
    build_pair_changed_flags,
    build_pair_review_details,
    default_csv_path,
    extract_conflict_review_details,
    extract_pair_preds_with_missing,
    load_rq2_dataset,
    print_multi_run_summary,
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
    conflict_artifact: Dict[str, Any],
    requirements_artifact: Dict[str, Any],
) -> None:
    """同一 type 內：一次 pairwise 辨識 → 衝突複核。

    會議紀錄只會寫入 ``meetings_by_type[type_name]`` 一次；各資料列的 record 僅含 pairs。
    """
    n = len(items)
    if n == 0:
        return
    requirements: List[Dict[str, Any]] = []
    for k in range(n):
        _, row = items[k]
        requirements.append(
            {
                "id": f"URL-{(k * 2) + 1}",
                "text": str(row.get("Text1") or ""),
                "source": "benchmark",
                "types": type_name,
            }
        )
        requirements.append(
            {
                "id": f"URL-{(k * 2) + 2}",
                "text": str(row.get("Text2") or ""),
                "source": "benchmark",
                "types": type_name,
            }
        )

    artifact: Dict[str, Any] = {
        "rough_idea": build_type_rough_idea(type_name),
        "URL": requirements,
        "conflict": {"pairs": [], "multiple": []},
    }
    sync_config_language(artifact, write_artifact_meta=False)

    updated = flow.analyst_agent.run_pairwise_conflict_detection(artifact)
    if not isinstance(updated, dict):
        raise TypeError(
            "flow.analyst_agent.run_pairwise_conflict_detection 必須回傳 dict，"
            f"實得 {type(updated).__name__}"
        )
    analyst_preds, missing_before_review = extract_pair_preds_with_missing(updated, n)
    if missing_before_review:
        raise RuntimeError(
            f"RQ2 conflict detection 仍缺少 pair_index: {missing_before_review}"
        )
    analyst_conflict = sum(1 for p in analyst_preds if p == "Conflict")
    analyst_neutral = sum(1 for p in analyst_preds if p == "Neutral")
    print(
        f"Analyst: 衝突辨識（Conflict={analyst_conflict}, Neutral={analyst_neutral}）",
        flush=True,
    )
    updated = flow.meeting.run_conflict_review(updated, round_num=1)
    if not isinstance(updated, dict):
        raise TypeError(
            "flow.meeting.run_conflict_review 必須回傳 dict，"
            f"實得 {type(updated).__name__}"
        )

    preds, missing_after_review = extract_pair_preds_with_missing(updated, n)
    if missing_after_review:
        missing_ids = [f"PAIR-{k + 1}" for k in missing_after_review]
        raise RuntimeError(f"RQ2 conflict review 後仍缺少最終標籤: {missing_ids}")
    details_by_index = build_pair_review_details(updated, n)
    for k in range(n):
        details = details_by_index.get(k)
        if 0 <= k < len(preds) and isinstance(details, dict):
            final_label = str(details.get("final_label") or "").strip()
            if final_label in {"Conflict", "Neutral"}:
                preds[k] = final_label
    changed_flags = build_pair_changed_flags(updated, n)
    meeting_details = extract_conflict_review_details(updated, round_num=1)
    meetings_by_type[type_name] = meeting_details
    print("衝突再審查會議：", flush=True)
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
        pair_details = details_by_index.get(k, {})
        review_details = pair_details.get("details") if isinstance(pair_details, dict) else {}
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
                            "details": pair_details,
                        }
                    ],
                },
            },
        )
    payload = conflict_payload(updated)
    req_id_map: Dict[str, str] = {}
    remapped_requirements: List[Dict[str, Any]] = []
    for req in requirements:
        old_id = str(req.get("id") or "").strip()
        new_id = f"REQ-{len(requirements_artifact['requirements']) + len(remapped_requirements) + 1}"
        req_id_map[old_id] = new_id
        item = dict(req)
        item["id"] = new_id
        remapped_requirements.append(item)
    exported_requirements = requirements_payload({"requirements": remapped_requirements})
    requirements_artifact["requirements"].extend(
        exported_requirements.get("requirements", []) or []
    )

    for pair in payload.get("pairs", []) or []:
        item = dict(pair)
        item["id"] = f"PAIR-{len(conflict_artifact['pairs']) + 1}"
        remapped_refs: List[Dict[str, Any]] = []
        for req in item.get("requirements") or []:
            if not isinstance(req, dict):
                continue
            req_row = dict(req)
            old_req_id = str(req_row.get("id") or "").strip()
            if old_req_id in req_id_map:
                req_row["id"] = req_id_map[old_req_id]
            remapped_refs.append(req_row)
        if remapped_refs:
            item["requirements"] = remapped_refs
        conflict_artifact["pairs"].append(item)

def run_conflict(
    flow: Flow,
    model_name: str,
    count: int = 0,
    *,
    data_path: Optional[Path] = None,
    scenario: Optional[str] = None,
    scenarios: Optional[List[str]] = None,
):
    """執行衝突辨識實驗。

    - 依 CSV/JSON 的 types 分組；**同一 type 內**整批做一次 pairwise 辨識，再全組一次衝突複核。
    - data_path 為 None：使用預設 cn_pairs.csv；亦可傳入 .json 陣列。
    - count > 0：只取前 count 筆。
    - record 輸出為 type-indexed object：``{ "<type 名稱>": [pair, ...] }``，同一 type 僅一筆。
    - conflict 輸出只保留主流程 conflict.json 的 pairs 區塊：``{"pairs": [...]}``。
    """
    try:
        if data_path is not None:
            data, _ = load_rq2_dataset(Path(data_path).resolve())
        else:
            p = default_csv_path()
            if not p.exists():
                print(f"錯誤：找不到資料檔 {p}")
                return None
            data, _ = load_rq2_dataset(p)
    except (OSError, ValueError) as e:
        print(f"錯誤：無法載入資料：{e}")
        return None

    selected_scenarios = [
        str(item).strip()
        for item in (scenarios or [])
        if str(item or "").strip()
    ]
    selected_scenario = str(scenario or "").strip()
    if selected_scenario and not selected_scenarios:
        selected_scenarios = [selected_scenario]
    if selected_scenarios:
        selected_set = set(selected_scenarios)
        data = [
            row
            for row in data
            if (str(row.get("types") or "Unknown").strip() or "Unknown") in selected_set
        ]
        if not data:
            print(f"錯誤：找不到情境/type：{', '.join(selected_scenarios)}")
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
    conflict_artifact: Dict[str, Any] = {"pairs": []}
    requirements_artifact: Dict[str, Any] = {"requirements": []}
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
                conflict_artifact=conflict_artifact,
                requirements_artifact=requirements_artifact,
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
        if pred not in {"Conflict", "Neutral"}:
            raise RuntimeError(f"RQ2 第 {i + 1} 筆缺少有效 pred")
        y_pred.append(pred)
    record_by_type = build_rq2_record_by_type(
        grouped, meetings_by_type, results_by_idx
    )
    result = build_rq2_result_payload(
        model_name=str(model_name),
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

    def m(v: Any) -> float:
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
        conflict=conflict_artifact,
        requirements=requirements_artifact,
    )

    print("\n=== 執行結果 ===")
    print("【整體】")
    print(f"  總資料量: {total}")
    print(
        "  Overall : "
        f"P={m(overall.get('precision')):.4f}, "
        f"R={m(overall.get('recall')):.4f}, "
        f"F1={m(overall.get('f1')):.4f}"
    )
    print(
        "  Conflict: "
        f"P={m(conflict_class.get('precision')):.4f}, "
        f"R={m(conflict_class.get('recall')):.4f}, "
        f"F1={m(conflict_class.get('f1')):.4f}"
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
            f"P={m(o.get('precision')):.4f}, "
            f"R={m(o.get('recall')):.4f}, "
            f"F1={m(o.get('f1')):.4f}"
        )
        print(
            "    Conflict: "
            f"P={m(c.get('precision')):.4f}, "
            f"R={m(c.get('recall')):.4f}, "
            f"F1={m(c.get('f1')):.4f}"
        )
    print("輸出檔案：")
    print(f"- result: {paths['result']}")
    print(f"- record: {paths['record']}")
    print(f"- cost:   {paths['cost']}")
    print(f"- conflict: {paths['conflict']}")
    print(f"- requirements: {paths['requirements']}")
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
    scenario: Optional[str] = None,
    scenarios: Optional[List[str]] = None,
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
        run_output = run_conflict(
            flow,
            model_name,
            count=count,
            data_path=data_path,
            scenario=scenario,
            scenarios=scenarios,
        )
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
