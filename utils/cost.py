# Cost tracker: runtime, usage records, and estimated model costs.
import threading

from time import perf_counter
from typing import Any, Dict, List, Optional


class CostTracker:
    """LLM token、耗時與估算成本。"""

    # 單位：USD / 1M tokens
    DEFAULT_PRICING_PER_1M_TOKENS: Dict[str, Dict[str, float]] = {
        # 官方定價（Text tokens, Standard）
        "gpt-5.4": {"input": 2.50, "output": 15.00},
        "gpt-5.2": {"input": 1.75, "output": 14.00},
        "gpt-4.1": {"input": 2.00, "output": 8.00},
        "gpt-4o-mini": {"input": 0.15, "output": 0.60},
        "gemini-3.1-flash-lite-preview": {"input": 0.25, "output": 1.50},
        "gemini-3-flash-preview": {"input": 0.50, "output": 3.00},
    }

    def __init__(
        self,
        model_name: str,
        pricing_per_1m_tokens: Optional[Dict[str, Dict[str, float]]] = None,
    ):
        self.model_name = model_name
        self.pricing_per_1m_tokens = (
            pricing_per_1m_tokens or self.DEFAULT_PRICING_PER_1M_TOKENS
        )

        self.input_tokens = 0
        self.output_tokens = 0
        self.total_tokens = 0
        self.elapsed_seconds = 0.0
        self.estimated_cost_usd = 0.0

        self.startedAt = None
        self.lock = threading.Lock()
        self.call_records: List[Dict[str, Any]] = []

    def start(self):
        with self.lock:
            self.startedAt = perf_counter()

    def end_segment(self) -> float:
        """結束本段計時並回傳秒數。"""
        with self.lock:
            if self.startedAt is None:
                return 0.0
            seg = perf_counter() - self.startedAt
            self.elapsed_seconds += seg
            self.startedAt = None
            return seg

    def addUsage(
        self,
        usage: Optional[Dict[str, Any]],
        metadata: Optional[Dict[str, Any]] = None,
        run_time_s: Optional[float] = None,
    ):
        """累加 token；total_tokens 固定為 input+output（可核對彙總）。"""
        if not usage:
            return

        input_count = int(usage.get("prompt_tokens", usage.get("input_tokens", 0)) or 0)
        output_count = int(
            usage.get("completion_tokens", usage.get("output_tokens", 0)) or 0
        )
        total_count = input_count + output_count

        with self.lock:
            record = {
                "input_tokens": input_count,
                "output_tokens": output_count,
                "total_tokens": total_count,
                "run_time(s)": round(float(run_time_s or 0.0), 3),
            }
            if metadata:
                record.update(metadata)
            self.call_records.append(record)
            self.input_tokens += input_count
            self.output_tokens += output_count
            self.total_tokens += total_count
            self.estimated_cost_usd += self.estimateCost(input_count, output_count)

    def reset(self):
        with self.lock:
            self.input_tokens = 0
            self.output_tokens = 0
            self.total_tokens = 0
            self.elapsed_seconds = 0.0
            self.estimated_cost_usd = 0.0
            self.startedAt = None
            self.call_records.clear()

    def get_call_records(self) -> List[Dict[str, Any]]:
        with self.lock:
            return list(self.call_records)

    def resolved_total_run_time_seconds(self) -> float:
        """總耗時：segment 計時與各次 addUsage(..., run_time_s=...) 加總取較大者。"""
        with self.lock:
            from_segments = float(self.elapsed_seconds)
            if self.startedAt is not None:
                from_segments += perf_counter() - self.startedAt
            from_records = sum(
                float(r.get("run_time(s)", 0.0) or 0.0) for r in self.call_records
            )
            return max(from_segments, from_records)

    def summary(self) -> Optional[Dict[str, Any]]:
        pricing = self.resolvePricing(self.model_name)
        if pricing is None:
            return None

        total_rt = self.resolved_total_run_time_seconds()
        with self.lock:
            return {
                "model": self.model_name,
                "input_tokens": self.input_tokens,
                "output_tokens": self.output_tokens,
                "total_tokens": self.total_tokens,
                "run_time(s)": round(total_rt, 3),
                "estimated_cost(USD)": round(self.estimated_cost_usd, 8),
            }

    def export_summary_dict(self) -> Dict[str, Any]:
        """匯出用：必回傳可序列化摘要（無定價表時 estimated_cost 可能為 0）。"""
        total_rt = self.resolved_total_run_time_seconds()
        with self.lock:
            return {
                "model": self.model_name,
                "input_tokens": self.input_tokens,
                "output_tokens": self.output_tokens,
                "total_tokens": self.total_tokens,
                "run_time(s)": round(total_rt, 3),
                "estimated_cost(USD)": round(self.estimated_cost_usd, 8),
            }

    def resolvePricing(self, model_name: str) -> Optional[Dict[str, float]]:
        if model_name in self.pricing_per_1m_tokens:
            return self.pricing_per_1m_tokens[model_name]

        # 支援前綴比對，例如 gpt-4o-2024-xx
        for key, value in self.pricing_per_1m_tokens.items():
            if key != "default" and model_name.startswith(key):
                return value

        return None

    def estimateCost(self, input_tokens: int, output_tokens: int) -> float:
        pricing = self.resolvePricing(self.model_name)
        if not pricing:
            return 0.0

        input_price = float(pricing.get("input", 0.0))
        output_price = float(pricing.get("output", 0.0))

        input_cost = (input_tokens / 1_000_000) * input_price
        output_cost = (output_tokens / 1_000_000) * output_price
        return input_cost + output_cost


def model_has_token_pricing(
    model_name: str,
    pricing_per_1m_tokens: Optional[Dict[str, Dict[str, float]]] = None,
) -> bool:
    """實驗腳本用：模型名稱是否在 CostTracker 定價表（含前綴比對）可解析。"""
    name = str(model_name or "").strip()
    if not name:
        return False
    tracker = CostTracker(name, pricing_per_1m_tokens=pricing_per_1m_tokens)
    return tracker.resolvePricing(tracker.model_name) is not None
