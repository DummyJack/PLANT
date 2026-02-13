# 從 cn_pairs.csv 取出 100 個 Conflict 和 100 個 Neutral

import csv
import random
from pathlib import Path

SRC = Path(__file__).parent / "cn_pairs.csv"
DST = Path(__file__).parent / "cn_pairs_200.csv"

SAMPLE_PER_CLASS = 100
SEED = 42


def split():
    conflicts = []
    neutrals = []

    with open(SRC, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            label = row["Class"].strip()
            if label == "Conflict":
                conflicts.append(row)
            elif label == "Neutral":
                neutrals.append(row)

    print(f"原始資料: Conflict={len(conflicts)}, Neutral={len(neutrals)}")

    random.seed(SEED)
    sampled_conflict = random.sample(conflicts, min(SAMPLE_PER_CLASS, len(conflicts)))
    sampled_neutral = random.sample(neutrals, min(SAMPLE_PER_CLASS, len(neutrals)))

    sampled = sampled_conflict + sampled_neutral
    random.shuffle(sampled)

    with open(DST, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["ID", "Text1", "Text2", "Class"])
        writer.writeheader()
        for i, row in enumerate(sampled):
            row["ID"] = i
            writer.writerow(row)

    print(f"已取出: Conflict={len(sampled_conflict)}, Neutral={len(sampled_neutral)}")
    print(f"已儲存: {DST}")


if __name__ == "__main__":
    split()
