"""
執行 ReqElicitGym 評估腳本（執行全部測試樣本）

本腳本：
1. 從測試資料中載入所有任務（不再只取前 3 個）
2. 建立 ReqElicitGym 環境
3. 建構 interviewer（待評估的模型）
4. 執行所有任務並自動記錄、評估
5. 儲存評估結果與對話過程檔案（含變異數及依 application_type 分類的統計）
"""

import os
import json
import sys
import argparse
import time
from pathlib import Path

from dotenv import load_dotenv

# 路徑：run_Baseline.py 在 RQ1 下，資料 ReqElicitBench.json、套件 Baseline/ 同在 RQ1 下
RQ1_DIR = Path(__file__).resolve().parent
# 從專案 config/.env 讀取（含 OPENAI_API_KEY）
_env_path = RQ1_DIR.parent.parent / "config" / ".env"
load_dotenv(_env_path)
BASELINE_DIR = RQ1_DIR / "Baseline"
RESULTS_DIR = RQ1_DIR / "results"

# 將 RQ1 目錄加入 Python 路徑，以便匯入 Baseline 套件
if str(RQ1_DIR) not in sys.path:
    sys.path.insert(0, str(RQ1_DIR))

from Baseline.config import ReqElicitGymConfig
from Baseline.env import ReqElicitGym
from Baseline.interviewer import Interviewer


def build_parser():
    """建構命令列參數解析器"""
    parser = argparse.ArgumentParser(description="執行 ReqElicitGym 評估腳本（執行全部測試樣本）")
    parser.add_argument("--api-key", type=str, default=None, help="API Key，也可用 OPENAI_API_KEY 環境變數")
    parser.add_argument("--base-url", type=str, default=None, help="API Base URL，也可用 OPENAI_BASE_URL 環境變數")
    parser.add_argument("--interviewer-model", type=str, default=None, help="Interviewer 使用的 LLM 模型")
    parser.add_argument("--gym-model", type=str, default="gpt-5.2", help="GYM（judge + user）使用的 LLM 模型，預設 gpt-5.2")
    parser.add_argument("--use-thinking", action="store_true", help="是否開啟 thinking 模式（會呼叫帶 enable_thinking 的介面）")
    parser.add_argument("--data-path", type=str, default=None, help="測試資料檔案路徑，預設 RQ1/ReqElicitBench.json")
    parser.add_argument("--max-tasks", type=int, default=None, help="最多執行的需求案例數量（預設全部，例如 3 表示只跑前 3 筆）")
    parser.add_argument("--run-id", type=str, default=None, help="結果檔名用 id，未傳則以執行時間（HHMMSS）自動產生")
    parser.add_argument("--verbose", action="store_true", help="詳細輸出")
    return parser


def main():
    """主函式：執行 ReqElicitGym-v8 評估（執行全部任務）"""
    args = build_parser().parse_args()

    # ========= 預設設定區域 =========
    default_data_path = str(RQ1_DIR / "ReqElicitBench.json")
    DEFAULTS = {
        "api_key": os.environ.get("OPENAI_API_KEY", ""),
        "base_url": os.environ.get("OPENAI_BASE_URL") or "https://api.openai.com/v1",
        "interviewer_model": "gpt-4o-mini",
        "gym_model": "gpt-5.2",
        "use_thinking": False,
        "data_path": default_data_path,
        "verbose": True,
    }

    # ========= 從命令列參數或環境變數取得設定 =========
    api_key = args.api_key or DEFAULTS["api_key"]
    base_url = args.base_url or DEFAULTS["base_url"]
    interviewer_model = args.interviewer_model or DEFAULTS["interviewer_model"]
    gym_model = args.gym_model or DEFAULTS["gym_model"]
    use_thinking = args.use_thinking or DEFAULTS["use_thinking"]
    data_path = args.data_path or DEFAULTS["data_path"]
    max_tasks = args.max_tasks
    if max_tasks is None:
        raw = input("請輸入要執行的任務數量（直接 Enter 為全部，或輸入數字如 3）：").strip()
        if raw:
            try:
                max_tasks = int(raw)
                if max_tasks <= 0:
                    max_tasks = None
            except ValueError:
                max_tasks = None
    run_id = args.run_id or time.strftime("%H%M%S")
    verbose = args.verbose or DEFAULTS["verbose"]

    # 統一使用同一套 API key 與 base URL
    # 如需對 judge/user 再細分 key，可繼續用 JUDGE_API_KEY / USER_API_KEY 覆寫
    judge_api_key = os.getenv("JUDGE_API_KEY", api_key)
    user_api_key = os.getenv("USER_API_KEY", api_key)
    judge_base_url = os.getenv("JUDGE_BASE_URL", base_url)
    user_base_url = os.getenv("USER_BASE_URL", base_url)

    if not api_key:
        print("錯誤：請在 config/.env 中設定 OPENAI_API_KEY，或設定環境變數 / 使用 --api-key 參數")
        sys.exit(1)

    # 檢查資料檔案
    if not os.path.exists(data_path):
        print(f"錯誤：找不到檔案 {data_path}")
        print("請確保資料檔案存在")
        sys.exit(1)

    # 載入任務，可選只取前 N 筆
    try:
        print(f"\n正在載入資料檔案：{data_path}")
        with open(data_path, "r", encoding="utf-8") as f:
            all_tasks = json.load(f)
        total_tasks_in_file = len(all_tasks)
        if max_tasks is not None and max_tasks > 0:
            all_tasks = all_tasks[:max_tasks]
            print(f"資料檔案共 {total_tasks_in_file} 個任務，本輪執行前 {len(all_tasks)} 個（--max-tasks={max_tasks}）")
        else:
            print(f"資料檔案包含 {total_tasks_in_file} 個任務，將對全部任務進行評估")
        # 若限制了數量，寫入暫存檔供 env 載入（env 只認 data_path）
        if max_tasks is not None and max_tasks > 0 and len(all_tasks) < total_tasks_in_file:
            subset_path = RQ1_DIR / ".reqelicit_subset.json"
            with open(subset_path, "w", encoding="utf-8") as f:
                json.dump(all_tasks, f, ensure_ascii=False, indent=2)
            data_path = str(subset_path)
    except Exception as e:
        print(f"錯誤：無法載入資料檔案：{e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)

    # 結果輸出到 RQ1/results，檔名：result_Baseline_<run_id>.json / record_Baseline_<run_id>.json
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    evaluation_result_path = str(RESULTS_DIR / f"result_Baseline_{run_id}.json")
    conversation_result_path = str(RESULTS_DIR / f"record_Baseline_{run_id}.json")
    llm = interviewer_model  # interviewer 使用的模型

    # 建立設定
    config = ReqElicitGymConfig(
        data_path=data_path,  # 直接使用全量資料檔案
        # Judge 設定（用於判斷 interviewer 的動作）
        judge_api_key=judge_api_key,
        judge_base_url=judge_base_url,
        judge_model_name=gym_model,
        judge_temperature=0.0,
        judge_max_tokens=1024,
        judge_timeout=30.0,
        # 模擬使用者設定
        user_api_key=user_api_key,
        user_base_url=user_base_url,
        user_model_name=gym_model,
        user_temperature=0.7,
        user_max_tokens=1024,
        user_timeout=30.0,
        # 使用者回答品質
        user_answer_quality="high",  # 可為 "high", "medium", 或 "low"
        # 環境設定
        max_steps=20,
        verbose=verbose,
        # 設定結果檔案路徑
        evaluation_result_path=evaluation_result_path,
        conversation_result_path=conversation_result_path,
    )

    # 建立環境
    print("\n正在建立環境...")
    try:
        env = ReqElicitGym(config)
    except Exception as e:
        print(f"錯誤：建立環境失敗：{e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)

    # 重置任務索引：__init__ 中 reset() 已消耗 task_0，需重置以便 run_all_tasks 從 task_0 開始
    env.current_task_index = 0

    # 建構 interviewer（在外部建構，不依賴環境設定）
    # 若開啟 thinking，需要較大的 max_tokens
    interviewer_max_tokens = 8192 if use_thinking else 1024
    interviewer = Interviewer(
        api_key=api_key,
        base_url=base_url,
        model_name=llm,  # 使用上方設定的模型名稱
        temperature=0.0,
        max_tokens=interviewer_max_tokens,
        # timeout=30.0,
        timeout=60.0,  # kimi2.5 的 timeout 為 60 秒
        use_thinking=use_thinking,
    )
    print(f"Interviewer 已建立：{interviewer}")

    # 執行所有任務（環境會自動記錄對話並計算評估指標）
    print("\n" + "=" * 60)
    print("開始執行全量評估實驗...")
    print("=" * 60)
    results = env.run_all_tasks(interviewer)

    # 儲存評估結果檔案（含變異數及依 application_type 分類的統計）
    # 若不傳 file_path 或傳入 None，會使用 config 中設定的路徑
    try:
        env.save_evaluation_results(file_path=None, interviewer_model_name=interviewer.model_name)
        print(f"\n評估結果已儲存至：{config.evaluation_result_path}")
    except Exception as e:
        print(f"儲存評估結果時發生錯誤：{e}")
        import traceback

        traceback.print_exc()

    # 儲存對話過程檔案（含每輪的 elicitation_ratio）
    # 若不傳 file_path 或傳入 None，會使用 config 中設定的路徑
    try:
        env.save_conversation_results(file_path=None)
        print(f"對話過程已儲存至：{config.conversation_result_path}")
    except Exception as e:
        print(f"儲存對話過程時發生錯誤：{e}")
        import traceback

        traceback.print_exc()

    # 列印總結
    print("\n" + "=" * 60)
    print("所有任務完成！")
    print("=" * 60)
    conversation_results = results.get("conversation_results", [])
    if conversation_results:
        print(f"總任務數：{len(conversation_results)}")
        avg_turns = sum(r.get("total_turns", 0) for r in conversation_results) / len(conversation_results)
        print(f"平均對話輪數：{avg_turns:.1f}")

    # 列印評估指標總結
    overall_metrics = results.get("overall_metrics", {})
    if overall_metrics:
        print(f"\n評估指標總結：")
        print(f"  總測試樣本數：{overall_metrics.get('total_tasks', 0)}")
        print(f"  總隱式需求數：{overall_metrics.get('total_requirements_all_tasks', 0)}")
        print(f"  總取得數：{overall_metrics.get('total_elicited_all_tasks', 0)}")
        print(f"\n平均指標（基於測試樣本平均）：")
        print(f"  平均取得比例：{overall_metrics.get('elicitation_ratio', 0.0):.2%}")
        print(f"  平均 TKQR：{overall_metrics.get('tkqr', 0.0):.4f}")
        print(f"  平均 ORA：{overall_metrics.get('ora', 0.0):.4f}")
        print(f"\n變異數：")
        print(f"  取得比例變異數：{overall_metrics.get('variance_elicitation_ratio', 0.0):.6f}")
        print(f"  TKQR 變異數：{overall_metrics.get('variance_tkqr', 0.0):.6f}")
        print(f"  ORA 變異數：{overall_metrics.get('variance_ora', 0.0):.6f}")
        print(f"\n總體比例（基於總計數）：")
        print(f"  總取得比例：{overall_metrics.get('elicitation_ratio_from_totals', 0.0):.2%}")

        # 列印依 application_type 分類的統計
        app_type_stats = overall_metrics.get("application_type_statistics", {})
        if app_type_stats:
            print(f"\n依應用類型統計：")
            print(f"{'Application Type':<40} {'任務數':<10} {'平均取得比例':<15} {'平均TKQR':<12} {'平均ORA':<12}")
            print("-" * 100)
            for app_type in sorted(app_type_stats.keys()):
                stats = app_type_stats[app_type]
                print(
                    f"{app_type:<40} {stats['num_tasks']:<10} "
                    f"{stats['average_elicitation_ratio']:>13.2%} "
                    f"{stats['average_tkqr']:>10.4f} "
                    f"{stats['average_ora']:>10.4f}"
                )

    return results

if __name__ == "__main__":
    main()

