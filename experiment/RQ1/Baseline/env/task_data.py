import json
import os
from typing import Dict, Any, List


def load_tasks(data_path: str) -> List[Dict[str, Any]]:
    if not os.path.exists(data_path):
        raise FileNotFoundError(f"Data file not found: {data_path}")

    with open(data_path, 'r', encoding='utf-8') as f:
        tasks = json.load(f)


    for i, task in enumerate(tasks):
        if "id" not in task:
            task["id"] = f"task_{i}"

    return tasks
