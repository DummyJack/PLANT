import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from metric import Metric
from utils import json_dump_no_scientific

def record_pair_id_from_index(index: int) -> str:
    return f"PAIR-{int(index) + 1}"

def normalize_pair_details(details: Any) -> Dict[str, Any]:
    """移除主流程內部欄位與舊格式欄位，只保留 RQ2 record 要展示的 pair details。"""
    if not isinstance(details, dict):
        details = {}

    cleaned: Dict[str, Any] = {}
    source = dict(details)
    source.pop("pair_id", None)
    source.pop("topic_id", None)
    source.pop("req_a", None)
    source.pop("req_b", None)
    source.pop("requirement_ids", None)

    source.pop("reason", None)
    source.pop("rationale", None)

    source.pop("round", None)
    if "from_label" in source and "initial_label" not in source:
        source["initial_label"] = source.pop("from_label")
    else:
        source.pop("from_label", None)
    source.pop("to_label", None)

    def cleaned_review_rows(rows: Any) -> List[Any]:
        review_rows = []
        if not isinstance(rows, list):
            return review_rows
        for review in rows:
            if not isinstance(review, dict):
                review_rows.append(review)
                continue
            item = dict(review)
            item.pop("id", None)
            item.pop("independent_label", None)
            if "rationale" in item and "reason" not in item:
                item["reason"] = item.pop("rationale")
            else:
                item.pop("rationale", None)
            review_rows.append(item)
        return review_rows

    for key, value in source.items():
        if key == "meeting_conflict_review" and isinstance(value, dict):
            grouped_reviews: Dict[str, List[Any]] = {}
            for round_key, rows in value.items():
                cleaned_rows = cleaned_review_rows(rows)
                if cleaned_rows:
                    grouped_reviews[str(round_key)] = cleaned_rows
            cleaned["meeting_conflict_review"] = grouped_reviews
        elif key == "meeting_conflict_review" and isinstance(value, list):
            cleaned["meeting_conflict_review"] = cleaned_review_rows(value)
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
) -> Dict[str, List[Dict[str, Any]]]:
    """組裝寫入 record 的 type-indexed object。"""
    out: Dict[str, List[Dict[str, Any]]] = {}
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
            description_by_pair_index[pair_index] = str(decision.get("reason") or "").strip()
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
            description = description_by_pair_index.get(local_pair_index, "")
            details = normalize_pair_details(base.pop("details", {}))
            base.pop("id", None)
            base = {"id": record_pair_id_from_index(local_pair_index), **base}
            review_details = details.get("meeting_conflict_review")
            if not isinstance(review_details, dict):
                review_details = {}
            final_label = str(details.get("final_label") or base.get("pred") or "").strip()
            if final_label:
                base["pred"] = final_label
            conflict_meeting = {
                "description": description or str(details.get("description") or "").strip(),
                "status": str(details.get("status") or "").strip(),
                "initial_label": str(details.get("initial_label") or "").strip(),
                "final_label": final_label,
                "details": review_details,
            }
            base["conflict_meeting"] = [conflict_meeting]
            pairs_out.append(base)
        out[str(g)] = pairs_out
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
    reqt_pairs: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Path]:
    """寫入 RQ2 result / record / cost 與 reqt_pairs 輸出檔案。"""
    results_dir.mkdir(parents=True, exist_ok=True)
    run_idx = next_result_index(prefix, results_dir)
    result_path = results_dir / f"result_{prefix}_{run_idx}.json"
    record_path = results_dir / f"record_{prefix}_{run_idx}.json"
    cost_path = results_dir / f"cost_{prefix}_{run_idx}.json"
    plant_dir = results_dir / prefix
    plant_dir.mkdir(parents=True, exist_ok=True)
    reqt_pairs_path = plant_dir / f"reqt_pairs_{run_idx}.json"

    with result_path.open("w", encoding="utf-8") as f:
        json_dump_no_scientific(result, f, indent=2, ensure_ascii=False)
    with record_path.open("w", encoding="utf-8") as f:
        json_dump_no_scientific(record, f, indent=2, ensure_ascii=False)
    with cost_path.open("w", encoding="utf-8") as f:
        json_dump_no_scientific(cost, f, indent=2, ensure_ascii=False)
    with reqt_pairs_path.open("w", encoding="utf-8") as f:
        json_dump_no_scientific(reqt_pairs or [], f, indent=2, ensure_ascii=False)

    return {
        "result": result_path,
        "record": record_path,
        "cost": cost_path,
        "reqt_pairs": reqt_pairs_path,
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
