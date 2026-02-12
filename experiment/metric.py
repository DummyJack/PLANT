# Metric — 評測指標計算

class Metric:
    # 計算 Precision、Recall、F1-Score
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
