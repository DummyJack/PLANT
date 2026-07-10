# Provides RQ2 Plant experiment main helpers.
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
    next_result_index,
    scalar_metrics_for_summary,
    write_rq2_outputs,
)

RQ2_DIR = Path(__file__).resolve().parent.parent
BASE_DIR = RQ2_DIR.parent.parent
RESULTS_DIR = RQ2_DIR / "results"
OUTPUT_PREFIX = "Plant"

load_dotenv(BASE_DIR / ".env")


def model_file_prefix(provider: str) -> str:
    normalized = str(provider or "").strip().lower()
    if normalized == "openai":
        return "gpt"
    if normalized in {"gemini", "claude"}:
        return normalized
    return normalized or "model"


def plant_model_file_prefix(config: Dict[str, Any]) -> str:
    agent_models = config.get("agent_models") if isinstance(config.get("agent_models"), dict) else {}
    default_cfg = agent_models.get("default") if isinstance(agent_models.get("default"), dict) else {}
    provider = str(default_cfg.get("provider") or "").strip()
    if not provider:
        for row in agent_models.values():
            if isinstance(row, dict) and str(row.get("provider") or "").strip():
                provider = str(row.get("provider") or "").strip()
                break
    return model_file_prefix(provider)


def cost_summary_diff(before: Dict[str, Any], after: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "model": str(after.get("model") or before.get("model") or ""),
        "input_tokens": max(0, int(after.get("input_tokens", 0) or 0) - int(before.get("input_tokens", 0) or 0)),
        "output_tokens": max(0, int(after.get("output_tokens", 0) or 0) - int(before.get("output_tokens", 0) or 0)),
        "total_tokens": max(0, int(after.get("total_tokens", 0) or 0) - int(before.get("total_tokens", 0) or 0)),
        "run_time(s)": round(
            max(
                0.0,
                float(after.get("run_time(s)", 0.0) or 0.0)
                - float(before.get("run_time(s)", 0.0) or 0.0),
            ),
            3,
        ),
        "estimated_cost(USD)": round(
            max(
                0.0,
                float(after.get("estimated_cost(USD)", 0.0) or 0.0)
                - float(before.get("estimated_cost(USD)", 0.0) or 0.0),
            ),
            8,
        ),
    }


def cost_totals(rows: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    return {
        "input_tokens": sum(int(v.get("input_tokens", 0) or 0) for v in rows.values()),
        "output_tokens": sum(int(v.get("output_tokens", 0) or 0) for v in rows.values()),
        "total_tokens": sum(int(v.get("total_tokens", 0) or 0) for v in rows.values()),
        "run_time(s)": round(sum(float(v.get("run_time(s)", 0.0) or 0.0) for v in rows.values()), 3),
        "estimated_cost(USD)": round(
            sum(float(v.get("estimated_cost(USD)", 0.0) or 0.0) for v in rows.values()),
            8,
        ),
    }


def current_cost_snapshot(flow: Flow) -> Dict[str, Dict[str, Any]]:
    rows: Dict[str, Dict[str, Any]] = {}
    for agent_name, model in flow.agent_models.items():
        if hasattr(model, "costTracker"):
            rows[agent_name] = model.costTracker.export_summary_dict()
    return rows

# ========
# Defines run type group batch function for this experiment module.
# ========
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

    updated = flow.analyst_agent.detect_pair_conflicts(artifact)
    if not isinstance(updated, dict):
        raise TypeError(
            "flow.analyst_agent.detect_pair_conflicts 必須回傳 dict，"
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
            final_label = str(dec.get("final_label") or "").strip() or "-"
            result = str(dec.get("result") or "").strip() or "-"
            reason = str(dec.get("reason") or "").strip()
            print(
                f"    - {cid}: {final_label} ({result})"
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
        new_id = f"REQ-{len(requirements_artifact['URL']) + len(remapped_requirements) + 1}"
        req_id_map[old_id] = new_id
        item = dict(req)
        item["id"] = new_id
        remapped_requirements.append(item)
    exported_requirements = requirements_payload({"URL": remapped_requirements})
    requirements_artifact["URL"].extend(exported_requirements.get("URL", []) or [])

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

# ========
# Defines run conflict function for this experiment module.
# ========
def run_conflict(
    flow: Flow,
    model_name: str,
    count: int = 0,
    *,
    data_path: Optional[Path] = None,
    scenario: Optional[str] = None,
    scenarios: Optional[List[str]] = None,
    run_id: Optional[str] = None,
    model_prefix: str = "",
):
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
    results_by_idx: Dict[int, Tuple[Any, Dict[str, Any]]] = {}
    grouped: Dict[str, list[tuple[int, dict]]] = {}
    for i, row in enumerate(data):
        g = str(row.get("types") or "Unknown")
        grouped.setdefault(g, []).append((i, row))

    meetings_by_type: Dict[str, Any] = {}
    conflict_artifact: Dict[str, Any] = {"pairs": []}
    requirements_artifact: Dict[str, Any] = {"URL": []}
    conflict_artifact.setdefault("pairs", [])
    requirements_artifact.setdefault("URL", [])
    task_cost_rows: List[Dict[str, Any]] = []

    for g, items in grouped.items():
        print(
            f"========== 類型：{g}（{len(items)} 筆）==========",
            flush=True,
        )
        cost_before = current_cost_snapshot(flow)
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
            cost_after = current_cost_snapshot(flow)
            agent_costs = {
                name: cost_summary_diff(cost_before.get(name, {}), summary)
                for name, summary in cost_after.items()
            }
            task_cost_rows.append(
                {
                    "task_name": str(g),
                    "totals": cost_totals(agent_costs),
                }
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
            raise

    missing_pred_rows = []
    y_pred = []
    for i in range(total):
        packed = results_by_idx.get(i)
        pred = packed[0] if packed else None
        if pred not in {"Conflict", "Neutral"}:
            row = data[i] if 0 <= i < len(data) else {}
            missing_pred_rows.append(
                {
                    "row": i + 1,
                    "type": str(row.get("types") or "Unknown"),
                    "error": str(
                        ((results_by_idx.get(i) or (None, {}))[1] or {})
                    )[:300],
                }
            )
            continue
        y_pred.append(pred)
    if missing_pred_rows:
        preview = ", ".join(
            f"第 {row['row']} 筆({row['type']})"
            for row in missing_pred_rows[:10]
        )
        raise RuntimeError(
            f"RQ2 有 {len(missing_pred_rows)} 筆缺少有效 pred；"
            f"通常是前面某個 type 整批失敗造成。前幾筆：{preview}"
        )
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

    # ========
    # Defines m function for this experiment module.
    # ========
    def m(v: Any) -> float:
        try:
            return float(v or 0.0)
        except (TypeError, ValueError):
            return 0.0

    cost_payload = build_plant_cost_payload(flow, task_cost_rows)
    paths = write_rq2_outputs(
        prefix=OUTPUT_PREFIX,
        results_dir=RESULTS_DIR,
        result=result,
        record=record_by_type,
        cost=cost_payload,
        run_id=run_id,
        model_prefix=model_prefix,
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
    return {
        "result": result,
        "cost": cost_payload,
        "paths": paths,
    }

# ========
# Defines run experiments function for this experiment module.
# ========
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
    file_prefix = plant_model_file_prefix(rq2_config)

    run_scalar_metrics: List[Dict[str, float]] = []
    run_costs_usd: List[float] = []
    run_input_tokens: List[int] = []
    run_output_tokens: List[int] = []
    run_total_tokens: List[int] = []
    run_total_runtime_s: List[float] = []
    run_costs_by_type: List[Dict[str, Dict[str, Any]]] = []

    for run_idx in range(runs):
        run_id = str(
            next_result_index(OUTPUT_PREFIX, RESULTS_DIR, model_prefix=file_prefix)
        )
        print(f"\n=== Run {run_idx + 1}/{runs}（run_id={run_id}）===")
        flow = build_flow(config=deepcopy(rq2_config))
        model_name = getattr(flow.agent_models.get("analyst"), "model_name", "unknown")
        run_output = run_conflict(
            flow,
            model_name,
            count=count,
            data_path=data_path,
            scenario=scenario,
            scenarios=scenarios,
            run_id=run_id,
            model_prefix=file_prefix,
        )
        result = run_output.get("result", {}) if isinstance(run_output, dict) else {}
        cost_payload = run_output.get("cost", {}) if isinstance(run_output, dict) else {}
        run_scalar_metrics.append(scalar_metrics_for_summary(result))
        run_costs_by_type.append(
            {
                str(row.get("task_name") or "Unknown"): row.get("totals", {})
                for row in (cost_payload.get("tasks", []) if isinstance(cost_payload, dict) else [])
                if isinstance(row, dict)
            }
        )
        run_costs_usd.append(
            float(cost_payload.get("totals", {}).get("estimated_cost(USD)", 0.0) or 0.0)
        )
        run_input_tokens.append(
            int(cost_payload.get("totals", {}).get("input_tokens", 0) or 0)
        )
        run_output_tokens.append(
            int(cost_payload.get("totals", {}).get("output_tokens", 0) or 0)
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
        run_input_tokens=run_input_tokens,
        run_output_tokens=run_output_tokens,
        run_total_tokens=run_total_tokens,
        run_total_runtime_s=run_total_runtime_s,
        run_costs_by_type=run_costs_by_type,
        model_prefix=file_prefix,
    )
