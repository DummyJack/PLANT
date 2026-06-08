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
                "precision": round(result["precision"], 4),
                "recall": round(result["recall"], 4),
                "f1": round(result["f1"], 4),
            }
            scores.append(result)

        n = len(scores)
        macro_avg = {
            "precision": round(sum(s["precision"] for s in scores) / n, 4) if n else 0.0,
            "recall": round(sum(s["recall"] for s in scores) / n, 4) if n else 0.0,
            "f1": round(sum(s["f1"] for s in scores) / n, 4) if n else 0.0,
        }

        return {
            "macro": macro_avg,
            **per_class,
        }
