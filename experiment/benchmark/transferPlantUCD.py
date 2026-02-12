import json
import csv
from pathlib import Path

DIR = Path(__file__).parent
json_path = DIR / "PlantUCD_dataset_test.json"
csv_path = DIR / "PlantUCD_dataset_test.csv"

with open(json_path, "r", encoding="utf-8") as f:
    data = json.load(f)

with open(csv_path, "w", encoding="utf-8", newline="") as f:
    writer = csv.writer(f)
    writer.writerow(["ID", "HumanLang", "PlantUML", "Output_AST"])
    for i, item in enumerate(data):
        writer.writerow([
            i,
            item.get("HumanLang", ""),
            item.get("PlantUML", ""),
            json.dumps(item.get("Output_AST", {}), ensure_ascii=False),
        ])

print(f"完成，共 {len(data)} 筆，已儲存: {csv_path}")
