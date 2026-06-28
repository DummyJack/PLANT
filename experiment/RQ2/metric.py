import math
from decimal import Decimal, ROUND_HALF_UP
from typing import Any


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


def round_float_tree_to_4(value: Any) -> Any:
    if isinstance(value, bool):
        return value
    if isinstance(value, float):
        return round_to_4(value)
    if isinstance(value, list):
        return [round_float_tree_to_4(item) for item in value]
    if isinstance(value, dict):
        return {key: round_float_tree_to_4(item) for key, item in value.items()}
    return value


class Metric:

    @staticmethod
    def binary(y_true: list, y_pred: list, positive_label: str = "Conflict") -> dict:
        if len(y_true) != len(y_pred):
            raise ValueError("y_true and y_pred must have the same length")

        tp = fp = fn = 0
        for t, p in zip(y_true, y_pred):
            if t == positive_label and p == positive_label:
                tp += 1
            elif t != positive_label and p == positive_label:
                fp += 1
            elif t == positive_label and p != positive_label:
                fn += 1

        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0

        return {
            "precision": precision,
            "recall": recall,
            "f1": f1,
        }

    @staticmethod
    def macro(y_true: list, y_pred: list, labels: list = None) -> dict:
        if len(y_true) != len(y_pred):
            raise ValueError("y_true and y_pred must have the same length")

        if labels is None:
            labels = sorted(set(y_true) | set(y_pred))

        per_class = {}
        scores = []

        for label in labels:
            result = Metric.binary(y_true, y_pred, positive_label=label)
            per_class[label] = {
                "precision": round_to_4(result["precision"]),
                "recall": round_to_4(result["recall"]),
                "f1": round_to_4(result["f1"]),
            }
            scores.append(result)

        n = len(scores)
        macro_avg = {
            "precision": round_to_4(sum(s["precision"] for s in scores) / n) if n else 0.0,
            "recall": round_to_4(sum(s["recall"] for s in scores) / n) if n else 0.0,
            "f1": round_to_4(sum(s["f1"] for s in scores) / n) if n else 0.0,
        }

        return {
            "macro": macro_avg,
            **per_class,
        }
