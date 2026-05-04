# Plant 衝突辨識實驗入口（使用 Flow 與 RQ2 config）

import sys
from pathlib import Path

RQ2_DIR = Path(__file__).resolve().parent
EXP_DIR = RQ2_DIR.parent
BASE_DIR = EXP_DIR.parent

if str(RQ2_DIR) not in sys.path:
    sys.path.insert(0, str(RQ2_DIR))
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from Plant.main import run_experiments

PROMPT_FOR_RUNS = True


def main() -> None:
    if len(sys.argv) < 2:
        data_path = None
    else:
        arg_path = Path(sys.argv[1]).expanduser()
        data_path = arg_path if arg_path.is_absolute() else (Path.cwd() / arg_path).resolve()

    raw_count = input("請輸入要執行的任務數量（Enter: 全做）：").strip()
    if not raw_count:
        count = 0
    else:
        try:
            count = int(raw_count)
        except ValueError:
            print("錯誤：任務數量必須是整數")
            sys.exit(1)
        if count < 0:
            print("錯誤：任務數量不可為負數")
            sys.exit(1)

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

    run_experiments(count=count, runs=runs, data_path=data_path)


if __name__ == "__main__":
    main()
