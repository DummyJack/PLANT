import csv
import os
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
import re
from pathlib import Path
from statistics import mean
from typing import Any, Optional

from utils.clean import apply_entrypoint_bootstrap

apply_entrypoint_bootstrap()

# 路徑與環境（須先於 metric / utils 匯入）
RQ2_DIR = Path(__file__).resolve().parent
BASE_DIR = RQ2_DIR.parent.parent

import numpy as np
from dotenv import load_dotenv
from openai import OpenAI

from metric import Metric
from utils import CostTracker, json_dump_no_scientific, model_has_token_pricing

load_dotenv(dotenv_path=BASE_DIR / ".env")
CN_PAIRS_CSV = "cn_pairs.csv"
RESULTS_DIR = RQ2_DIR / "results"
RESULTS_FILE_PREFIX = "Baseline"

# 實驗常數
BASELINE_PROVIDER = "openai"
BASELINE_MODEL = "gpt-4.1"
BASELINE_TEMPERATURE = 0.0
PROMPT_FOR_RUNS = True
MAX_WORKERS = 5

# 取得下一個輸出編號（同 prefix 下取現有最大值 +1）。
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

# 建立衝突判斷的提示詞。
def conflict_prompt(text1: str, text2: str, req_type: Optional[str] = None) -> str:
    type_line = f"情境: {req_type}\n\n" if req_type else ""
    return (
        f"{type_line}需求 A: {text1}\n\n需求 B: {text2}\n\n"
        "根據情境，判斷需求 A 和 B 是否有衝突，有衝突輸出 Conflict，沒有則輸出 Neutral，不用再額外生成任何內容。"
    )


# 從 Gemini 回傳物件萃取文字內容。
def gemini_response_text(response: Any) -> str:
    try:
        t = getattr(response, "text", None)
        if t:
            return t
    except Exception:
        pass
    if getattr(response, "candidates", None):
        parts: list[str] = []
        for c in response.candidates:
            for p in getattr(c.content, "parts", []) or []:
                if getattr(p, "text", None):
                    parts.append(p.text)
        return "".join(parts)
    return ""


# 單一 LLM 端點，對兩句需求做 Conflict / Neutral 二元判斷。
class BaselineModel:

    def __init__(
        self,
        provider: str = "openai",
        model_name: Optional[str] = None,
        temperature: float = 0.0,
    ) -> None:
        p = (provider or "openai").lower()
        self.provider = p
        self.temperature = temperature

        if p == "openai":
            self.model_name = model_name or BASELINE_MODEL
            api_key = os.getenv("OPENAI_API_KEY")
            if not api_key:
                print("錯誤：未找到 OPENAI_API_KEY 環境變數")
                sys.exit(1)
            self.client: Optional[OpenAI] = OpenAI(api_key=api_key)
            self.genai_client = None
            self.genai_types = None
            self.gemini_lock = None
        elif p == "gemini":
            self.model_name = model_name or BASELINE_MODEL
            api_key = os.getenv("GEMINI_API_KEY")
            if not api_key:
                print("錯誤：未找到 GEMINI_API_KEY 環境變數")
                sys.exit(1)
            try:
                from google import genai
                from google.genai import types as genai_types
            except ImportError as e:
                print("錯誤：使用 Gemini 請先安裝 google-genai")
                raise SystemExit(1) from e
            self.genai_client = genai.Client(api_key=api_key)
            self.genai_types = genai_types
            self.client = None
            self.gemini_lock = threading.Lock()
        else:
            print(f"錯誤：不支援的 provider: {provider}（請用 openai 或 gemini）")
            sys.exit(1)

        self.cost_tracker = CostTracker(model_name=self.model_name)
        if not model_has_token_pricing(self.model_name):
            print(
                f"警告：沒有找到 token 的定價：模型「{self.model_name}」。"
                "請在專案 utils/cost.py 的 CostTracker.DEFAULT_PRICING_PER_1M_TOKENS 補上該模型，"
                "或改用已定價的模型名稱。"
            )
            sys.exit(1)

    def detect_conflict(
        self, text1: str, text2: str, req_type: Optional[str] = None
    ) -> str:
        # 對外入口：依 provider 分派到對應推論實作。
        user_prompt = conflict_prompt(text1, text2, req_type=req_type)

        if self.provider == "openai":
            return self.detect_openai(user_prompt)
        return self.detect_gemini(user_prompt)

    # 使用 OpenAI Chat Completions 做衝突判斷，並累加成本。
    def detect_openai(self, user_prompt: str) -> str:
        assert self.client is not None
        self.cost_tracker.start()
        resp = None
        try:
            resp = self.client.chat.completions.create(
                model=self.model_name,
                messages=[{"role": "user", "content": user_prompt}],
                temperature=self.temperature,
            )
        finally:
            run_s = self.cost_tracker.end_segment()

        usage = getattr(resp, "usage", None) if resp is not None else None
        if usage:
            self.cost_tracker.addUsage(
                {
                    "prompt_tokens": getattr(usage, "prompt_tokens", 0) or 0,
                    "completion_tokens": getattr(usage, "completion_tokens", 0) or 0,
                    "total_tokens": getattr(usage, "total_tokens", 0) or 0,
                },
                run_time_s=run_s,
            )
        if resp is None or not getattr(resp, "choices", None):
            return "Neutral"
        return (resp.choices[0].message.content or "").strip()

    # 使用 Gemini 生成內容 API 做衝突判斷，並累加成本。
    def detect_gemini(self, user_prompt: str) -> str:
        assert self.genai_client is not None and self.genai_types is not None
        assert self.gemini_lock is not None

        cfg = self.genai_types.GenerateContentConfig(temperature=self.temperature)
        self.cost_tracker.start()
        response = None
        try:
            with self.gemini_lock:
                response = self.genai_client.models.generate_content(
                    model=self.model_name,
                    contents=user_prompt,
                    config=cfg,
                )
        finally:
            run_s = self.cost_tracker.end_segment()

        um = getattr(response, "usage_metadata", None) if response is not None else None
        if um:
            prompt = getattr(um, "prompt_token_count", 0) or 0
            cand = getattr(um, "candidates_token_count", 0) or 0
            total = getattr(um, "total_token_count", None)
            if total is None:
                total = prompt + cand
            self.cost_tracker.addUsage(
                {
                    "prompt_tokens": prompt,
                    "completion_tokens": cand,
                    "total_tokens": int(total),
                },
                run_time_s=run_s,
            )

        raw = gemini_response_text(response).strip()
        if not raw:
            raise ValueError("Gemini 無回應內容（可能被安全過濾或無候選）")
        return raw


# 成本相關
def build_baseline_cost_payload(model: BaselineModel) -> dict:
    # 產生單層成本摘要，對齊 RQ1 Baseline cost 結構。
    return dict(model.cost_tracker.export_summary_dict())


# 載入資料集；可依 types 過濾，limit > 0 時只取前 N 筆。
def load_cn_pairs(
    csv_path: Path,
    limit: int,
    *,
    scenarios: Optional[list[str]] = None,
) -> list[dict]:
    with csv_path.open(encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    selected = [str(s).strip() for s in (scenarios or []) if str(s).strip()]
    if selected:
        selected_set = set(selected)
        rows = [
            row for row in rows
            if (str(row.get("types") or "Unknown").strip() or "Unknown") in selected_set
        ]
    if limit > 0:
        return rows[:limit]
    return rows


def choose_scenarios(csv_path: Path) -> Optional[list[str]]:
    try:
        rows = load_cn_pairs(csv_path, 0)
    except OSError as e:
        print(f"錯誤：無法載入資料檔以列出情境：{e}")
        sys.exit(1)

    scenario_counts: dict[str, int] = {}
    for row in rows:
        scenario = str(row.get("types") or "Unknown").strip() or "Unknown"
        scenario_counts[scenario] = scenario_counts.get(scenario, 0) + 1

    if not scenario_counts:
        print("錯誤：資料集中沒有可執行的情境")
        sys.exit(1)

    scenarios = list(scenario_counts.keys())
    print("可選情境：")
    for idx, scenario in enumerate(scenarios, 1):
        print(f"  {idx}. {scenario}（{scenario_counts[scenario]} 筆）")

    raw_scenario = input("請選擇要執行的情境（Enter: 全部，可輸入 1,3,5）：").strip()
    if not raw_scenario:
        return None
    tokens = [token.strip() for token in raw_scenario.split(",") if token.strip()]
    if not tokens or any(not token.isdigit() for token in tokens):
        print("錯誤：請輸入情境編號；多個情境請使用 1,3,5 格式")
        sys.exit(1)
    selected: list[str] = []
    seen: set[int] = set()
    for token in tokens:
        selected_idx = int(token)
        if selected_idx < 1 or selected_idx > len(scenarios):
            print("錯誤：情境編號超出範圍")
            sys.exit(1)
        if selected_idx in seen:
            continue
        seen.add(selected_idx)
        selected.append(scenarios[selected_idx - 1])
    return selected


# 單筆資料推論，回傳索引、預測與紀錄。
def predict_row(model: BaselineModel, idx: int, row: dict) -> tuple[int, Optional[str], dict]:
    text1, text2 = row["Text1"], row["Text2"]
    req_type = (row.get("types") or "").strip()
    pred = model.detect_conflict(text1, text2, req_type=req_type)
    rec = {
        "type": req_type,
        "text1": text1,
        "text2": text2,
        "true": row["Class"],
        "pred": pred,
    }
    return idx, pred, rec


# 建立單筆失敗時的保底紀錄。
def failed_record(data: list[dict], idx: int) -> tuple[None, dict]:
    row = data[idx]
    return (
        None,
        {
            "text1": row["Text1"],
            "text2": row["Text2"],
            "true": row["Class"],
            "pred": None,
        },
    )


# 從單次 result 抽出可跨 run 做 mean/std 的數值指標。
def scalar_metrics_for_summary(result: dict) -> dict[str, float]:
    out: dict[str, float] = {}
    metrics = result.get("metrics") if isinstance(result.get("metrics"), dict) else {}
    overall = metrics.get("overall") if isinstance(metrics.get("overall"), dict) else {}
    for k, v in overall.items():
        if isinstance(v, (int, float)):
            out[f"overall_{k}"] = float(v)
        elif isinstance(v, dict):
            prefix = str(k)
            for sk, sv in v.items():
                if isinstance(sv, (int, float)):
                    out[f"{prefix}_{sk}"] = float(sv)
    conflict = metrics.get("conflict")
    if isinstance(conflict, dict):
        for k, v in conflict.items():
            if isinstance(v, (int, float)):
                out[f"conflict_{k}"] = float(v)
    return out


def run_conflict(
    model: BaselineModel,
    count: int = 0,
    *,
    paths: dict[str, Path],
    scenarios: Optional[list[str]] = None,
) -> dict:
    # 執行一次完整衝突辨識並輸出 result/record/cost。
    csv_path = RQ2_DIR / CN_PAIRS_CSV
    data = load_cn_pairs(csv_path, count, scenarios=scenarios)
    total = len(data)
    if total == 0:
        print(f"錯誤：沒有資料可跑（檢查 {CN_PAIRS_CSV} 或 count）")
        sys.exit(1)

    y_true = [row["Class"] for row in data]
    results_by_idx: dict[int, tuple[Optional[str], dict]] = {}
    max_workers = min(MAX_WORKERS, total)

    done = 0
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_idx = {
            executor.submit(predict_row, model, i, row): i
            for i, row in enumerate(data)
        }
        for future in as_completed(future_to_idx):
            idx = future_to_idx[future]
            try:
                i, pred, rec = future.result()
                results_by_idx[i] = (pred, rec)
            except Exception:
                results_by_idx[idx] = failed_record(data, idx)
            done += 1
            print(f"\r  conflict: {done}/{total}", end="", flush=True)

    y_pred = [
        (results_by_idx[i][0] if results_by_idx[i][0] is not None else "Neutral")
        for i in range(total)
    ]
    records = [results_by_idx[i][1] for i in range(total)]
    print()

    n_conflict = y_true.count("Conflict")
    n_neutral = y_true.count("Neutral")
    overall = Metric.macro(y_true, y_pred, labels=["Conflict", "Neutral"])["macro"]
    conflict_metrics = Metric.binary(y_true, y_pred, positive_label="Conflict")
    metrics = {"overall": overall, "conflict": conflict_metrics}

    result = {
        "model": str(model.model_name),
        "total": total,
        "scenarios": scenarios or [],
        "count": {
            "conflict": n_conflict,
            "neutral": n_neutral,
        },
        "metrics": metrics,
    }

    with paths["result"].open("w", encoding="utf-8") as f:
        json_dump_no_scientific(result, f, indent=2, ensure_ascii=False)
    with paths["record"].open("w", encoding="utf-8") as f:
        json_dump_no_scientific(records, f, indent=2, ensure_ascii=False)
    with paths["cost"].open("w", encoding="utf-8") as f:
        json_dump_no_scientific(
            build_baseline_cost_payload(model), f, indent=2, ensure_ascii=False
        )
    for key in ("result", "record", "cost"):
        print(f"  已儲存: {paths[key]}")

    return result


if __name__ == "__main__":
    print(f"Baseline provider={BASELINE_PROVIDER} model={BASELINE_MODEL}")
    csv_path = RQ2_DIR / CN_PAIRS_CSV
    scenarios = choose_scenarios(csv_path)
    count = 0

    runs: Optional[int] = None
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
        print("錯誤：runs 必須為正整數")
        sys.exit(1)

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    run_scalar_metrics: list[dict[str, float]] = []
    run_costs_usd: list[float] = []
    run_total_tokens: list[int] = []
    run_total_runtime_s: list[float] = []

    for run_idx in range(runs):
        run_id = str(next_result_index(RESULTS_FILE_PREFIX, RESULTS_DIR))
        print(f"\n=== Run {run_idx + 1}/{runs}（run_id={run_id}）===")

        model = BaselineModel(
            provider=BASELINE_PROVIDER,
            model_name=BASELINE_MODEL,
            temperature=float(BASELINE_TEMPERATURE),
        )
        print(f"  provider={model.provider} model={model.model_name}")

        paths = {
            "result": RESULTS_DIR / f"result_{RESULTS_FILE_PREFIX}_{run_id}.json",
            "record": RESULTS_DIR / f"record_{RESULTS_FILE_PREFIX}_{run_id}.json",
            "cost": RESULTS_DIR / f"cost_{RESULTS_FILE_PREFIX}_{run_id}.json",
        }
        result = run_conflict(model, count=count, paths=paths, scenarios=scenarios)
        run_scalar_metrics.append(scalar_metrics_for_summary(result))
        cost_payload = build_baseline_cost_payload(model)
        run_costs_usd.append(float(cost_payload.get("estimated_cost(USD)", 0.0) or 0.0))
        run_total_tokens.append(int(cost_payload.get("total_tokens", 0) or 0))
        run_total_runtime_s.append(float(cost_payload.get("run_time(s)", 0.0) or 0.0))

    if runs > 1:
        all_keys: set[str] = set()
        for m in run_scalar_metrics:
            all_keys.update(m.keys())
        print("\n多次執行結果統計（平均值 ± 標準差）：")
        # JSON 與終端輸出順序：先 overall（precision→recall→f1），再 conflict（同序）；其餘鍵依字母接於後。
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
        summary_metrics: dict[str, Any] = {}
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

        summary_payload: dict[str, Any] = {"runs": runs}
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

        summary_path = RESULTS_DIR / f"summary_{RESULTS_FILE_PREFIX}.json"
        with summary_path.open("w", encoding="utf-8") as f:
            json_dump_no_scientific(summary_payload, f, indent=2, ensure_ascii=False)
        print(f"已儲存至：{summary_path}")
