import math
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict, List, Sequence


def round_to_2(value: float) -> float:
    value = float(value or 0.0)
    if not math.isfinite(value):
        return 0.0
    return float(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def round_to_4(value: float) -> float:
    value = float(value or 0.0)
    if not math.isfinite(value):
        return 0.0
    return float(Decimal(str(value)).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP))


def round_float_tree_to_2(value: Any) -> Any:
    if isinstance(value, bool):
        return value
    if isinstance(value, float):
        return round_to_2(value)
    if isinstance(value, list):
        return [round_float_tree_to_2(item) for item in value]
    if isinstance(value, dict):
        return {key: round_float_tree_to_2(item) for key, item in value.items()}
    return value


def variance(values: Sequence[float], mean: float) -> float:
    if len(values) <= 1:
        return 0.0
    return sum((float(x) - mean) ** 2 for x in values) / len(values)


def std_from_variance(value: float) -> float:
    return max(float(value or 0.0), 0.0) ** 0.5


def compute_tkqr(hit_sequence: Sequence[int], total_requirements: int) -> float:
    import math

    n = len(hit_sequence)
    k = int(total_requirements or 0)
    if n == 0 or k == 0:
        return 0.0

    dcg = 0.0
    for i, h_i in enumerate(hit_sequence, start=1):
        if int(h_i) == 1:
            dcg += 1.0 / math.log2(i + 1)

    idcg = 0.0
    for i in range(1, min(n, k) + 1):
        idcg += 1.0 / math.log2(i + 1)

    if idcg == 0.0:
        return 0.0
    return dcg / idcg


def compute_ora(turns: int, total_requirements: int) -> float:
    import math

    n = int(turns or 0)
    k = int(total_requirements or 0) + 1
    if k <= 0:
        return 0.0

    sigma = 0.425 * k
    deviation_squared = (n - k) ** 2
    return math.exp(-deviation_squared / (2 * sigma ** 2))


def aggregate_action_type_effectiveness(task_results: List[Dict[str, Any]]) -> Dict[str, Any]:
    agg: Dict[str, Dict[str, int]] = {}
    for t in task_results:
        for action_type, stats in (t.get("action_type_effectiveness") or {}).items():
            if action_type not in agg:
                agg[action_type] = {"total": 0, "effective": 0}
            agg[action_type]["total"] += int(stats.get("total", 0) or 0)
            agg[action_type]["effective"] += int(stats.get("effective", 0) or 0)

    out: Dict[str, Any] = {}
    for action_type, stats in agg.items():
        total = int(stats["total"])
        effective = int(stats["effective"])
        out[action_type] = {
            "total": total,
            "effective": effective,
            "effectiveness_ratio": (effective / total) if total > 0 else 0.0,
        }
    return out


def aggregate_aspect_type_elicitation(task_results: List[Dict[str, Any]]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    aspects: List[str] = []
    for task in task_results:
        for aspect in (task.get("aspect_type_elicitation", {}) or {}).keys():
            if aspect not in aspects:
                aspects.append(aspect)

    for aspect in aspects:
        total = sum(
            int((t.get("aspect_type_elicitation", {}).get(aspect, {}) or {}).get("total", 0) or 0)
            for t in task_results
        )
        elicited = sum(
            int((t.get("aspect_type_elicitation", {}).get(aspect, {}) or {}).get("elicited", 0) or 0)
            for t in task_results
        )
        out[aspect] = {
            "total": total,
            "elicited": elicited,
            "elicitation_ratio": (elicited / total) if total > 0 else 0.0,
        }
    return out


def application_type_statistics(task_results: List[Dict[str, Any]]) -> Dict[str, Any]:
    groups: Dict[str, List[Dict[str, Any]]] = {}
    for t in task_results:
        app_type = str(t.get("application_type", "Unknown"))
        groups.setdefault(app_type, []).append(t)

    stats: Dict[str, Any] = {}
    for app_type, rows in groups.items():
        if not rows:
            continue
        ers = [float(x.get("elicitation_ratio", 0.0) or 0.0) for x in rows]
        tkqrs = [float(x.get("tkqr", 0.0) or 0.0) for x in rows]
        oras = [float(x.get("ora", 0.0) or 0.0) for x in rows]
        m_er = sum(ers) / len(rows)
        m_tk = sum(tkqrs) / len(rows)
        m_or = sum(oras) / len(rows)
        stats[app_type] = {
            "num_tasks": len(rows),
            "average_elicitation_ratio": m_er,
            "variance_elicitation_ratio": variance(ers, m_er),
            "average_tkqr": m_tk,
            "variance_tkqr": variance(tkqrs, m_tk),
            "average_ora": m_or,
            "variance_ora": variance(oras, m_or),
        }
    return stats


def compute_overall_metrics(task_results: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not task_results:

        return {
            "elicitation_ratio": 0.0,
            "tkqr": 0.0,
            "ora": 0.0,
            "variance_elicitation_ratio": 0.0,
            "variance_tkqr": 0.0,
            "variance_ora": 0.0,
            "std_elicitation_ratio": 0.0,
            "std_tkqr": 0.0,
            "std_ora": 0.0,
            "action_type_effectiveness": {},
            "aspect_type_elicitation": {},
            "total_tasks": 0,
            "task_results": [],
        }

    total_tasks = len(task_results)
    total_requirements = sum(int(t.get("total_requirements", 0) or 0) for t in task_results)
    total_elicited = sum(int(t.get("total_elicited", 0) or 0) for t in task_results)

    ers = [float(t.get("elicitation_ratio", 0.0) or 0.0) for t in task_results]
    tkqrs = [float(t.get("tkqr", 0.0) or 0.0) for t in task_results]
    oras = [float(t.get("ora", 0.0) or 0.0) for t in task_results]
    token_costs = [float(t.get("token_cost", 0.0) or 0.0) for t in task_results]

    avg_er = (sum(ers) / total_tasks) if total_tasks else 0.0
    avg_tkqr = (sum(tkqrs) / total_tasks) if total_tasks else 0.0
    avg_ora = (sum(oras) / total_tasks) if total_tasks else 0.0
    avg_token = (sum(token_costs) / total_tasks) if total_tasks else 0.0
    variance_er = variance(ers, avg_er)
    variance_tkqr = variance(tkqrs, avg_tkqr)
    variance_ora = variance(oras, avg_ora)

    return {
        "elicitation_ratio": avg_er,
        "tkqr": avg_tkqr,
        "ora": avg_ora,
        "variance_elicitation_ratio": variance_er,
        "variance_tkqr": variance_tkqr,
        "variance_ora": variance_ora,
        "std_elicitation_ratio": std_from_variance(variance_er),
        "std_tkqr": std_from_variance(variance_tkqr),
        "std_ora": std_from_variance(variance_ora),
        "average_token_cost": avg_token,
        "variance_token_cost": variance(token_costs, avg_token),
        "elicitation_ratio_from_totals": (
            (total_elicited / total_requirements) if total_requirements > 0 else 0.0
        ),
        "action_type_effectiveness": aggregate_action_type_effectiveness(task_results),
        "aspect_type_elicitation": aggregate_aspect_type_elicitation(task_results),
        "application_type_statistics": application_type_statistics(task_results),
        "total_tasks": total_tasks,
        "total_requirements_all_tasks": total_requirements,
        "total_elicited_all_tasks": total_elicited,
        "task_results": task_results,
    }
