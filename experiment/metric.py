# Metric — 評測指標計算

class Metric:
    @staticmethod
    def precision_recall_f1(y_true: list, y_pred: list, positive: str = "Conflict") -> dict:
        tp = fp = fn = tn = 0
        for t, p in zip(y_true, y_pred):
            if t == positive and p == positive:
                tp += 1
            elif t != positive and p == positive:
                fp += 1
            elif t == positive and p != positive:
                fn += 1
            else:
                tn += 1

        precision = tp / (tp + fp) if (tp + fp) else 0.0
        recall = tp / (tp + fn) if (tp + fn) else 0.0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0

        return {
            "precision": round(precision, 4),
            "recall": round(recall, 4),
            "f1": round(f1, 4),
        }

    # Micro 平均：各類別的 TP/FP/FN 加總後再算 P/R/F1
    @staticmethod
    def micro(y_true: list, y_pred: list, labels: list = None) -> dict:
        if labels is None:
            labels = sorted(set(y_true) | set(y_pred))

        total_tp = total_fp = total_fn = 0
        for label in labels:
            for t, p in zip(y_true, y_pred):
                if t == label and p == label:
                    total_tp += 1
                elif t != label and p == label:
                    total_fp += 1
                elif t == label and p != label:
                    total_fn += 1

        precision = total_tp / (total_tp + total_fp) if (total_tp + total_fp) else 0.0
        recall = total_tp / (total_tp + total_fn) if (total_tp + total_fn) else 0.0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0

        return {
            "precision": round(precision, 4),
            "recall": round(recall, 4),
            "f1": round(f1, 4),
        }

    # Macro 平均：各類別分別算 P/R/F1 再取平均
    @staticmethod
    def macro(y_true: list, y_pred: list, labels: list = None) -> dict:
        if labels is None:
            labels = sorted(set(y_true) | set(y_pred))

        per_class = {}
        for label in labels:
            per_class[label.lower()] = Metric.precision_recall_f1(y_true, y_pred, positive=label)

        n = len(per_class)
        macro_avg = {}
        for key in ["precision", "recall", "f1"]:
            macro_avg[key] = round(sum(v[key] for v in per_class.values()) / n, 4) if n else 0.0

        return {"macro": macro_avg, **per_class}
