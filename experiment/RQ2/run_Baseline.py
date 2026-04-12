# 基準方法衝突辨識實驗（含 BaselineModel：OpenAI 或 Google Gemini）

from __future__ import annotations

import csv
import os
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from dotenv import load_dotenv
from openai import OpenAI

# ---------------------------------------------------------------------------
# 路徑與環境（須先於 utils / metric 匯入）
# ---------------------------------------------------------------------------
RQ2_DIR = Path(__file__).resolve().parent
BASE_DIR = RQ2_DIR.parent.parent
sys.path.insert(0, str(BASE_DIR))
load_dotenv(dotenv_path=BASE_DIR / ".env")

from metric import Metric
from utils import CostTracker, json_dump_no_scientific

# ---------------------------------------------------------------------------
# 實驗常數
# ---------------------------------------------------------------------------
CN_PAIRS_CSV = "cn_100.csv"  # 基準資料集（與 dataset/extract_RQ2.py 產出對齊）
RESULTS_DIR = RQ2_DIR / "results"
MAX_WORKERS = 10
BASELINE_PROVIDER = "openai"
BASELINE_MODEL = "gpt-4.1"
BASELINE_TEMPERATURE = 0.0

COST_ACTION_DETECT = "baseline.detect_conflict"
DEFAULT_OPENAI_MODEL = "gpt-4.1"
DEFAULT_GEMINI_MODEL = "gemini-3-flash-preview"

def _conflict_prompt(text1: str, text2: str) -> str:
    return (
        f"需求 A: {text1}\n\n需求 B: {text2}\n\n"
        "判斷以上需求 A 和 B 是否有衝突，有衝突輸出 Conflict，沒有則輸出 Neutral，不用再額外生成任何內容。"
    )


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


# ---------------------------------------------------------------------------
# BaselineModel
# ---------------------------------------------------------------------------
class BaselineModel:
    """單一 LLM 端點，對兩句需求做 Conflict / Neutral 二元判斷。"""

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
            self.model_name = model_name or DEFAULT_OPENAI_MODEL
            api_key = os.getenv("OPENAI_API_KEY")
            if not api_key:
                print("錯誤：未找到 OPENAI_API_KEY 環境變數")
                sys.exit(1)
            self.client: OpenAI | None = OpenAI(api_key=api_key)
            self._genai_client = None
            self._genai_types = None
            self._gemini_lock = None
        elif p == "gemini":
            self.model_name = model_name or DEFAULT_GEMINI_MODEL
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
            self._genai_client = genai.Client(api_key=api_key)
            self._genai_types = genai_types
            self.client = None
            self._gemini_lock = threading.Lock()
        else:
            print(f"錯誤：不支援的 provider: {provider}（請用 openai 或 gemini）")
            sys.exit(1)

        self.cost_tracker = CostTracker(model_name=self.model_name)

    def detect_conflict(self, text1: str, text2: str) -> str:
        user_prompt = _conflict_prompt(text1, text2)

        if self.provider == "openai":
            return self._detect_openai(user_prompt)
        return self._detect_gemini(user_prompt)

    def _detect_openai(self, user_prompt: str) -> str:
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
                metadata={"action": COST_ACTION_DETECT},
                run_time_s=run_s,
            )
        if resp is None or not getattr(resp, "choices", None):
            return "Neutral"
        return (resp.choices[0].message.content or "").strip()

    def _detect_gemini(self, user_prompt: str) -> str:
        assert self._genai_client is not None and self._genai_types is not None
        assert self._gemini_lock is not None

        cfg = self._genai_types.GenerateContentConfig(temperature=self.temperature)
        self.cost_tracker.start()
        response = None
        try:
            with self._gemini_lock:
                response = self._genai_client.models.generate_content(
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
                metadata={"action": COST_ACTION_DETECT},
                run_time_s=run_s,
            )

        raw = gemini_response_text(response).strip()
        if not raw:
            raise ValueError("Gemini 無回應內容（可能被安全過濾或無候選）")
        return raw


# ---------------------------------------------------------------------------
# 成本彙總與輸出
# ---------------------------------------------------------------------------
def build_baseline_cost_payload(model: BaselineModel) -> dict:
    agent = model.cost_tracker.export_summary_dict()
    return {
        "method": "Baseline",
        "agents": {"baseline": agent},
        "totals": {
            "input_tokens": agent["input_tokens"],
            "output_tokens": agent["output_tokens"],
            "total_tokens": agent["total_tokens"],
            "run_time(s)": agent["run_time(s)"],
            "estimated_cost(USD)": agent["estimated_cost(USD)"],
        },
    }


def _load_cn_pairs(csv_path: Path, limit: int) -> list[dict]:
    with csv_path.open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    if limit > 0:
        return rows[:limit]
    return rows


def _predict_row(model: BaselineModel, idx: int, row: dict) -> tuple[int, Optional[str], dict]:
    text1, text2 = row["Text1"], row["Text2"]
    pred = model.detect_conflict(text1, text2)
    rec = {"text1": text1, "text2": text2, "true": row["Class"], "pred": pred}
    return idx, pred, rec


def _failed_record(data: list[dict], idx: int) -> tuple[None, dict]:
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


def run_conflict(model: BaselineModel, count: int = 0) -> dict:
    csv_path = RQ2_DIR / CN_PAIRS_CSV
    data = _load_cn_pairs(csv_path, count)
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
            executor.submit(_predict_row, model, i, row): i
            for i, row in enumerate(data)
        }
        for future in as_completed(future_to_idx):
            idx = future_to_idx[future]
            try:
                i, pred, rec = future.result()
                results_by_idx[i] = (pred, rec)
            except Exception:
                results_by_idx[idx] = _failed_record(data, idx)
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
    minor_ratio = min(n_conflict, n_neutral) / total if total else 0.0
    mode = "macro"
    print(f"  整體計算方式: {mode} (少數類佔比 {minor_ratio:.1%})")
    overall = Metric.macro(y_true, y_pred, labels=["Conflict", "Neutral"])["macro"]

    conflict_metrics = Metric.precision_recall_f1(y_true, y_pred, label="Conflict")
    metrics = {"mode": mode, "overall": overall, "conflict": conflict_metrics}

    result = {
        "task": "conflict_detection",
        "model": f"{getattr(model, 'provider', 'openai')}_{model.model_name}",
        "total": total,
        "count": {
            "conflict": n_conflict,
            "neutral": n_neutral,
            "minority_ratio": round(min(n_conflict, n_neutral) / total, 4) if total else 0.0,
        },
        "metrics": metrics,
    }

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%H%M%S")
    paths = {
        "result": RESULTS_DIR / f"result_Baseline_{ts}.json",
        "record": RESULTS_DIR / f"record_Baseline_{ts}.json",
        "cost": RESULTS_DIR / f"cost_Baseline_{ts}.json",
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
    model = BaselineModel(
        provider=BASELINE_PROVIDER,
        model_name=BASELINE_MODEL,
        temperature=float(BASELINE_TEMPERATURE),
    )
    print(f"Baseline provider={model.provider} model={model.model_name}")

    raw_count = input("實驗幾筆資料 (Enter:全做): ").strip()
    count = int(raw_count) if raw_count else 0
    run_conflict(model, count=count)
