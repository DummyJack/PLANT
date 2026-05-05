import csv
import json
import os
import re
from pathlib import Path
from statistics import mean
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
from flow.setup import Flow
from utils import json_dump_no_scientific

RQ2_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = RQ2_DIR
RESULTS_DIR = RQ2_DIR / "results"

def record_pair_id_from_internal(pair_id: Any) -> str:
    """Convert internal PAIR-000 ids to record-facing PAIR-1 ids."""
    text = str(pair_id or "").strip()
    m = re.fullmatch(r"PAIR-(\d+)", text)
    if not m:
        return text
    return f"PAIR-{int(m.group(1)) + 1}"

def print_multi_run_summary(
    *,
    runs: int,
    run_scalar_metrics: List[Dict[str, float]],
    run_costs_usd: List[float],
    run_total_tokens: List[int],
    run_total_runtime_s: List[float],
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

    print("\n多次執行結果統計（平均值 ± 標準差）：")
    summary_metrics: Dict[str, Any] = {}
    for key in ordered_keys:
        vals = [float(row[key]) for row in run_scalar_metrics if key in row]
        if not vals:
            continue
        mu = mean(vals)
        sd = float(np.std(vals))
        summary_metrics[key] = {
            "mean": mu,
            "std": sd,
            "per_round_values": vals,
        }
        print(f"  {key}：{mu:.4f} ± {sd:.4f}")

    summary_payload: Dict[str, Any] = {"runs": runs}
    if summary_metrics:
        summary_payload["metrics"] = summary_metrics
    if run_costs_usd:
        cost_mu = float(np.mean(run_costs_usd))
        cost_sd = float(np.std(run_costs_usd))
        token_mu = float(np.mean(run_total_tokens))
        token_sd = float(np.std(run_total_tokens))
        rt_mu = float(np.mean(run_total_runtime_s))
        rt_sd = float(np.std(run_total_runtime_s))
        print(f"  平均 token：{token_mu:.1f} ± {token_sd:.1f}")
        print(f"  平均成本(USD)：{cost_mu:.8f} ± {cost_sd:.8f}")
        print(f"  平均執行時間(s)：{rt_mu:.3f} ± {rt_sd:.3f}")
        summary_payload["cost"] = {
            "average_token": {
                "mean": token_mu,
                "std": token_sd,
                "per_round_values": [int(x) for x in run_total_tokens],
            },
            "average_cost(USD)": {
                "mean": cost_mu,
                "std": cost_sd,
                "per_round_values": [float(x) for x in run_costs_usd],
            },
            "average_run_time(s)": {
                "mean": rt_mu,
                "std": rt_sd,
                "per_round_values": [float(x) for x in run_total_runtime_s],
            },
        }
    else:
        print("  平均成本(USD)：N/A")

    summary_path = RESULTS_DIR / "summary_Plant.json"
    with summary_path.open("w", encoding="utf-8") as f:
        json_dump_no_scientific(summary_payload, f, indent=2, ensure_ascii=False)
    print(f"統計已儲存至：{summary_path}")

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

def sync_config_language(artifact: Dict[str, Any]) -> None:
    """依輸入內容同步輸出語系，供各 agent prompt 使用。"""
    req_texts = [
        str(r.get("text") or "").strip()
        for r in (artifact.get("requirements") or [])
        if isinstance(r, dict)
    ]
    text_for_detect = " ".join(
        [str(artifact.get("rough_idea") or "").strip(), *req_texts]
    ).strip()
    lang = "en" if is_likely_english(text_for_detect) else "zh-Hant"
    os.environ["PLANT_OUTPUT_LANGUAGE"] = lang
    meta = artifact.get("meta")
    if not isinstance(meta, dict):
        meta = {}
        artifact["meta"] = meta
    meta["output_language"] = lang

def build_type_stakeholders(type_name: str, max_stakeholders: int) -> List[Dict[str, Any]]:
    """為 RQ2 benchmark 產生固定來源角色，不經過 user agent。"""
    cap = max(1, min(5, int(max_stakeholders or 5)))
    tn = str(type_name or "").strip() or "Generic System"
    base = [
        f"{tn} benchmark source",
        f"{tn} requirement A source",
        f"{tn} requirement B source",
        f"{tn} review context",
        f"{tn} dataset context",
    ]
    return [{"name": name, "text": []} for name in base[:cap]]

def build_type_rough_idea(type_name: str) -> str:
    """依 type 產生情境化 rough_idea。"""
    tn = str(type_name or "").strip() or "Generic System"
    return f"我要做一個 {tn}，請以此情境進行需求衝突辨識。"

def default_csv_path() -> Path:
    p = DATA_DIR / "cn_100.csv"
    if p.exists():
        return p
    fb = DATA_DIR / "cn_pairs.csv"
    return fb if fb.exists() else p

def load_rq2_dataset(path: Path) -> Tuple[List[Dict[str, Any]], str]:
    """載入實驗列資料。支援 CSV，或 JSON 陣列（打包多筆於單一檔）。

    每筆須含：Text1, Text2, Class；可選 types（與 CSV 相同）。"""
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
        with open(path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                rows.append(row)
        return rows, path.name
    raise ValueError(f"不支援的副檔名：{suffix}（請使用 .csv 或 .json）")

def extract_pair_preds_with_missing(
    artifact: Dict[str, Any], n_pairs: int
) -> Tuple[List[str], List[int]]:
    """依 pair_index（或 PAIR-xxx id）取得每對最終標籤，並回報未覆蓋 pair。"""
    by_k: Dict[int, str] = {}
    for c in artifact.get("conflicts", []) or []:
        if not isinstance(c, dict):
            continue
        pi = c.get("pair_index")
        if pi is None:
            cid = str(c.get("id") or "")
            if cid.startswith("PAIR-"):
                suf = cid.split("-", 1)[-1].strip()
                try:
                    pi = int(suf)
                except ValueError:
                    continue
        try:
            ik = int(pi)
        except (TypeError, ValueError):
            continue
        if ik < 0 or ik >= n_pairs:
            continue
        lb = (c.get("label") or "").strip()
        if lb in ("Conflict", "Neutral"):
            by_k[ik] = lb
    preds = [by_k.get(k, "Neutral") for k in range(n_pairs)]
    missing = [k for k in range(n_pairs) if k not in by_k]
    return preds, missing

def pair_index_from_id(pair_id: Any) -> Optional[int]:
    text = str(pair_id or "").strip()
    if not text:
        return None
    if text.startswith("PAIR-"):
        text = text.split("-", 1)[-1].strip()
    try:
        return int(text)
    except (TypeError, ValueError):
        return None

def incorrect_label_for(true_label: Any) -> str:
    label = str(true_label or "").strip()
    if label == "Conflict":
        return "Neutral"
    if label == "Neutral":
        return "Conflict"
    return "Neutral"

def extract_pair_review_preds_with_missing(
    artifact: Dict[str, Any],
    n_pairs: int,
) -> Tuple[List[str], List[int], Dict[int, Dict[str, Any]]]:
    """RQ2 label endpoint：優先讀主流程產生的 pair_reviews.final_label。"""
    by_k: Dict[int, str] = {}
    review_by_k: Dict[int, Dict[str, Any]] = {}
    for row in artifact.get("pair_reviews", []) or []:
        if not isinstance(row, dict):
            continue
        ik = pair_index_from_id(row.get("pair_id"))
        if ik is None or ik < 0 or ik >= n_pairs:
            continue
        label = str(row.get("final_label") or "").strip()
        if label not in {"Conflict", "Neutral"}:
            continue
        by_k[ik] = label
        review_by_k[ik] = row
    preds = [by_k.get(k, "Neutral") for k in range(n_pairs)]
    missing = [k for k in range(n_pairs) if k not in by_k]
    return preds, missing, review_by_k

def infer_single_pair_pred(artifact: Dict[str, Any]) -> Optional[str]:
    """從單 pair 的 conflict_detection 輸出推斷標籤。"""
    conflicts = artifact.get("conflicts") if isinstance(artifact.get("conflicts"), list) else []
    labels: List[str] = []
    for c in conflicts:
        if not isinstance(c, dict):
            continue
        lb = str(c.get("label") or "").strip()
        if lb in {"Conflict", "Neutral"}:
            labels.append(lb)
    if "Conflict" in labels:
        return "Conflict"
    if "Neutral" in labels:
        return "Neutral"
    if not labels:
        # 沒有任何輸出時保守視為 Neutral，但 caller 仍可標註 unresolved。
        return None
    return labels[0]

def supplement_missing_pair_predictions(
    flow: Flow,
    items: List[Tuple[int, Dict[str, Any]]],
    missing_pair_indices: List[int],
) -> Tuple[Dict[int, str], List[int]]:
    """對初判未覆蓋的 pair 逐對補判。"""
    supplemented: Dict[int, str] = {}
    unresolved: List[int] = []
    for k in missing_pair_indices:
        if k < 0 or k >= len(items):
            continue
        _, row = items[k]
        mini_artifact: Dict[str, Any] = {
            "requirements": [
                {"id": "A", "text": str(row.get("Text1") or "")},
                {"id": "B", "text": str(row.get("Text2") or "")},
            ],
            "conflicts": [],
            "meta": {"pairwise_only": False},
        }
        try:
            out = flow.analyst_agent.run_conflict_detection(mini_artifact)
            if not isinstance(out, dict):
                unresolved.append(k)
                continue
            lb = infer_single_pair_pred(out)
            if lb in {"Conflict", "Neutral"}:
                supplemented[k] = lb
            else:
                unresolved.append(k)
        except Exception:
            unresolved.append(k)
    return supplemented, unresolved

def inject_supplemented_conflicts(
    artifact: Dict[str, Any],
    *,
    pair_id_prefix: str,
    supplemented_labels: Dict[int, str],
) -> None:
    """把補判結果注入 artifact.conflicts，讓後續會前複核可見。"""
    if not supplemented_labels:
        return
    pool = artifact.get("conflicts")
    if not isinstance(pool, list):
        pool = []
        artifact["conflicts"] = pool

    existing_idx = set()
    for c in pool:
        if not isinstance(c, dict):
            continue
        try:
            pi = int(c.get("pair_index"))
            existing_idx.add(pi)
        except (TypeError, ValueError):
            continue

    for k, lb in supplemented_labels.items():
        if k in existing_idx:
            continue
        pool.append(
            {
                "id": f"PAIR-{k:03d}",
                "pair_index": int(k),
                "label": lb,
                "description": "補判：原始整批衝突辨識未覆蓋此 pair，改由單對補判。",
                "requirement_ids": [
                    f"{pair_id_prefix}-P{k}-a",
                    f"{pair_id_prefix}-P{k}-b",
                ],
                "supplemented": True,
                "supplement_reason": "missing_from_batch_conflict_detection",
            }
        )

def extract_pre_meeting_details(
    artifact: Dict[str, Any], *, round_num: int = 0
) -> Dict[str, Any]:
    """同一 type 整批只做一次會前複核：回傳可寫入 record 的會議資訊（不含 summary / raw_log_entry）。"""
    details: Dict[str, Any] = {
        "round": int(round_num),
        "changed_count": 0,
        "discussion_mode": "",
        "participants": [],
        "conversation": [],
        "decisions": [],
    }
    log = artifact.get("conflict_recheck_log")
    if not isinstance(log, list) or not log:
        return details
    entry = None
    for item in reversed(log):
        if not isinstance(item, dict):
            continue
        try:
            if int(item.get("round", -1)) == int(round_num):
                entry = item
                break
        except (TypeError, ValueError):
            continue
    if entry is None:
        entry = log[-1] if isinstance(log[-1], dict) else None
    if not isinstance(entry, dict):
        return details

    try:
        details["round"] = int(entry.get("round", round_num))
    except (TypeError, ValueError):
        details["round"] = int(round_num)
    tid = str(entry.get("topic_id") or "").strip()
    if tid:
        details["topic_id"] = tid
    details["changed_count"] = int(entry.get("changed_count", 0) or 0)
    details["discussion_mode"] = str(entry.get("discussion_mode") or "")
    details["participants"] = list(entry.get("participants") or [])
    conv = entry.get("conversation")
    if not isinstance(conv, list):
        conv = list(entry.get("dialogue") or [])
    normalized_conv: Dict[str, Any] = {}

    def normalize_conversation_statement(statement: str) -> Any:
        text = str(statement or "").strip()
        if not text:
            return ""
        try:
            parsed = json.loads(text)
        except Exception:
            return text
        if not isinstance(parsed, dict):
            return text
        pair_reviews = parsed.get("pair_reviews")
        if not isinstance(pair_reviews, list):
            return text
        return {
            "review_summary": str(
                parsed.get("review_summary") or parsed.get("overall_assessment") or ""
            ).strip(),
            "pair_reviews": [
                {
                    **row,
                    "id": record_pair_id_from_internal(row.get("id")),
                }
                if isinstance(row, dict)
                else row
                for row in pair_reviews
            ],
        }

    def add_conversation_statement(agent_name: str, statement: str) -> None:
        key = agent_name or "statement"
        normalized_statement = normalize_conversation_statement(statement)
        if key in normalized_conv and normalized_conv[key]:
            previous = normalized_conv[key]
            if isinstance(previous, str) and isinstance(normalized_statement, str):
                normalized_conv[key] = f"{previous}\n\n{normalized_statement}"
            else:
                existing = previous if isinstance(previous, list) else [previous]
                normalized_conv[key] = existing + [normalized_statement]
        else:
            normalized_conv[key] = normalized_statement

    for item in conv:
        if isinstance(item, str):
            s = item.strip()
            if s:
                agent_name = ""
                statement = s
                if ":" in s:
                    prefix, rest = s.split(":", 1)
                    if prefix.strip().lower() in {"analyst", "expert", "modeler", "user", "mediator"}:
                        agent_name = prefix.strip().lower()
                        statement = rest.strip()
                add_conversation_statement(agent_name, statement)
            continue
        if isinstance(item, dict):
            agent_name = str(item.get("agent") or "").strip()
            statement = str(item.get("statement") or item.get("content") or "").strip()
            if statement:
                add_conversation_statement(agent_name, statement)
    details["conversation"] = normalized_conv

    conflicts_by_id: Dict[str, Dict[str, Any]] = {}
    for c in artifact.get("conflicts", []) or []:
        if not isinstance(c, dict):
            continue
        cid = str(c.get("id") or "").strip()
        if cid:
            conflicts_by_id[cid] = c

    decision_rows: List[Dict[str, Any]] = []
    decisions = entry.get("decisions")
    if isinstance(decisions, list) and decisions:
        for d in decisions:
            if not isinstance(d, dict):
                continue
            cid = str(d.get("id") or "").strip()
            nl = str(d.get("new_label") or "").strip()
            rs = str(d.get("reason") or "").strip()
            cf = conflicts_by_id.get(cid, {})
            pm = (
                cf.get("pre_meeting_review")
                if isinstance(cf.get("pre_meeting_review"), dict)
                else {}
            )
            decision_rows.append(
                {
                    "id": cid,
                    "new_label": nl,
                    "reason": rs,
                    "from_label": str(pm.get("from_label") or ""),
                    "to_label": str(pm.get("to_label") or nl),
                    "result": str(pm.get("result") or ""),
                    "requirement_ids": list(cf.get("requirement_ids") or []),
                    "pair_index": cf.get("pair_index"),
                    "description": str(cf.get("description") or ""),
                }
            )
    details["decisions"] = decision_rows
    pair_reviews = entry.get("pair_reviews")
    details["pair_reviews"] = pair_reviews if isinstance(pair_reviews, list) else []
    return details

def build_pair_changed_flags(
    artifact: Dict[str, Any], n_pairs: int, preds: List[str]
) -> List[bool]:
    """每對：會前再審查是否改判（仍用 from/to label 比對，但不輸出這兩個欄位）。"""
    flags: List[bool] = [False] * n_pairs
    by_k: Dict[int, bool] = {}

    for c in artifact.get("conflicts", []) or []:
        if not isinstance(c, dict):
            continue
        pi = c.get("pair_index")
        if pi is None:
            cid = str(c.get("id") or "")
            if cid.startswith("PAIR-"):
                suf = cid.split("-", 1)[-1].strip()
                try:
                    pi = int(suf)
                except ValueError:
                    continue
        try:
            ik = int(pi)
        except (TypeError, ValueError):
            continue
        if ik < 0 or ik >= n_pairs:
            continue

        final_label = str(c.get("label") or "").strip()
        if final_label not in {"Conflict", "Neutral"}:
            final_label = preds[ik] if ik < len(preds) else "Neutral"

        pm = c.get("pre_meeting_review") if isinstance(c.get("pre_meeting_review"), dict) else {}
        from_label = str(pm.get("from_label") or final_label).strip() or final_label
        to_label = str(pm.get("to_label") or final_label).strip() or final_label
        changed = bool(pm.get("result") == "modify" or from_label != to_label)

        by_k[ik] = changed

    for k in range(n_pairs):
        flags[k] = bool(by_k.get(k, False))
    return flags
