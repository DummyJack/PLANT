# Provides RQ2 Plant experiment utils helpers.
import csv
import json
import os
import re
from pathlib import Path
from statistics import mean
from typing import Any, Dict, List, Tuple

import numpy as np
from agents.profile.analyst.conflicts import all_conflict_rows
from metric import round_to_4
from utils import json_dump_no_scientific

RQ2_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = RQ2_DIR
RESULTS_DIR = RQ2_DIR / "results"

# ========
# Defines final pair label function for this experiment module.
# ========
def final_pair_label(row: Dict[str, Any]) -> str:
    return str(row.get("final_label") or "").strip()

# ========
# Defines print multi run summary function for this experiment module.
# ========
def print_multi_run_summary(
    *,
    runs: int,
    run_scalar_metrics: List[Dict[str, float]],
    run_costs_usd: List[float],
    run_total_tokens: List[int],
    run_total_runtime_s: List[float],
    model_prefix: str,
    method_prefix: str = "Plant",
) -> None:
    if runs <= 1:
        return

    all_keys: set[str] = set()
    for metric_row in run_scalar_metrics:
        all_keys.update(metric_row.keys())
    preferred_order = [
        "overall_precision",
        "overall_recall",
        "overall_f1",
        "conflict_precision",
        "conflict_recall",
        "conflict_f1",
    ]
    ordered_keys = [key for key in preferred_order if key in all_keys]
    ordered_keys.extend(sorted(key for key in all_keys if key not in set(ordered_keys)))

    print("\n多次執行結果統計（平均值）：")
    summary_metrics: Dict[str, Any] = {}
    summary_metrics_by_type: Dict[str, Dict[str, Any]] = {}
    for key in ordered_keys:
        vals = [float(row[key]) for row in run_scalar_metrics if key in row]
        if not vals:
            continue
        rounded_vals = [round_to_4(v) for v in vals]
        mu = round_to_4(mean(vals))
        sigma = round_to_4(float(np.std(vals)))
        summary_item = {
            "mean": mu,
            "std": sigma,
            "per_round_values": rounded_vals,
        }
        if key.startswith("by_type."):
            parts = key.split(".", 2)
            if len(parts) == 3:
                _, scenario, metric_key = parts
                summary_metrics_by_type.setdefault(scenario, {})[metric_key] = summary_item
            else:
                summary_metrics[key] = summary_item
        else:
            summary_metrics[key] = summary_item
        print(f"  {key}：{mu:.2f}")

    summary_payload: Dict[str, Any] = {"runs": runs}
    if summary_metrics:
        summary_payload["metrics"] = summary_metrics
    if summary_metrics_by_type:
        summary_payload["metrics_by_type"] = summary_metrics_by_type
    if run_costs_usd:
        cost_mu = float(np.mean(run_costs_usd))
        token_mu = float(np.mean(run_total_tokens))
        rt_mu = float(np.mean(run_total_runtime_s))
        print(f"  平均 token：{token_mu:.1f}")
        print(f"  平均成本(USD)：{cost_mu:.8f}")
        print(f"  平均執行時間(s)：{rt_mu:.3f}")
        summary_payload["cost"] = {
            "average_token": token_mu,
            "average_cost(USD)": cost_mu,
            "average_run_time(s)": rt_mu,
        }
    else:
        print("  平均成本(USD)：N/A")

    file_prefix = f"{str(model_prefix or '').strip()}_" if str(model_prefix or "").strip() else ""
    summary_path = RESULTS_DIR / f"{file_prefix}summary_{method_prefix}.json"
    with summary_path.open("w", encoding="utf-8") as f:
        json_dump_no_scientific(summary_payload, f, indent=2, ensure_ascii=False)
    print(f"統計已儲存至：{summary_path}")

# ========
# Defines is likely english function for this experiment module.
# ========
def is_likely_english(text: str) -> bool:
    s = str(text or "").strip()
    if not s:
        return False
    letters = re.findall(r"[A-Za-z]", s)
    cjk = re.findall(r"[\u4e00-\u9fff]", s)
    if not letters:
        return False
    if not cjk:
        return True
    return len(letters) >= (len(cjk) * 2)

# ========
# Defines sync config language function for this experiment module.
# ========
def sync_config_language(artifact: Dict[str, Any], *, write_artifact_meta: bool = True) -> None:
    req_texts = [
        str(r.get("text") or "").strip()
        for r in (artifact.get("URL") or [])
        if isinstance(r, dict)
    ]
    text_for_detect = " ".join(
        [str(artifact.get("rough_idea") or "").strip(), *req_texts]
    ).strip()
    lang = "en" if is_likely_english(text_for_detect) else "zh-Hant"
    os.environ["PLANT_OUTPUT_LANGUAGE"] = lang
    if not write_artifact_meta:
        return
    meta = artifact.get("meta")
    if not isinstance(meta, dict):
        meta = {}
        artifact["meta"] = meta
    meta["output_language"] = lang

# ========
# Defines build type rough idea function for this experiment module.
# ========
def build_type_rough_idea(type_name: str) -> str:
    tn = str(type_name or "").strip() or "Generic System"
    return f"我要做一個 {tn}"

# ========
# Defines default csv path function for this experiment module.
# ========
def default_csv_path() -> Path:
    return DATA_DIR / "cn_pairs.csv"

# ========
# Defines load rq2 dataset function for this experiment module.
# ========
def load_rq2_dataset(path: Path) -> Tuple[List[Dict[str, Any]], str]:
    if not path.exists():
        raise FileNotFoundError(str(path))
    suffix = path.suffix.lower()
    if suffix == ".json":
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
        if not isinstance(raw, list):
            raise ValueError("JSON 批次檔頂層必須為陣列 [...]")
        rows: List[Dict[str, Any]] = []
        for i, item in enumerate(raw):
            if not isinstance(item, dict):
                raise ValueError(f"JSON 第 {i} 筆必須為物件")
            for k in ("Text1", "Text2", "Class"):
                if k not in item or item[k] is None:
                    raise ValueError(f"JSON 第 {i} 筆缺少欄位 {k}")
            rows.append(dict(item))
        return rows, path.name
    if suffix == ".csv":
        rows = []
        with open(path, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                rows.append(row)
        return rows, path.name
    raise ValueError(f"不支援的副檔名：{suffix}（請使用 .csv 或 .json）")

# ========
# Defines extract pair preds with missing function for this experiment module.
# ========
def extract_pair_preds_with_missing(
    artifact: Dict[str, Any], n_pairs: int
) -> Tuple[List[str], List[int]]:
    by_k: Dict[int, str] = {}
    for c in all_conflict_rows(artifact):
        if not isinstance(c, dict):
            continue
        pi = c.get("pair_index")
        if pi is None:
            cid = str(c.get("id") or "")
            if cid.startswith("PAIR-"):
                suf = cid.split("-", 1)[-1].strip()
                try:
                    pi = int(suf) - 1
                except ValueError:
                    continue
        try:
            ik = int(pi)
        except (TypeError, ValueError):
            continue
        if ik < 0 or ik >= n_pairs:
            continue
        lb = final_pair_label(c)
        if lb in ("Conflict", "Neutral"):
            by_k[ik] = lb
    preds = [by_k.get(k, "") for k in range(n_pairs)]
    missing = [k for k in range(n_pairs) if k not in by_k]
    return preds, missing

# ========
# Defines extract conflict review details function for this experiment module.
# ========
def extract_conflict_review_details(
    artifact: Dict[str, Any], *, round_num: int = 0
) -> Dict[str, Any]:
    details: Dict[str, Any] = {
        "round": int(round_num),
        "changed_count": 0,
        "discussion_mode": "",
        "participants": [],
        "decisions": [],
    }
    decisions: List[Dict[str, Any]] = []
    participants: List[str] = []

    # ========
    # Defines add participant function for this experiment module.
    # ========
    def add_participant(name: Any) -> None:
        text = str(name or "").strip()
        if text and text not in participants:
            participants.append(text)

    for c in all_conflict_rows(artifact):
        if not isinstance(c, dict):
            continue
        cid = str(c.get("id") or "").strip()
        if not cid:
            continue
        meeting = c.get("meeting")
        if not isinstance(meeting, dict) or not meeting:
            continue
        for rows in meeting.values():
            if not isinstance(rows, list):
                continue
            for row in rows:
                if not isinstance(row, dict):
                    continue
                add_participant(row.get("agent"))

        initial_label = str(c.get("initial_label") or "").strip()
        final_label = str(c.get("final_label") or "").strip()
        if initial_label not in {"Conflict", "Neutral"}:
            raise RuntimeError(f"RQ2 conflict review initial_label 不合法: {cid}")
        if final_label not in {"Conflict", "Neutral"}:
            raise RuntimeError(f"RQ2 conflict review final_label 不合法: {cid}")
        description = str(c.get("description") or "").strip()
        decisions.append(
            {
                "id": cid,
                "reason": description,
                "initial_label": initial_label,
                "final_label": final_label,
                "result": (
                    "modify"
                    if initial_label and final_label and initial_label != final_label
                    else "keep"
                ),
                "status": str(c.get("status") or "").strip(),
                "requirement_ids": list(c.get("requirement_ids") or []),
                "pair_index": c.get("pair_index"),
                "description": description,
            }
        )

    details["changed_count"] = sum(
        1 for item in decisions if item.get("result") == "modify"
    )
    details["discussion_mode"] = "sequential" if decisions else ""
    details["participants"] = participants
    details["decisions"] = decisions
    return details

# ========
# Defines build pair changed flags function for this experiment module.
# ========
def build_pair_changed_flags(artifact: Dict[str, Any], n_pairs: int) -> List[bool]:
    flags: List[bool] = [False] * n_pairs
    by_k: Dict[int, bool] = {}

    for c in all_conflict_rows(artifact):
        if not isinstance(c, dict):
            continue
        pi = c.get("pair_index")
        if pi is None:
            cid = str(c.get("id") or "")
            if cid.startswith("PAIR-"):
                suf = cid.split("-", 1)[-1].strip()
                try:
                    pi = int(suf) - 1
                except ValueError:
                    continue
        try:
            ik = int(pi)
        except (TypeError, ValueError):
            continue
        if ik < 0 or ik >= n_pairs:
            continue

        current_label = final_pair_label(c)
        if current_label not in {"Conflict", "Neutral"}:
            raise RuntimeError(f"RQ2 pair 缺少最終標籤: PAIR-{ik + 1}")

        initial_label = str(c.get("initial_label") or "").strip()
        resolved_final_label = str(c.get("final_label") or "").strip()
        if initial_label not in {"Conflict", "Neutral"}:
            raise RuntimeError(f"RQ2 pair initial_label 不合法: PAIR-{ik + 1}")
        if resolved_final_label not in {"Conflict", "Neutral"}:
            raise RuntimeError(f"RQ2 pair final_label 不合法: PAIR-{ik + 1}")
        changed = bool(
            initial_label
            and resolved_final_label
            and initial_label != resolved_final_label
        )

        by_k[ik] = changed

    for k in range(n_pairs):
        flags[k] = bool(by_k.get(k, False))
    return flags

# ========
# Defines build pair review details function for this experiment module.
# ========
def build_pair_review_details(
    artifact: Dict[str, Any],
    n_pairs: int,
) -> Dict[int, Dict[str, Any]]:
    details_by_k: Dict[int, Dict[str, Any]] = {}

    for c in all_conflict_rows(artifact):
        if not isinstance(c, dict):
            continue
        pi = c.get("pair_index")
        if pi is None:
            cid = str(c.get("id") or "")
            if cid.startswith("PAIR-"):
                suf = cid.split("-", 1)[-1].strip()
                try:
                    pi = int(suf) - 1
                except ValueError:
                    continue
        try:
            ik = int(pi)
        except (TypeError, ValueError):
            continue
        if ik < 0 or ik >= n_pairs:
            continue

        final_label = final_pair_label(c)
        if final_label not in {"Conflict", "Neutral"}:
            raise RuntimeError(f"RQ2 pair 缺少最終標籤: PAIR-{ik + 1}")

        details = c.get("meeting")
        if not isinstance(details, dict):
            raise RuntimeError(f"RQ2 pair 缺少 conflict meeting: PAIR-{ik + 1}")
        initial_label = str(c.get("initial_label") or "").strip()
        review_final_label = str(c.get("final_label") or "").strip()
        description = str(c.get("description") or "").strip()
        if initial_label not in {"Conflict", "Neutral"}:
            raise RuntimeError(f"RQ2 pair initial_label 不合法: PAIR-{ik + 1}")
        if review_final_label not in {"Conflict", "Neutral"}:
            raise RuntimeError(f"RQ2 pair final_label 不合法: PAIR-{ik + 1}")
        if not description:
            raise RuntimeError(f"RQ2 pair 缺少 description: PAIR-{ik + 1}")
        if not isinstance(details, dict) or not details:
            raise RuntimeError(f"RQ2 pair 缺少 details: PAIR-{ik + 1}")
        details_by_k[ik] = {
            "status": str(c.get("status") or "").strip(),
            "initial_label": initial_label,
            "final_label": review_final_label,
            "reason": description,
            "description": description,
            "details": details,
        }
    return details_by_k
