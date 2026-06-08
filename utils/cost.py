# Handles cost logic for shared utility behavior for the Plant runtime.
import threading

from time import perf_counter
from typing import Any, Dict, List, Optional


# ========
# Defines CostTracker class for this module workflow.
# ========
class CostTracker:

    DEFAULT_PRICING_PER_1M_TOKENS: Dict[str, Dict[str, float]] = {
        "gpt-5.2": {"input": 1.75, "output": 14.00},
        "gpt-4.1": {"input": 2.00, "output": 8.00},
    }

    # ========
    # Defines __init__ function for this module workflow.
    # ========
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

    # ========
    # Defines start function for this module workflow.
    # ========
    def start(self):
        with self.lock:
            self.startedAt = perf_counter()

    # ========
    # Defines end segment function for this module workflow.
    # ========
    def end_segment(self) -> float:
        with self.lock:
            if self.startedAt is None:
                return 0.0
            seg = perf_counter() - self.startedAt
            self.elapsed_seconds += seg
            self.startedAt = None
            return seg

    # ========
    # Defines add usage function for this module workflow.
    # ========
    def add_usage(
        self,
        usage: Optional[Dict[str, Any]],
        metadata: Optional[Dict[str, Any]] = None,
        run_time_s: Optional[float] = None,
    ):
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
            self.estimated_cost_usd += self.estimate_cost(input_count, output_count)

    # ========
    # Defines reset function for this module workflow.
    # ========
    def reset(self):
        with self.lock:
            self.input_tokens = 0
            self.output_tokens = 0
            self.total_tokens = 0
            self.elapsed_seconds = 0.0
            self.estimated_cost_usd = 0.0
            self.startedAt = None
            self.call_records.clear()

    # ========
    # Defines get call records function for this module workflow.
    # ========
    def get_call_records(self) -> List[Dict[str, Any]]:
        with self.lock:
            return list(self.call_records)

    # ========
    # Defines resolved total run time seconds function for this module workflow.
    # ========
    def resolved_total_run_time_seconds(self) -> float:
        with self.lock:
            from_segments = float(self.elapsed_seconds)
            if self.startedAt is not None:
                from_segments += perf_counter() - self.startedAt
            from_records = sum(
                float(r.get("run_time(s)", 0.0) or 0.0) for r in self.call_records
            )
            return max(from_segments, from_records)

    # ========
    # Defines summary function for this module workflow.
    # ========
    def summary(self) -> Optional[Dict[str, Any]]:
        pricing = self.resolve_pricing(self.model_name)
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

    # ========
    # Defines export summary dict function for this module workflow.
    # ========
    def export_summary_dict(self) -> Dict[str, Any]:
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

    # ========
    # Defines resolve pricing function for this module workflow.
    # ========
    def resolve_pricing(self, model_name: str) -> Optional[Dict[str, float]]:
        if model_name in self.pricing_per_1m_tokens:
            return self.pricing_per_1m_tokens[model_name]

        for key, value in self.pricing_per_1m_tokens.items():
            if key != "default" and model_name.startswith(key):
                return value

        return None

    # ========
    # Defines estimate cost function for this module workflow.
    # ========
    def estimate_cost(self, input_tokens: int, output_tokens: int) -> float:
        pricing = self.resolve_pricing(self.model_name)
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
    name = str(model_name or "").strip()
    if not name:
        return False
    tracker = CostTracker(name, pricing_per_1m_tokens=pricing_per_1m_tokens)
    return tracker.resolve_pricing(tracker.model_name) is not None
