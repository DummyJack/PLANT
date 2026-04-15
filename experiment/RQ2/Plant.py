# Plant 衝突辨識實驗結果（使用 Flow 與 RQ2 config）

import csv
import json
import os
import sys
import tempfile
import traceback
import re
from copy import deepcopy
from pathlib import Path
from statistics import mean
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

RQ2_DIR = Path(__file__).resolve().parent
EXP_DIR = RQ2_DIR.parent
BASE_DIR = EXP_DIR.parent
sys.path.insert(0, str(RQ2_DIR))
sys.path.insert(0, str(BASE_DIR))

from dotenv import load_dotenv
from flow import Flow
from metric import Metric
from utils import json_dump_no_scientific, model_has_token_pricing

DATA_DIR = RQ2_DIR
RESULTS_DIR = RQ2_DIR / "results"
CONFIG_PATH = RQ2_DIR / "config_RQ2.json"
PROMPT_FOR_RUNS = True

load_dotenv(BASE_DIR / ".env")


class ExperimentLogger:
    """實驗用無輸出 logger（不寫 log 檔）。"""

    def info(self, *args, **kwargs):
        pass

    def warning(self, *args, **kwargs):
        pass

    def error(self, *args, **kwargs):
        pass


class ExperimentStore:
    """實驗用無 I/O store（不產生 project id 與 artifacts）。"""

    def __init__(self) -> None:
        self.project_id = "rq2_experiment"
        # AgendaRunner 會讀取 output_dir；不指向 repo 根目錄，避免誤讀既有 design_rationale.md
        self.output_dir = Path(tempfile.gettempdir()) / "plant_rq2_experiment_store"
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.project_dir = self.output_dir

    def save_artifact(self, data: Dict[str, Any]):
        pass

    def save_json(self, data: Dict[str, Any], filepath: str, indent: int = 2):
        pass

    def save_markdown(self, content: str, filename: str):
        pass

    def save_plantuml_files(self, model_data: Dict[str, Any]):
        pass

    def save_draft(self, content: str, version: int):
        pass

    def get_draft_version(self) -> int:
        return -1

    def load_draft(self, version: int):
        return None


def _assert_agent_models_have_token_pricing(config: Dict[str, Any]) -> None:
    for agent, info in (config.get("agent_models") or {}).items():
        if agent == "default" or not isinstance(info, dict):
            continue
        mn = info.get("model")
        if not mn:
            continue
        if not model_has_token_pricing(str(mn)):
            print(
                f"警告：沒有找到 token 的定價：agent_models.{agent} 模型「{mn}」。"
                "請在專案 utils.py 的 CostTracker.DEFAULT_PRICING_PER_1M_TOKENS 補上該模型，"
                "或改用已定價的模型名稱。"
            )
            sys.exit(1)


def load_rq2_config() -> Dict[str, Any]:
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    if not isinstance(cfg, dict):
        raise ValueError("config_RQ2.json 內容必須是 JSON 物件")
    return cfg


def build_flow(config: Optional[Dict[str, Any]] = None) -> Flow:
    if config is None:
        config = load_rq2_config()
    check_provider_model_mismatch(config)
    _assert_agent_models_have_token_pricing(config)
    return Flow(config=config, store=ExperimentStore(), logger=ExperimentLogger())


def check_provider_model_mismatch(config: Dict[str, Any]) -> None:
    """檢查 provider/model 是否明顯不匹配；任一不匹配即拋 ValueError 中止。"""

    def _looks_openai(model: str) -> bool:
        m = (model or "").lower()
        return m.startswith("gpt-") or m.startswith("o")

    def _looks_gemini(model: str) -> bool:
        return (model or "").lower().startswith("gemini")

    mismatches: list[str] = []
    model_cfg = (config.get("agent_models") or {})
    for agent, info in model_cfg.items():
        if not isinstance(info, dict):
            continue
        provider = (info.get("provider") or "").lower()
        model = info.get("model") or ""
        if not provider or not model:
            continue
        bad = (
            (provider == "openai" and _looks_gemini(model))
            or (provider == "gemini" and _looks_openai(model))
        )
        if bad:
            mismatches.append(
                f"agent_models.{agent}: provider={provider!r}, model={model!r}"
            )

    if not mismatches:
        return
    detail = "\n".join(f"  - {line}" for line in mismatches)
    msg = f"provider/model 明顯不匹配（請修正 config 的 agent_models）：\n{detail}"
    raise ValueError(msg)


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


def build_type_stakeholders(flow: Flow, type_name: str, max_stakeholders: int) -> List[Dict[str, Any]]:
    """由 user agent 依 type 情境自行提出 stakeholder 名稱。"""
    cap = max(1, min(5, int(max_stakeholders or 5)))
    rough_idea = build_type_rough_idea(type_name)
    proposed = flow.user_agent.propose_stakeholders(rough_idea)
    stakeholders: List[Dict[str, Any]] = []
    for item in proposed or []:
        if isinstance(item, dict):
            name = str(item.get("name") or "").strip()
        else:
            name = str(item).strip()
        if name and name not in {s.get("name", "") for s in stakeholders}:
            stakeholders.append({"name": name, "text": []})
        if len(stakeholders) >= cap:
            break
    if not stakeholders:
        raise RuntimeError(f"RQ2 user agent 未能為 type={type_name} 產生 stakeholder")
    return stakeholders[:cap]


def build_type_rough_idea(type_name: str) -> str:
    """依 type 產生情境化 rough_idea。"""
    tn = str(type_name or "").strip() or "Generic System"
    return f"我要做一個 {tn}，請以此情境進行需求衝突辨識。"


def build_plant_cost_payload(flow: Flow) -> Dict[str, Any]:
    """彙總 Flow 內各 LLM 的 CostTracker（與 flow.finalize 的 cost_summary 結構相近）。"""
    cost_by_agent: Dict[str, Any] = {}
    for agent_name, m in flow.agent_models.items():
        if not hasattr(m, "costTracker"):
            continue
        summary = m.costTracker.export_summary_dict()
        # 僅保留本次實驗中實際有 LLM token 使用的 agent。
        if int(summary.get("total_tokens", 0) or 0) <= 0:
            continue
        cost_by_agent[agent_name] = summary
    if not cost_by_agent:
        return {
            "agents": {},
            "totals": {
                "input_tokens": 0,
                "output_tokens": 0,
                "total_tokens": 0,
                "run_time(s)": 0.0,
                "estimated_cost(USD)": 0.0,
            },
        }
    totals = {
        "input_tokens": sum(int(v.get("input_tokens", 0) or 0) for v in cost_by_agent.values()),
        "output_tokens": sum(int(v.get("output_tokens", 0) or 0) for v in cost_by_agent.values()),
        "total_tokens": sum(int(v.get("total_tokens", 0) or 0) for v in cost_by_agent.values()),
        "run_time(s)": round(
            sum(float(v.get("run_time(s)", 0.0) or 0.0) for v in cost_by_agent.values()),
            3,
        ),
        "estimated_cost(USD)": round(
            sum(float(v.get("estimated_cost(USD)", 0.0) or 0.0) for v in cost_by_agent.values()),
            8,
        ),
    }
    return {
        "agents": cost_by_agent,
        "totals": totals,
    }


def _default_csv_path() -> Path:
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


def _extract_pair_preds_with_missing(
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


def _infer_single_pair_pred(artifact: Dict[str, Any]) -> Optional[str]:
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


def _supplement_missing_pair_predictions(
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
            lb = _infer_single_pair_pred(out)
            if lb in {"Conflict", "Neutral"}:
                supplemented[k] = lb
            else:
                unresolved.append(k)
        except Exception:
            unresolved.append(k)
    return supplemented, unresolved


def _inject_supplemented_conflicts(
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


def _extract_pre_meeting_details(
    artifact: Dict[str, Any], *, round_num: int = 0
) -> Dict[str, Any]:
    """同一 type 整批只做一次會前複核：回傳可寫入 record 的會議資訊（不含 summary / raw_log_entry）。"""
    show_debug = bool((artifact.get("meta") or {}).get("rq2_debug", False))
    details: Dict[str, Any] = {
        "round": int(round_num),
        "changed_count": 0,
        "discussion_mode": "",
        "participants": [],
        "conversation": [],
        "decisions": [],
    }
    if show_debug:
        details["debug"] = {}
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
    if show_debug:
        details["debug"] = dict(entry.get("debug") or {}) if isinstance(entry.get("debug"), dict) else {}
    conv = entry.get("conversation")
    if not isinstance(conv, list):
        conv = list(entry.get("dialogue") or [])
    normalized_conv: List[str] = []
    for item in conv:
        if isinstance(item, str):
            s = item.strip()
            if s:
                normalized_conv.append(s)
            continue
        if isinstance(item, dict):
            agent_name = str(item.get("agent") or "").strip()
            statement = str(item.get("statement") or item.get("content") or "").strip()
            if agent_name and statement:
                normalized_conv.append(f"{agent_name}: {statement}")
            elif statement:
                normalized_conv.append(statement)
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
    return details


def _build_pair_changed_flags(
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


def _pair_batch_gap_status(
    k: int,
    *,
    missing_before: set[int],
    supplemented: set[int],
    unresolved: set[int],
) -> str:
    """初判漏檢／單對補判結果。"""
    if k in unresolved:
        return "unexpected_unresolved"
    if k in supplemented:
        return "recovered_by_single_pair_fallback"
    return "covered_by_batch_detection"


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
    stakeholders = build_type_stakeholders(flow, type_name, max_stakeholders)
    # 讓 user agent 在本 type 的整批流程中明確知道自己代表哪些人。
    flow.user_agent.stakeholders = stakeholders

    requirements: List[Dict[str, Any]] = []
    for k in range(n):
        _, row = items[k]
        sh_a = stakeholders[(2 * k) % len(stakeholders)]["name"]
        sh_b = stakeholders[(2 * k + 1) % len(stakeholders)]["name"]
        requirements.append(
            {
                "id": f"{pair_id_prefix}-P{k}-a",
                "text": str(row.get("Text1") or ""),
                "proposed_by": "user",
                "source_stakeholder": sh_a,
            }
        )
        requirements.append(
            {
                "id": f"{pair_id_prefix}-P{k}-b",
                "text": str(row.get("Text2") or ""),
                "proposed_by": "user",
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
            "requirements_proposed_by": "user_agent",
            "requirement_owner_type": type_name,
            "rq2_debug": bool(flow.config.get("rq2_debug", False)),
        },
    }
    sync_config_language(artifact)

    updated = flow.analyst_agent.run_conflict_detection(artifact)
    if not isinstance(updated, dict):
        raise TypeError(
            "flow.analyst_agent.run_conflict_detection 必須回傳 dict，"
            f"實得 {type(updated).__name__}"
        )
    analyst_preds, missing_before_supplement = _extract_pair_preds_with_missing(updated, n)
    supplemented_labels: Dict[int, str] = {}
    unresolved_missing: List[int] = []
    if missing_before_supplement:
        supplemented_labels, unresolved_missing = _supplement_missing_pair_predictions(
            flow, items, missing_before_supplement
        )
        for k, lb in supplemented_labels.items():
            if 0 <= k < n:
                analyst_preds[k] = lb
        _inject_supplemented_conflicts(
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
            unresolved_txt = ", ".join(str(i) for i in sorted(unresolved_missing))
            raise RuntimeError(
                "硬閘門：存在補判後仍 unresolved 的 pair，"
                f"type={type_name}, unresolved_pair_indices=[{unresolved_txt}]"
            )
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

    preds, _ = _extract_pair_preds_with_missing(updated, n)
    changed_flags = _build_pair_changed_flags(updated, n, preds)
    meeting_details = _extract_pre_meeting_details(updated, round_num=1)
    if missing_before_supplement:
        meeting_details["missing_before_supplement"] = list(missing_before_supplement)
        meeting_details["supplemented_pair_indices"] = sorted(supplemented_labels.keys())
        meeting_details["supplement_unresolved_pair_indices"] = sorted(unresolved_missing)
    meetings_by_type[type_name] = meeting_details
    missing_before_set = set(missing_before_supplement)
    supplemented_set = set(supplemented_labels.keys())
    unresolved_set = set(unresolved_missing)
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
                            "changed_after_review": changed_flags[k],
                            "true": row["Class"],
                            "pred": preds[k],
                            "batch_gap_status": _pair_batch_gap_status(
                                k,
                                missing_before=missing_before_set,
                                supplemented=supplemented_set,
                                unresolved=unresolved_set,
                            ),
                        }
                    ],
                },
            },
        )


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
        pairs_out: List[Dict[str, Any]] = []
        for row_index, row in items:
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
                    "changed_after_review": False,
                    "true": row.get("Class"),
                    "pred": None,
                    "batch_gap_status": "covered_by_batch_detection",
                }
            pairs_out.append(base)
        meeting = meetings_by_type.get(g)
        block: Dict[str, Any] = dict(meeting) if isinstance(meeting, dict) else {}
        block["pairs"] = pairs_out
        out.append({str(g): block})
    return out


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
      會議欄位為單次會前複核之扁平結構（``round`` / ``conversation`` / ``decisions`` 等）。
    """
    try:
        if data_path is not None:
            data, data_file_label = load_rq2_dataset(Path(data_path).resolve())
        else:
            p = _default_csv_path()
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
                                    "changed_after_review": False,
                                    "true": row["Class"],
                                    "pred": None,
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

    n_conflict = y_true.count("Conflict")
    n_neutral = y_true.count("Neutral")
    overall = Metric.macro(y_true, y_pred, labels=["Conflict", "Neutral"])["macro"]
    conflict_class = Metric.binary(y_true, y_pred, positive_label="Conflict")
    metrics = {"overall": overall, "conflict": conflict_class}

    by_type: Dict[str, Dict[str, Any]] = {}
    for g, items in grouped.items():
        idxs = [i for i, _ in items]
        yt = [y_true[i] for i in idxs]
        yp = [y_pred[i] for i in idxs]
        if not yt:
            continue
        n_conf = yt.count("Conflict")
        n_neu = yt.count("Neutral")
        m_overall = Metric.macro(yt, yp, labels=["Conflict", "Neutral"])["macro"]
        m_conflict = Metric.binary(yt, yp, positive_label="Conflict")
        by_type[g] = {
            "total": len(yt),
            "count": {"conflict": n_conf, "neutral": n_neu},
            "overall": m_overall,
            "conflict": m_conflict,
        }

    result = {
        "model": str(model_name),
        "data_file": data_file_label,
        "total": total,
        "count": {
            "conflict": n_conflict,
            "neutral": n_neutral,
        },
        "metrics": metrics,
        "metrics_by_type": by_type,
    }

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    run_idx = next_result_index("Plant", RESULTS_DIR)
    result_path = RESULTS_DIR / f"result_Plant_{run_idx}.json"
    record_path = RESULTS_DIR / f"record_Plant_{run_idx}.json"
    cost_path = RESULTS_DIR / f"cost_Plant_{run_idx}.json"
    def _m(v: Any) -> float:
        try:
            return float(v or 0.0)
        except (TypeError, ValueError):
            return 0.0

    with open(result_path, "w", encoding="utf-8") as f:
        json_dump_no_scientific(result, f, indent=2, ensure_ascii=False)
    with open(record_path, "w", encoding="utf-8") as f:
        json_dump_no_scientific(record_by_type, f, indent=2, ensure_ascii=False)
    cost_payload = build_plant_cost_payload(flow)
    with open(cost_path, "w", encoding="utf-8") as f:
        json_dump_no_scientific(cost_payload, f, indent=2, ensure_ascii=False)

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
    print(f"- result: {result_path}")
    print(f"- record: {record_path}")
    print(f"- cost:   {cost_path}")
    return {
        "result": result,
        "cost": cost_payload,
        "paths": {
            "result": result_path,
            "record": record_path,
            "cost": cost_path,
        },
    }


if __name__ == "__main__":
    # 用法：
    #   python Plant.py
    #   python Plant.py /path/to/batch.json
    #   python Plant.py /path/to/data.csv
    arg_path: Optional[Path] = None
    if len(sys.argv) >= 2:
        arg_path = Path(sys.argv[1]).expanduser()
        if not arg_path.is_absolute():
            arg_path = (Path.cwd() / arg_path).resolve()
    raw_count = input("請輸入要執行的任務數量（Enter: 全做）：").strip()
    if not raw_count:
        count = 0
    else:
        try:
            count = int(raw_count)
        except ValueError:
            print("錯誤：任務數量必須是整數")
            sys.exit(1)
        if count < 0:
            print("錯誤：任務數量不可為負數")
            sys.exit(1)

    try:
        rq2_config = load_rq2_config()
    except Exception as e:
        print(f"錯誤：無法讀取 config_RQ2.json：{e}")
        sys.exit(1)

    runs: int | None = None
    if PROMPT_FOR_RUNS:
        raw_runs = input("請輸入要重複執行幾次：").strip()
        if not raw_runs:
            print("錯誤：請輸入重複執行次數")
            sys.exit(1)
        try:
            runs = int(raw_runs)
        except ValueError:
            print("錯誤：重複執行次數必須是整數")
            sys.exit(1)
    if runs is None:
        runs = 1
    runs = int(runs)
    if runs <= 0:
        print("錯誤：runs（重複執行次數）必須為正整數")
        sys.exit(1)

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    run_scalar_metrics: List[Dict[str, float]] = []
    run_costs_usd: List[float] = []
    run_total_tokens: List[int] = []
    run_total_runtime_s: List[float] = []

    for run_idx in range(runs):
        print(f"\n=== Run {run_idx + 1}/{runs} ===")
        flow = build_flow(config=deepcopy(rq2_config))
        model_name = getattr(flow.agent_models.get("analyst"), "model_name", "unknown")
        run_output = run_conflict(flow, model_name, count=count, data_path=arg_path)
        result = run_output.get("result", {}) if isinstance(run_output, dict) else {}
        cost_payload = run_output.get("cost", {}) if isinstance(run_output, dict) else {}
        run_scalar_metrics.append(scalar_metrics_for_summary(result))
        run_costs_usd.append(float(cost_payload.get("totals", {}).get("estimated_cost(USD)", 0.0) or 0.0))
        run_total_tokens.append(int(cost_payload.get("totals", {}).get("total_tokens", 0) or 0))
        run_total_runtime_s.append(float(cost_payload.get("totals", {}).get("run_time(s)", 0.0) or 0.0))

    if runs > 1:
        all_keys: set[str] = set()
        for m in run_scalar_metrics:
            all_keys.update(m.keys())
        preferred_order = [
            "overall_precision",
            "overall_recall",
            "overall_f1",
            "conflict_precision",
            "conflict_recall",
            "conflict_f1",
        ]
        ordered_keys = [k for k in preferred_order if k in all_keys]
        ordered_keys.extend(sorted(k for k in all_keys if k not in set(ordered_keys)))
        print("\n跨多次執行統計（平均值 ± 標準差）：")
        summary_metrics: Dict[str, Any] = {}
        for key in ordered_keys:
            vals = [float(m[key]) for m in run_scalar_metrics if key in m]
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
        print(f"跨 run 統計已儲存至：{summary_path}")
