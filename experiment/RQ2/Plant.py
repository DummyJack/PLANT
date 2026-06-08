# Runs the RQ2 Plant conflict experiment workflow.
import sys
from pathlib import Path
from typing import Optional

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
EXPERIMENT_ROOT = Path(__file__).resolve().parent
if str(EXPERIMENT_ROOT) not in sys.path:
    sys.path.insert(0, str(EXPERIMENT_ROOT))

from utils.clean import apply_entrypoint_bootstrap

apply_entrypoint_bootstrap()

RQ2_DIR = Path(__file__).resolve().parent
EXP_DIR = RQ2_DIR.parent
BASE_DIR = EXP_DIR.parent

from Plant.main import run_experiments
from Plant.utils import default_csv_path, load_rq2_dataset

ask_runs = True

# ========
# Defines choose scenarios function for this experiment module.
# ========
def choose_scenarios(data_path: Optional[Path]) -> Optional[list[str]]:
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

    raw_scenario = input("請選擇要執行的情境（Enter: 全部，可輸入 1,3,5）：").strip()
    if not raw_scenario:
        return None
    tokens = [token.strip() for token in raw_scenario.split(",") if token.strip()]
    if not tokens or any(not token.isdigit() for token in tokens):
        print("錯誤：請輸入情境編號；多個情境請使用 1,3,5 格式")
        sys.exit(1)
    selected: list[str] = []
    seen: set[int] = set()
    for token in tokens:
        selected_idx = int(token)
        if selected_idx < 1 or selected_idx > len(scenarios):
            print("錯誤：情境編號超出範圍")
            sys.exit(1)
        if selected_idx in seen:
            continue
        seen.add(selected_idx)
        selected.append(scenarios[selected_idx - 1])
    return selected

# ========
# Defines main function for this experiment module.
# ========
def main() -> None:
    if len(sys.argv) < 2:
        data_path = None
    else:
        arg_path = Path(sys.argv[1]).expanduser()
        data_path = arg_path if arg_path.is_absolute() else (Path.cwd() / arg_path).resolve()

    scenarios = choose_scenarios(data_path)
    count = 0

    if ask_runs:
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

    run_experiments(count=count, runs=runs, data_path=data_path, scenarios=scenarios)

if __name__ == "__main__":
    main()
