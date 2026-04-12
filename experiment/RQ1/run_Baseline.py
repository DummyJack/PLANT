import os
import json
import sys
import argparse
import time
from time import perf_counter
from pathlib import Path

from dotenv import load_dotenv

# 路徑：run_Baseline.py 在 RQ1 下，資料 ReqElicitBench_10.json、套件 Baseline/ 同在 RQ1 下
RQ1_DIR = Path(__file__).resolve().parent
BASE_DIR = RQ1_DIR.parent.parent
# 從專案主目錄 .env 讀取（含 OPENAI_API_KEY）
env_path = BASE_DIR / ".env"
load_dotenv(env_path)
DEFAULT_CONFIG_PATH = RQ1_DIR / "baseline_config.json"
# 結果輸出目錄與檔名前綴（固定於程式，不經 baseline_config.json）
RESULTS_DIR = RQ1_DIR / "results"
RESULTS_FILE_PREFIX = "Baseline"
# 預設資料檔、任務數與互動行為（固定於程式，不經 baseline_config.json）
DEFAULT_DATA_FILE = "ReqElicitBench_10.json"
# 未指定 --max-tasks 且下方為 None 時，是否在終端機詢問要跑幾題
PROMPT_FOR_MAX_TASKS = True
# 程式內預設最多任務數：None 表示不預先限定（仍可用 --max-tasks 或互動輸入）
DEFAULT_MAX_TASKS = None
# Gemini「OpenAI 相容」Chat Completions（官方文件）
GEMINI_OPENAI_COMPAT_BASE = "https://generativelanguage.googleapis.com/v1beta/openai/"
# 未指定 --base-url 且未設 OPENAI_BASE_URL 時的預設 API base（固定於程式，不經 baseline_config.json）
DEFAULT_BASE_URL = "https://api.openai.com/v1"

# 將 RQ1 目錄加入 Python 路徑，以便匯入 Baseline 套件
if str(RQ1_DIR) not in sys.path:
    sys.path.insert(0, str(RQ1_DIR))
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from Baseline.config import ReqElicitGymConfig
from Baseline.env import ReqElicitGym
import Baseline.env.prompts as baseline_prompts
import Baseline.interviewer as baseline_interviewer_module
from Baseline.interviewer import Interviewer
from utils import CostTracker, json_dump_no_scientific


def _resolve_data_path(raw: str) -> str:
    """相對路徑則相對於 RQ1 目錄解析。"""
    p = Path(raw)
    if p.is_absolute():
        return str(p.resolve())
    return str((RQ1_DIR / p).resolve())


def load_baseline_file_config(path: Path) -> dict:
    if not path.is_file():
        raise FileNotFoundError(f"找不到設定檔：{path}")
    with path.open(encoding="utf-8") as f:
        cfg = json.load(f)
    if not isinstance(cfg, dict):
        raise TypeError("baseline_config.json 頂層必須為物件")
    return cfg


def build_parser():
    """建構命令列參數解析器"""
    parser = argparse.ArgumentParser(description="執行 ReqElicitGym 評估腳本（執行全部測試樣本）")
    parser.add_argument(
        "--config",
        type=str,
        default=str(DEFAULT_CONFIG_PATH),
        help=f"實驗設定 JSON 路徑（預設 {DEFAULT_CONFIG_PATH.name}）",
    )
    parser.add_argument("--api-key", type=str, default=None, help="API Key，也可用 OPENAI_API_KEY 環境變數")
    parser.add_argument(
        "--gemini",
        action="store_true",
        help="使用 Gemini：讀取 GEMINI_API_KEY，base_url 預設為 Google OpenAI 相容端點（可用 GEMINI_BASE_URL 或 --base-url 覆寫）；請將模型設為 gemini-*",
    )
    parser.add_argument("--base-url", type=str, default=None, help="覆寫 OPENAI_BASE_URL 與程式預設 DEFAULT_BASE_URL")
    parser.add_argument("--interviewer-model", type=str, default=None, help="覆寫設定檔中的 interviewer_model")
    parser.add_argument("--gym-model", type=str, default=None, help="覆寫設定檔中的 gym_model（judge + user）")
    parser.add_argument("--use-thinking", action="store_true", help="開啟 thinking 模式（覆寫設定檔為 true）")
    parser.add_argument("--data-path", type=str, default=None, help="覆寫程式預設資料檔（可為絕對或相對 RQ1 之路徑）")
    parser.add_argument("--max-tasks", type=int, default=None, help="只跑前 N 筆；覆寫程式預設 DEFAULT_MAX_TASKS")
    parser.add_argument("--run-id", type=str, default=None, help="結果檔名用 id，未傳則以執行時間（HHMMSS）自動產生")
    parser.add_argument("--verbose", action="store_true", help="強制詳細輸出（覆寫設定檔 verbose）")
    parser.add_argument("--quiet", action="store_true", help="關閉詳細輸出（覆寫設定檔 verbose）")
    return parser


def main():
    """主函式：執行 ReqElicitGym-v8 評估（執行全部任務）"""
    args = build_parser().parse_args()

    cfg_path = Path(args.config).expanduser()
    if not cfg_path.is_absolute():
        cfg_path = (RQ1_DIR / cfg_path).resolve()
    file_cfg = load_baseline_file_config(cfg_path)
    print(f"設定檔：{cfg_path}")

    def pick(key: str, default):
        v = file_cfg.get(key, default)
        return default if v is None else v

    # api_key 不寫入 JSON，僅環境變數或命令列
    api_key = args.api_key or os.environ.get("OPENAI_API_KEY", "")
    base_url = args.base_url or os.environ.get("OPENAI_BASE_URL") or DEFAULT_BASE_URL
    if args.gemini:
        gemini_key = os.environ.get("GEMINI_API_KEY", "")
        api_key = args.api_key or gemini_key
        if not api_key:
            print("錯誤：使用 --gemini 時請在 .env 設定 GEMINI_API_KEY，或傳入 --api-key")
            sys.exit(1)
        base_url = (
            args.base_url
            or os.environ.get("GEMINI_BASE_URL")
            or GEMINI_OPENAI_COMPAT_BASE
        )
    interviewer_model = args.interviewer_model or pick("interviewer_model", "gpt-4o-mini")
    gym_model = args.gym_model or pick("gym_model", "gpt-5.2")
    use_thinking = bool(args.use_thinking or pick("use_thinking", False))
    data_path = args.data_path or _resolve_data_path(DEFAULT_DATA_FILE)

    max_tasks = args.max_tasks
    if max_tasks is None:
        max_tasks = DEFAULT_MAX_TASKS
        if max_tasks is not None and (not isinstance(max_tasks, int) or max_tasks <= 0):
            max_tasks = None
    if max_tasks is None and PROMPT_FOR_MAX_TASKS:
        raw = input("請輸入要執行的任務數量（直接 Enter 為全部，或輸入數字如 3）：").strip()
        if raw:
            try:
                max_tasks = int(raw)
                if max_tasks <= 0:
                    max_tasks = None
            except ValueError:
                max_tasks = None

    run_id = args.run_id or time.strftime("%H%M%S")
    if args.quiet:
        verbose = False
    elif args.verbose:
        verbose = True
    else:
        verbose = bool(pick("verbose", True))

    judge_temperature = float(pick("judge_temperature", 0.0))
    judge_max_tokens = int(pick("judge_max_tokens", 1024))
    judge_timeout = float(pick("judge_timeout", 30.0))
    user_temperature = float(pick("user_temperature", 0.7))
    user_max_tokens = int(pick("user_max_tokens", 1024))
    user_timeout = float(pick("user_timeout", 30.0))
    user_answer_quality = str(pick("user_answer_quality", "high"))
    max_steps = int(pick("max_steps", 20))
    interviewer_temperature = float(pick("interviewer_temperature", 0.0))
    interviewer_timeout = float(pick("interviewer_timeout", 60.0))
    interviewer_max_tokens = int(pick("interviewer_max_tokens", 1024))
    interviewer_max_tokens_thinking = int(pick("interviewer_max_tokens_thinking", 8192))

    # 統一使用同一套 API key 與 base URL
    # 如需對 judge/user 再細分 key，可繼續用 JUDGE_API_KEY / USER_API_KEY 覆寫
    judge_api_key = os.getenv("JUDGE_API_KEY", api_key)
    user_api_key = os.getenv("USER_API_KEY", api_key)
    judge_base_url = os.getenv("JUDGE_BASE_URL", base_url)
    user_base_url = os.getenv("USER_BASE_URL", base_url)

    if not api_key:
        print("錯誤：請在專案主目錄 .env 中設定 OPENAI_API_KEY，或設定環境變數 / 使用 --api-key 參數")
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

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    evaluation_result_path = str(RESULTS_DIR / f"result_{RESULTS_FILE_PREFIX}_{run_id}.json")
    conversation_result_path = str(RESULTS_DIR / f"record_{RESULTS_FILE_PREFIX}_{run_id}.json")
    cost_result_path = str(RESULTS_DIR / f"cost_{RESULTS_FILE_PREFIX}_{run_id}.json")
    llm = interviewer_model  # interviewer 使用的模型

    # 建立設定
    config = ReqElicitGymConfig(
        data_path=data_path,
        judge_api_key=judge_api_key,
        judge_base_url=judge_base_url,
        judge_model_name=gym_model,
        judge_temperature=judge_temperature,
        judge_max_tokens=judge_max_tokens,
        judge_timeout=judge_timeout,
        user_api_key=user_api_key,
        user_base_url=user_base_url,
        user_model_name=gym_model,
        user_temperature=user_temperature,
        user_max_tokens=user_max_tokens,
        user_timeout=user_timeout,
        user_answer_quality=user_answer_quality,
        max_steps=max_steps,
        verbose=verbose,
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

    interviewer_max_tokens = (
        interviewer_max_tokens_thinking if use_thinking else interviewer_max_tokens
    )
    interviewer = Interviewer(
        api_key=api_key,
        base_url=base_url,
        model_name=llm,
        temperature=interviewer_temperature,
        max_tokens=interviewer_max_tokens,
        timeout=interviewer_timeout,
        use_thinking=use_thinking,
    )
    interviewer_cost_tracker = CostTracker(model_name=interviewer.model_name)
    user_cost_tracker = CostTracker(model_name=gym_model)
    _orig_ask_question = interviewer.ask_question
    _orig_prompt_model_call = baseline_prompts.model_call
    _orig_prompt_model_call_with_thinking = baseline_prompts.model_call_with_thinking
    _orig_interviewer_model_call = baseline_interviewer_module.model_call
    _orig_interviewer_model_call_with_thinking = baseline_interviewer_module.model_call_with_thinking

    def _tracked_ask_question(conversation_history, return_usage=False):
        start = perf_counter()
        out = _orig_ask_question(conversation_history, return_usage=return_usage)
        elapsed = perf_counter() - start
        if return_usage:
            question, usage_info = out
            interviewer_cost_tracker.addUsage(
                usage_info or {},
                metadata={"action": "baseline.interviewer.ask_question"},
                run_time_s=elapsed,
            )
            return question, usage_info
        return out

    def _tracked_model_call(
        system_prompt,
        user_prompt,
        model_config,
        return_json=True,
        return_usage=False,
    ):
        start = perf_counter()
        response, usage_info = _orig_prompt_model_call(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            model_config=model_config,
            return_json=return_json,
            return_usage=True,
        )
        elapsed = perf_counter() - start
        if system_prompt == baseline_prompts.PASSIVE_RESPONSE_SYSTEM:
            user_cost_tracker.addUsage(
                usage_info or {},
                metadata={"action": "baseline.user.generate_response"},
                run_time_s=elapsed,
            )
        if return_usage:
            return response, usage_info
        return response

    interviewer.ask_question = _tracked_ask_question
    baseline_prompts.model_call = _tracked_model_call
    baseline_interviewer_module.model_call = _tracked_model_call
    baseline_prompts.model_call_with_thinking = _orig_prompt_model_call_with_thinking
    baseline_interviewer_module.model_call_with_thinking = _orig_interviewer_model_call_with_thinking
    print(f"Interviewer 已建立：{interviewer}")

    # 執行所有任務（環境會自動記錄對話並計算評估指標）
    print("\n" + "=" * 60)
    print("開始執行全量評估實驗...")
    print("=" * 60)
    results = env.run_all_tasks(interviewer)
    interviewer.ask_question = _orig_ask_question
    baseline_prompts.model_call = _orig_prompt_model_call
    baseline_prompts.model_call_with_thinking = _orig_prompt_model_call_with_thinking
    baseline_interviewer_module.model_call = _orig_interviewer_model_call
    baseline_interviewer_module.model_call_with_thinking = _orig_interviewer_model_call_with_thinking

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

    # 儲存成本摘要（interviewer token/cost）
    try:
        interviewer_summary = interviewer_cost_tracker.export_summary_dict()
        user_summary = user_cost_tracker.export_summary_dict()
        cost_payload = {
            "agents": {
                "interviewer": interviewer_summary,
                "user": user_summary,
            },
            "totals": {
                "input_tokens": int(interviewer_summary.get("input_tokens", 0) or 0)
                + int(user_summary.get("input_tokens", 0) or 0),
                "output_tokens": int(interviewer_summary.get("output_tokens", 0) or 0)
                + int(user_summary.get("output_tokens", 0) or 0),
                "total_tokens": int(interviewer_summary.get("total_tokens", 0) or 0)
                + int(user_summary.get("total_tokens", 0) or 0),
                "run_time(s)": round(
                    float(interviewer_summary.get("run_time(s)", 0.0) or 0.0)
                    + float(user_summary.get("run_time(s)", 0.0) or 0.0),
                    3,
                ),
                "estimated_cost(USD)": round(
                    float(interviewer_summary.get("estimated_cost(USD)", 0.0) or 0.0)
                    + float(user_summary.get("estimated_cost(USD)", 0.0) or 0.0),
                    8,
                ),
            },
        }
        with open(cost_result_path, "w", encoding="utf-8") as f:
            json_dump_no_scientific(cost_payload, f, indent=2, ensure_ascii=False)
        print(f"成本摘要已儲存至：{cost_result_path}")
    except Exception as e:
        print(f"儲存成本摘要時發生錯誤：{e}")
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

