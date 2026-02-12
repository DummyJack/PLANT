# BaselineModel 函式輸出結果

import json
from baseline import BaselineModel

model = BaselineModel()

# 測試 detect_conflict
print("=== detect_conflict ===")
result = model.detect_conflict(
    "The system shall support up to 4 Viewers.",
    "The system shall support up to 8 Viewers."
)
print(result)

print()

# 測試 generate_plantuml
print("=== generate_plantuml ===")
result = model.generate_plantuml(
    "TrafficEvent includes attributes such as eventId, eventType, timestamp, and description, and is associated with EventLogger, which provides the logEvent method."
)
print(json.dumps(result, indent=2, ensure_ascii=False))
