# Provides RQ2 Plant experiment records helpers.
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from metric import Metric
from utils import json_dump_no_scientific

# ========
# Defines record pair id from index function for this experiment module.
# ========
def record_pair_id_from_index(index: int) -> str:
    return f"PAIR-{int(index) + 1}"

# ========
# Defines normalize pair details function for this experiment module.
# ========
def normalize_pair_details(details: Any) -> Dict[str, Any]:
    if not isinstance(details, dict):
        details = {}

    cleaned: Dict[str, Any] = {}
    source = dict(details)
    source.pop("pair_id", None)
    source.pop("topic_id", None)
    source.pop("requirement_ids", None)

    source.pop("reason", None)

    source.pop("round", None)
    if "from_label" in source and "initial_label" not in source:
        source["initial_label"] = source.pop("from_label")
    else:
        source.pop("from_label", None)
    source.pop("to_label", None)

    # ========
    # Defines cleaned review rows function for this experiment module.
    # ========
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
            review_rows.append(item)
        return review_rows

    for key, value in source.items():
        if key == "details" and isinstance(value, dict):
            grouped_reviews: Dict[str, List[Any]] = {}
            for round_key, rows in value.items():
                cleaned_rows = cleaned_review_rows(rows)
                if cleaned_rows:
                    grouped_reviews[str(round_key)] = cleaned_rows
            cleaned["details"] = grouped_reviews
        else:
            cleaned[key] = value

    return cleaned

# ========
# Defines next result index function for this experiment module.
# ========
def next_result_index(prefix: str, results_dir: Path) -> int:
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

# ========
# Defines build rq2 record by type function for this experiment module.
# ========
def build_rq2_record_by_type(
    grouped: Dict[str, List[Tuple[int, Dict[str, Any]]]],
    meetings_by_type: Dict[str, Any],
    results_by_idx: Dict[int, Tuple[Any, Dict[str, Any]]],
) -> Dict[str, List[Dict[str, Any]]]:
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
            review_details = details.get("details")
            if not isinstance(review_details, dict):
                review_details = {}
            final_label = str(details.get("final_label") or "").strip()
            if final_label not in {"Conflict", "Neutral"}:
                raise RuntimeError(f"RQ2 record 缺少 final_label: {base['id']}")
            initial_label = str(details.get("initial_label") or "").strip()
            if initial_label not in {"Conflict", "Neutral"}:
                raise RuntimeError(f"RQ2 record 缺少 initial_label: {base['id']}")
            description = str(details.get("description") or "").strip()
            if not description:
                raise RuntimeError(f"RQ2 record 缺少 description: {base['id']}")
            if not review_details:
                raise RuntimeError(f"RQ2 record 缺少 details: {base['id']}")
            base["pred"] = final_label
            conflict_meeting = {
                "status": str(details.get("status") or "").strip(),
                "initial_label": initial_label,
                "final_label": final_label,
                "description": description_by_pair_index.get(local_pair_index, "") or description,
                "details": review_details,
            }
            base["conflict_meeting"] = [conflict_meeting]
            pairs_out.append(base)
        out[str(g)] = pairs_out
    return out

# ========
# Defines build rq2 result payload function for this experiment module.
# ========
def build_rq2_result_payload(
    *,
    model_name: str,
    y_true: List[str],
    y_pred: List[str],
    grouped: Dict[str, List[Tuple[int, Dict[str, Any]]]],
    selected_types: Optional[List[str]] = None,
) -> Dict[str, Any]:
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

    result = {
        "model": str(model_name),
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
    normalized_selected = [
        str(item).strip()
        for item in (selected_types or [])
        if str(item or "").strip()
    ]
    if normalized_selected:
        result["selected_types"] = normalized_selected
    return result

# ========
# Defines write rq2 outputs function for this experiment module.
# ========
def write_rq2_outputs(
    *,
    prefix: str,
    results_dir: Path,
    result: Dict[str, Any],
    record: Dict[str, Any],
    cost: Dict[str, Any],
) -> Dict[str, Path]:
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

# ========
# Defines scalar metrics for summary function for this experiment module.
# ========
def scalar_metrics_for_summary(result: Dict[str, Any]) -> Dict[str, float]:
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
    metrics_by_type = (
        result.get("metrics_by_type")
        if isinstance(result.get("metrics_by_type"), dict)
        else {}
    )
    for scenario, scenario_metrics in metrics_by_type.items():
        if not isinstance(scenario_metrics, dict):
            continue
        prefix = f"by_type.{scenario}"
        overall_by_type = scenario_metrics.get("overall")
        if isinstance(overall_by_type, dict):
            for k, v in overall_by_type.items():
                if isinstance(v, (int, float)):
                    out[f"{prefix}.overall_{k}"] = float(v)
        conflict_by_type = scenario_metrics.get("conflict")
        if isinstance(conflict_by_type, dict):
            for k, v in conflict_by_type.items():
                if isinstance(v, (int, float)):
                    out[f"{prefix}.conflict_{k}"] = float(v)
    return out
