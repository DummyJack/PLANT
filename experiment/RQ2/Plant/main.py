# Provides RQ2 Plant experiment main helpers.
import json
import traceback
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from dotenv import load_dotenv
from flow.setup import Flow
from storage.artifact import conflict_payload, requirements_payload
from utils import json_dump_no_scientific

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

# ========
# Defines load checkpoint file function for this experiment module.
# ========
def load_checkpoint_file(path: Path) -> Dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        with path.open("r", encoding="utf-8") as f:
            payload = json.load(f)
    except Exception as e:
        raise RuntimeError(f"checkpoint 檔案無法讀取，請修復或刪除後再續跑：{path}") from e
    if not isinstance(payload, dict):
        raise RuntimeError(f"checkpoint 檔案格式錯誤，最外層必須是 object：{path}")
    return payload

# ========
# Defines write json atomic function for this experiment module.
# ========
def write_json_atomic(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f".{path.name}.tmp")
    with tmp_path.open("w", encoding="utf-8") as f:
        json_dump_no_scientific(payload, f, indent=2, ensure_ascii=False)
    tmp_path.replace(path)

# ========
# Defines merge cost payloads function for this experiment module.
# ========
def merge_cost_payloads(previous: Dict[str, Any], current: Dict[str, Any]) -> Dict[str, Any]:
    if not previous:
        return current
    if not current:
        return previous
    merged_agents: Dict[str, Any] = {}
    previous_agents = previous.get("agents") or {}
    current_agents = current.get("agents") or {}
    for agent in sorted(set(previous_agents.keys()) | set(current_agents.keys())):
        prev = previous_agents.get(agent) or {}
        cur = current_agents.get(agent) or {}
        merged_agents[agent] = {
            "model": cur.get("model") or prev.get("model") or "",
            "input_tokens": int(prev.get("input_tokens", 0) or 0) + int(cur.get("input_tokens", 0) or 0),
            "output_tokens": int(prev.get("output_tokens", 0) or 0) + int(cur.get("output_tokens", 0) or 0),
            "total_tokens": int(prev.get("total_tokens", 0) or 0) + int(cur.get("total_tokens", 0) or 0),
            "run_time(s)": round(float(prev.get("run_time(s)", 0.0) or 0.0) + float(cur.get("run_time(s)", 0.0) or 0.0), 3),
            "estimated_cost(USD)": round(float(prev.get("estimated_cost(USD)", 0.0) or 0.0) + float(cur.get("estimated_cost(USD)", 0.0) or 0.0), 8),
        }
    totals = {
        "input_tokens": sum(int(v.get("input_tokens", 0) or 0) for v in merged_agents.values()),
        "output_tokens": sum(int(v.get("output_tokens", 0) or 0) for v in merged_agents.values()),
        "total_tokens": sum(int(v.get("total_tokens", 0) or 0) for v in merged_agents.values()),
        "run_time(s)": round(sum(float(v.get("run_time(s)", 0.0) or 0.0) for v in merged_agents.values()), 3),
        "estimated_cost(USD)": round(sum(float(v.get("estimated_cost(USD)", 0.0) or 0.0) for v in merged_agents.values()), 8),
    }
    return {"agents": merged_agents, "totals": totals}

# ========
# Defines available rq2 checkpoints function for this experiment module.
# ========
def available_rq2_checkpoints(results_dir: Path) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for path in sorted(results_dir.glob(f"checkpoint_{OUTPUT_PREFIX}_*.json")):
        run_id = path.stem.replace(f"checkpoint_{OUTPUT_PREFIX}_", "", 1)
        invalid = False
        try:
            with path.open("r", encoding="utf-8") as f:
                payload = json.load(f)
        except Exception:
            invalid = True
            payload = {}
        if not isinstance(payload, dict):
            invalid = True
            payload = {}
        completed = 0
        try:
            completed = int(payload.get("completed_type_count", 0) or 0)
        except (TypeError, ValueError):
            invalid = True
        rows.append({"run_id": run_id, "path": path, "completed": completed, "invalid": invalid})
    return rows

# ========
# Defines choose resume run id function for this experiment module.
# ========
def choose_resume_run_id(results_dir: Path) -> str:
    checkpoints = available_rq2_checkpoints(results_dir)
    if not checkpoints:
        return ""
    print("\n偵測到 RQ2 Plant checkpoint：")
    for idx, row in enumerate(checkpoints, start=1):
        suffix = "，檔案可能損壞" if row.get("invalid") else ""
        print(f"  {idx}. run_id={row['run_id']}，已完成 {row['completed']} 個 type{suffix}")
    print("  0. 開始新的 run")
    raw = input("請選擇要續跑的 checkpoint（Enter/0: 新 run）：").strip()
    if not raw or raw == "0":
        return ""
    try:
        index = int(raw)
    except ValueError:
        return ""
    if 1 <= index <= len(checkpoints):
        return str(checkpoints[index - 1]["run_id"])
    return ""

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
    checkpoint_path: Optional[Path] = None,
    checkpoint_payload: Optional[Dict[str, Any]] = None,
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

    cp = checkpoint_payload if isinstance(checkpoint_payload, dict) else {}
    previous_cost_payload = cp.get("cost_payload", {}) if isinstance(cp, dict) else {}
    completed_types = {
        str(item).strip()
        for item in (cp.get("completed_types", []) if isinstance(cp, dict) else [])
        if str(item).strip()
    }
    if cp and completed_types and not previous_cost_payload:
        print(
            "警告：此 checkpoint 沒有 cost_payload，成本只能統計本次續跑新增部分。"
            "若需要完整成本，請使用新版 checkpoint 或重新跑該 run。",
            flush=True,
        )
    if cp:
        cp_total = int(cp.get("total", 0) or 0)
        cp_selected_types = [
            str(item).strip()
            for item in (cp.get("selected_types", []) or [])
            if str(item).strip()
        ]
        if cp_total and cp_total != total:
            raise RuntimeError(
                f"checkpoint 原本資料量為 {cp_total}，本次資料量為 {total}。續跑時請使用相同的 count 與 type 選擇。"
            )
        if cp_selected_types != selected_scenarios:
            raise RuntimeError(
                f"checkpoint 原本 type 選擇為 {cp_selected_types or '全部'}，"
                f"本次為 {selected_scenarios or '全部'}。續跑時請使用相同設定。"
            )
    for raw_idx, packed in (cp.get("results_by_idx", {}) if isinstance(cp, dict) else {}).items():
        try:
            idx = int(raw_idx)
        except (TypeError, ValueError):
            continue
        if isinstance(packed, dict):
            results_by_idx[idx] = (packed.get("pred"), packed.get("record", {}))

    meetings_by_type: Dict[str, Any] = (
        dict(cp.get("meetings_by_type", {}))
        if isinstance(cp.get("meetings_by_type"), dict)
        else {}
    )
    conflict_artifact: Dict[str, Any] = (
        dict(cp.get("conflict_artifact", {}))
        if isinstance(cp.get("conflict_artifact"), dict)
        else {"pairs": []}
    )
    requirements_artifact: Dict[str, Any] = (
        dict(cp.get("requirements_artifact", {}))
        if isinstance(cp.get("requirements_artifact"), dict)
        else {"URL": []}
    )
    conflict_artifact.setdefault("pairs", [])
    requirements_artifact.setdefault("URL", [])

    def persist_checkpoint() -> Dict[str, Any]:
        if checkpoint_path is None:
            return merge_cost_payloads(previous_cost_payload, build_plant_cost_payload(flow))
        cost_payload = merge_cost_payloads(previous_cost_payload, build_plant_cost_payload(flow))
        packed_results = {
            str(idx): {
                "pred": pred,
                "record": rec,
            }
            for idx, (pred, rec) in sorted(results_by_idx.items())
        }
        write_json_atomic(
            checkpoint_path,
            {
                "run_id": str(run_id or ""),
                "total": total,
                "selected_types": selected_scenarios,
                "completed_type_count": len(completed_types),
                "completed_types": sorted(completed_types),
                "results_by_idx": packed_results,
                "meetings_by_type": meetings_by_type,
                "conflict_artifact": conflict_artifact,
                "requirements_artifact": requirements_artifact,
                "cost_payload": cost_payload,
            },
        )
        return cost_payload

    for g, items in grouped.items():
        if str(g) in completed_types:
            print(
                f"========== 類型：{g}（{len(items)} 筆）已完成，略過 ==========",
                flush=True,
            )
            continue
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
            completed_types.add(str(g))
            persist_checkpoint()
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
        selected_types=selected_scenarios,
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

    cost_payload = merge_cost_payloads(previous_cost_payload, build_plant_cost_payload(flow))
    paths = write_rq2_outputs(
        prefix=OUTPUT_PREFIX,
        results_dir=RESULTS_DIR,
        result=result,
        record=record_by_type,
        cost=cost_payload,
        run_id=run_id,
    )
    persist_checkpoint()

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
    resume_run_id: Optional[str] = None,
) -> None:
    try:
        rq2_config = load_rq2_config()
    except Exception as e:
        print(f"錯誤：無法讀取 Plant/config.json：{e}")
        raise SystemExit(1) from e

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    if resume_run_id is None:
        resume_run_id = choose_resume_run_id(RESULTS_DIR)
    if resume_run_id:
        runs = 1

    run_scalar_metrics: List[Dict[str, float]] = []
    run_costs_usd: List[float] = []
    run_total_tokens: List[int] = []
    run_total_runtime_s: List[float] = []

    for run_idx in range(runs):
        run_id = resume_run_id if resume_run_id and run_idx == 0 else str(next_result_index(OUTPUT_PREFIX, RESULTS_DIR))
        checkpoint_path = RESULTS_DIR / f"checkpoint_{OUTPUT_PREFIX}_{run_id}.json"
        checkpoint_payload = (
            load_checkpoint_file(checkpoint_path)
            if resume_run_id and run_idx == 0
            else {}
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
            checkpoint_path=checkpoint_path,
            checkpoint_payload=checkpoint_payload,
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
