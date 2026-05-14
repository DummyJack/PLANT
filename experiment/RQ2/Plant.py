# Plant 衝突辨識實驗入口（使用 Flow 與 RQ2 config）

import sys
from pathlib import Path
from typing import Optional

RQ2_DIR = Path(__file__).resolve().parent
EXP_DIR = RQ2_DIR.parent
BASE_DIR = EXP_DIR.parent

if str(RQ2_DIR) not in sys.path:
    sys.path.insert(0, str(RQ2_DIR))
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from Plant.main import run_experiments
from Plant.utils import default_csv_path, load_rq2_dataset

PROMPT_FOR_RUNS = True


def choose_scenario(data_path: Optional[Path]) -> Optional[str]:
    path = data_path or default_csv_path()
    try:
        rows, _ = load_rq2_dataset(path)
    except (OSError, ValueError) as e:
        print(f"錯誤：無法載入資料檔以列出情境：{e}")
        sys.exit(1)

    scenario_counts: dict[str, int] = {}
    for row in rows:
        scenario = str(row.get("types") or "Unknown").strip() or "Unknown"
        scenario_counts[scenario] = scenario_counts.get(scenario, 0) + 1

    if not scenario_counts:
        print("錯誤：資料集中沒有可執行的情境")
        sys.exit(1)

    scenarios = list(scenario_counts.keys())
    print("可選情境：")
    for idx, scenario in enumerate(scenarios, 1):
        print(f"  {idx}. {scenario}（{scenario_counts[scenario]} 筆）")

    raw_scenario = input("請選擇要執行的情境（Enter: 全部，可輸入編號或名稱）：").strip()
    if not raw_scenario:
        return None
    if raw_scenario.isdigit():
        selected_idx = int(raw_scenario)
        if 1 <= selected_idx <= len(scenarios):
            return scenarios[selected_idx - 1]
        print("錯誤：情境編號超出範圍")
        sys.exit(1)
    if raw_scenario in scenario_counts:
        return raw_scenario

    print(f"錯誤：找不到情境「{raw_scenario}」")
    sys.exit(1)


def main() -> None:
    if len(sys.argv) < 2:
        data_path = None
    else:
        arg_path = Path(sys.argv[1]).expanduser()
        data_path = arg_path if arg_path.is_absolute() else (Path.cwd() / arg_path).resolve()

    scenario = choose_scenario(data_path)
    count = 0

    if PROMPT_FOR_RUNS:
        raw_runs = input("請輸入要重複執行幾次：").strip()
        if not raw_runs:
            print("錯誤：請輸入重複執行次數")
            sys.exit(1)
        try:
            runs = int(raw_runs)
        except ValueError:
            print("錯誤：重複執行次數必須是整數")
            sys.exit(1)
        if runs <= 0:
            print("錯誤：runs（重複執行次數）必須為正整數")
            sys.exit(1)
    else:
        runs = 1

    run_experiments(count=count, runs=runs, data_path=data_path, scenario=scenario)


if __name__ == "__main__":
    main()
