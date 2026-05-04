import re
from pathlib import Path
from typing import Any, Dict, List, Tuple

from metric import Metric
from utils import json_dump_no_scientific

def normalize_pair_details(details: Any) -> Dict[str, Any]:
    """整理 pair details 的輸出欄位與順序。"""
    if not isinstance(details, dict):
        details = {}

    cleaned: Dict[str, Any] = {}
    source = dict(details)
    source.pop("pair_id", None)
    source.pop("topic_id", None)
    source.pop("req_a", None)
    source.pop("req_b", None)
    source.pop("confidence", None)
    source.pop("requirement_ids", None)

    source.pop("reason", None)
    source.pop("rationale", None)

    round_value = source.pop("round", None)
    if round_value is not None:
        cleaned["round"] = round_value

    for key, value in source.items():
        if key == "agent_judgments" and isinstance(value, list):
            judgments = []
            for judgment in value:
                if not isinstance(judgment, dict):
                    judgments.append(judgment)
                    continue
                item = dict(judgment)
                item.pop("id", None)
                item.pop("confidence", None)
                item.pop("independent_label", None)
                if "rationale" in item and "reason" not in item:
                    item["reason"] = item.pop("rationale")
                else:
                    item.pop("rationale", None)
                judgments.append(item)
            cleaned[key] = judgments
        else:
            cleaned[key] = value

    return cleaned

def next_result_index(prefix: str, results_dir: Path) -> int:
    """取得下一個輸出編號（同 prefix 下取現有最大值 +1）。"""
    pat = re.compile(rf"^(?:result|record|cost)_{re.escape(prefix)}_(\d+)\.json$")
    max_idx = 0
    for p in results_dir.glob(f"*_{prefix}_*.json"):
        m = pat.match(p.name)
        if not m:
            continue
        try:
            max_idx = max(max_idx, int(m.group(1)))
        except ValueError:
            continue
    return max_idx + 1

def build_rq2_record_by_type(
    grouped: Dict[str, List[Tuple[int, Dict[str, Any]]]],
    meetings_by_type: Dict[str, Any],
    results_by_idx: Dict[int, Tuple[Any, Dict[str, Any]]],
) -> List[Dict[str, Any]]:
    """組裝寫入 record 的「每 type 一筆」列表（每筆為單一 type key 的物件）。

    每個 pair 保留實驗所需欄位，不輸出資料列索引。
    """
    out: List[Dict[str, Any]] = []
    for g, items in grouped.items():
        meeting = meetings_by_type.get(g)
        block: Dict[str, Any] = dict(meeting) if isinstance(meeting, dict) else {}
        description_by_pair_index: Dict[int, str] = {}
        for decision in block.get("decisions", []) or []:
            if not isinstance(decision, dict):
                continue
            try:
                pair_index = int(decision.get("pair_index"))
            except (TypeError, ValueError):
                continue
            description = str(decision.pop("description", "") or "").strip()
            if description:
                description_by_pair_index[pair_index] = description
        pairs_out: List[Dict[str, Any]] = []
        for local_pair_index, (row_index, row) in enumerate(items):
            packed = results_by_idx.get(row_index)
            if not packed:
                continue
            _, rec = packed
            if not isinstance(rec, dict):
                continue
            tkey = str(row.get("types") or g)
            inner = rec.get(tkey)
            if not isinstance(inner, dict):
                inner = next(iter(rec.values()), {})
            plist = inner.get("pairs") if isinstance(inner.get("pairs"), list) else []
            base: Dict[str, Any]
            if plist and isinstance(plist[0], dict):
                base = dict(plist[0])
            else:
                base = {
                    "text1": row.get("Text1"),
                    "text2": row.get("Text2"),
                    "is_changed": False,
                    "true": row.get("Class"),
                    "pred": None,
                    "details": {},
                }
            if "changed_after_review" in base and "is_changed" not in base:
                base["is_changed"] = base.pop("changed_after_review")
            else:
                base.pop("changed_after_review", None)
            base.pop("description", None)
            description = description_by_pair_index.get(local_pair_index, "")
            details = normalize_pair_details(base.pop("details", {}))
            base.pop("id", None)
            base = {"id": f"PAIR-{local_pair_index}", **base}
            if description:
                reordered: Dict[str, Any] = {}
                for key, value in base.items():
                    reordered[key] = value
                    if key == "pred":
                        reordered["description"] = description
                base = reordered
            base["details"] = details
            pairs_out.append(base)
        block.pop("pair_reviews", None)
        block.pop("topic_id", None)
        block.pop("decisions", None)
        block["pairs"] = pairs_out
        out.append({str(g): block})
    return out

def build_rq2_result_payload(
    *,
    model_name: str,
    data_file_label: str,
    y_true: List[str],
    y_pred: List[str],
    grouped: Dict[str, List[Tuple[int, Dict[str, Any]]]],
) -> Dict[str, Any]:
    """組裝 RQ2 result 輸出，包含整體 metrics 與各 type metrics。"""
    n_conflict = y_true.count("Conflict")
    n_neutral = y_true.count("Neutral")
    overall = Metric.macro(y_true, y_pred, labels=["Conflict", "Neutral"])["macro"]
    conflict_class = Metric.binary(y_true, y_pred, positive_label="Conflict")

    by_type: Dict[str, Dict[str, Any]] = {}
    for g, items in grouped.items():
        idxs = [i for i, _ in items]
        yt = [y_true[i] for i in idxs]
        yp = [y_pred[i] for i in idxs]
        if not yt:
            continue
        n_conf = yt.count("Conflict")
        n_neu = yt.count("Neutral")
        by_type[g] = {
            "total": len(yt),
            "count": {"conflict": n_conf, "neutral": n_neu},
            "overall": Metric.macro(yt, yp, labels=["Conflict", "Neutral"])["macro"],
            "conflict": Metric.binary(yt, yp, positive_label="Conflict"),
        }

    return {
        "model": str(model_name),
        "data_file": data_file_label,
        "total": len(y_true),
        "count": {
            "conflict": n_conflict,
            "neutral": n_neutral,
        },
        "metrics": {
            "overall": overall,
            "conflict": conflict_class,
        },
        "metrics_by_type": by_type,
    }

def write_rq2_outputs(
    *,
    prefix: str,
    results_dir: Path,
    result: Dict[str, Any],
    record: List[Dict[str, Any]],
    cost: Dict[str, Any],
) -> Dict[str, Path]:
    """寫入 RQ2 result / record / cost 三個輸出檔案。"""
    results_dir.mkdir(parents=True, exist_ok=True)
    run_idx = next_result_index(prefix, results_dir)
    result_path = results_dir / f"result_{prefix}_{run_idx}.json"
    record_path = results_dir / f"record_{prefix}_{run_idx}.json"
    cost_path = results_dir / f"cost_{prefix}_{run_idx}.json"

    with result_path.open("w", encoding="utf-8") as f:
        json_dump_no_scientific(result, f, indent=2, ensure_ascii=False)
    with record_path.open("w", encoding="utf-8") as f:
        json_dump_no_scientific(record, f, indent=2, ensure_ascii=False)
    with cost_path.open("w", encoding="utf-8") as f:
        json_dump_no_scientific(cost, f, indent=2, ensure_ascii=False)

    return {
        "result": result_path,
        "record": record_path,
        "cost": cost_path,
    }

def scalar_metrics_for_summary(result: Dict[str, Any]) -> Dict[str, float]:
    """抽出可跨多次執行計算 mean/std 的數值指標。"""
    out: Dict[str, float] = {}
    metrics = result.get("metrics") if isinstance(result.get("metrics"), dict) else {}
    overall = metrics.get("overall") if isinstance(metrics.get("overall"), dict) else {}
    for k, v in overall.items():
        if isinstance(v, (int, float)):
            out[f"overall_{k}"] = float(v)
    conflict = metrics.get("conflict")
    if isinstance(conflict, dict):
        for k, v in conflict.items():
            if isinstance(v, (int, float)):
                out[f"conflict_{k}"] = float(v)
    return out
