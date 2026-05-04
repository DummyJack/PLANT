import os
import json
import sys
import re
from time import perf_counter
from pathlib import Path
from statistics import mean

import numpy as np
from typing import List

from dotenv import load_dotenv

# 路徑：run_Baseline.py 在 RQ1 下，資料 ReqElicitBench_10.json、套件 Baseline/ 同在 RQ1 下
RQ1_DIR = Path(__file__).resolve().parent
BASE_DIR = RQ1_DIR.parent.parent
# 從專案主目錄 .env 讀取（含 OPENAI_API_KEY）
env_path = BASE_DIR / ".env"
load_dotenv(env_path)
# Baseline 設定檔位於 Baseline/config.json。
DEFAULT_CONFIG_PATH = RQ1_DIR / "Baseline" / "config.json"
# 結果輸出目錄與檔名前綴（固定於程式，不經 Baseline/config.json）
RESULTS_DIR = RQ1_DIR / "results"
RESULTS_FILE_PREFIX = "Baseline"
# 預設資料檔、任務數與互動行為（固定於程式，不經 Baseline/config.json）
DEFAULT_DATA_FILE = "ReqElicitBench_10.json"
# 未設定 max_tasks 且下方為 None 時，是否在終端機詢問要跑幾題
PROMPT_FOR_MAX_TASKS = True
# 未設定 runs 時，是否在終端機詢問要跑幾次
PROMPT_FOR_RUNS = True
# 程式內預設最多任務數：None 表示不預先限定（仍可用互動輸入）
DEFAULT_MAX_TASKS = None
# Gemini「OpenAI 相容」Chat Completions（官方文件）
GEMINI_OPENAI_COMPAT_BASE = "https://generativelanguage.googleapis.com/v1beta/openai/"
# 未指定 --base-url 且未設 OPENAI_BASE_URL 時的預設 API base（固定於程式，不經 Baseline/config.json）
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
from utils import CostTracker, json_dump_no_scientific, model_has_token_pricing


def resolve_data_path(raw: str) -> str:
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
        raise TypeError("Baseline/config.json 頂層必須為物件")
    return cfg


def next_result_index(prefix: str, results_dir: Path) -> int:
    """取得下一個輸出編號（同 prefix 下取現有最大值 +1）。"""
    pat = re.compile(rf"^(?:result|record|cost)_{re.escape(prefix)}_(\d+)\.json$")
    max_idx = 0
    for p in results_dir.glob(f"*_{prefix}_*.json"):
        m = pat.match(p.name)
        if not m:
            continue
        try:
            max_idx = max(max_idx, int(m.group(1)))
        except ValueError:
            continue
    return max_idx + 1


def main():
    """主函式：執行 ReqElicitGym-v8 評估（執行全部任務）"""
    cfg_path = DEFAULT_CONFIG_PATH.resolve()
    file_cfg = load_baseline_file_config(cfg_path)
    print(f"設定檔：{cfg_path}")

    def pick(key: str, default):
        v = file_cfg.get(key, default)
        return default if v is None else v

    # api_key 不寫入 JSON，僅環境變數；Gemini 請在 Baseline/config.json 設 "use_gemini": true
    use_gemini = bool(pick("use_gemini", False))
    api_key = os.environ.get("OPENAI_API_KEY", "")
    base_url = os.environ.get("OPENAI_BASE_URL") or DEFAULT_BASE_URL
    if use_gemini:
        gemini_key = os.environ.get("GEMINI_API_KEY", "")
        api_key = gemini_key
        if not api_key:
            print("錯誤：use_gemini 為 true 時請在 .env 設定 GEMINI_API_KEY")
            sys.exit(1)
        base_url = os.environ.get("GEMINI_BASE_URL") or GEMINI_OPENAI_COMPAT_BASE
    interviewer_model = pick("interviewer_model", "gpt-4o-mini")
    gym_model = pick("gym_model", "gpt-5.2")
    use_thinking = bool(pick("use_thinking", False))
    data_path = resolve_data_path(DEFAULT_DATA_FILE)

    max_tasks = None
    if max_tasks is None:
        max_tasks = DEFAULT_MAX_TASKS
        if max_tasks is not None and (not isinstance(max_tasks, int) or max_tasks <= 0):
            max_tasks = None
    if max_tasks is None and PROMPT_FOR_MAX_TASKS:
        raw = input("請輸入要執行的任務數量（Enter: 全做）：").strip()
        if raw:
            try:
                max_tasks = int(raw)
                if max_tasks <= 0:
                    max_tasks = None
            except ValueError:
                max_tasks = None

    runs = None
    if runs is None and PROMPT_FOR_RUNS:
        raw_runs = input("請輸入要重複執行幾次：").strip()
        if not raw_runs:
            print("錯誤：請輸入重複執行次數（正整數）")
            sys.exit(1)
        try:
            runs = int(raw_runs)
        except ValueError:
            print("錯誤：重複執行次數必須是整數")
            sys.exit(1)
    if runs is None:
        if PROMPT_FOR_RUNS:
            print("錯誤：請在互動模式下輸入重複執行次數（正整數）")
            sys.exit(1)
        runs = 1
    runs = int(runs)
    if runs <= 0:
        print("錯誤：runs 必須為正整數")
        sys.exit(1)
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

    for label, mn in (
        ("interviewer", interviewer_model),
        ("gym (judge/user)", gym_model),
    ):
        if not model_has_token_pricing(mn):
            print(
                f"警告：沒有找到 token 的定價：{label} 模型「{mn}」。"
                "請在專案 utils/cost.py 的 CostTracker.DEFAULT_PRICING_PER_1M_TOKENS 補上該模型，"
                "或改用已定價的模型名稱。"
            )
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
    llm = interviewer_model  # interviewer 使用的模型
    run_results: List[dict] = []
    run_metrics: List[dict] = []
    run_costs_usd: List[float] = []
    run_total_tokens: List[int] = []
    run_total_runtime_s: List[float] = []
    round_ids_used: List[str] = []

    for run_idx in range(runs):
        run_id = str(next_result_index(RESULTS_FILE_PREFIX, RESULTS_DIR))
        round_ids_used.append(run_id)

        evaluation_result_path = str(RESULTS_DIR / f"result_{RESULTS_FILE_PREFIX}_{run_id}.json")
        conversation_result_path = str(RESULTS_DIR / f"record_{RESULTS_FILE_PREFIX}_{run_id}.json")
        cost_result_path = str(RESULTS_DIR / f"cost_{RESULTS_FILE_PREFIX}_{run_id}.json")

        print(f"\n=== Run {run_idx + 1}/{runs}（run_id={run_id}）===")

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

        print("\n正在建立環境...")
        try:
            env = ReqElicitGym(config)
        except Exception as e:
            print(f"錯誤：建立環境失敗：{e}")
            import traceback

            traceback.print_exc()
            sys.exit(1)

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

        def tracked_ask_question(conversation_history, return_usage=False):
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

        def tracked_model_call(
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

        interviewer.ask_question = tracked_ask_question
        baseline_prompts.model_call = tracked_model_call
        baseline_interviewer_module.model_call = tracked_model_call
        baseline_prompts.model_call_with_thinking = _orig_prompt_model_call_with_thinking
        baseline_interviewer_module.model_call_with_thinking = _orig_interviewer_model_call_with_thinking
        print(f"Interviewer 已建立：{interviewer}")

        print("\n" + "=" * 60)
        print("開始執行全量評估實驗...")
        print("=" * 60)
        results = env.run_all_tasks(interviewer)
        interviewer.ask_question = _orig_ask_question
        baseline_prompts.model_call = _orig_prompt_model_call
        baseline_prompts.model_call_with_thinking = _orig_prompt_model_call_with_thinking
        baseline_interviewer_module.model_call = _orig_interviewer_model_call
        baseline_interviewer_module.model_call_with_thinking = _orig_interviewer_model_call_with_thinking

        try:
            env.save_evaluation_results(file_path=None, interviewer_model_name=interviewer.model_name)
            print(f"\n評估結果已儲存至：{config.evaluation_result_path}")
        except Exception as e:
            print(f"儲存評估結果時發生錯誤：{e}")
            import traceback
            traceback.print_exc()

        try:
            env.save_conversation_results(file_path=None)
            print(f"對話過程已儲存至：{config.conversation_result_path}")
        except Exception as e:
            print(f"儲存對話過程時發生錯誤：{e}")
            import traceback
            traceback.print_exc()

        run_total_cost_usd = 0.0
        run_total_token = 0
        run_total_runtime = 0.0
        run_cost_ok = False
        try:
            interviewer_summary = interviewer_cost_tracker.export_summary_dict()
            user_summary = user_cost_tracker.export_summary_dict()
            cost_payload = {
                "interviewer": interviewer_summary,
                "user": user_summary,
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
            }
            run_total_cost_usd = float(cost_payload.get("estimated_cost(USD)", 0.0) or 0.0)
            run_total_token = int(cost_payload.get("total_tokens", 0) or 0)
            run_total_runtime = float(cost_payload.get("run_time(s)", 0.0) or 0.0)
            with open(cost_result_path, "w", encoding="utf-8") as f:
                json_dump_no_scientific(cost_payload, f, indent=2, ensure_ascii=False)
            run_cost_ok = True
            print(f"成本摘要已儲存至：{cost_result_path}")
        except Exception as e:
            print(f"儲存成本摘要時發生錯誤：{e}")
            import traceback
            traceback.print_exc()

        run_results.append(results)
        run_metrics.append(results.get("overall_metrics", {}) or {})
        if run_cost_ok:
            run_costs_usd.append(run_total_cost_usd)
            run_total_tokens.append(run_total_token)
            run_total_runtime_s.append(run_total_runtime)

    results = run_results[-1] if run_results else {}
    print("\n" + "=" * 60)
    print("所有任務完成！")
    print("=" * 60)
    conversation_results = results.get("conversation_results", [])
    if conversation_results:
        print(f"總任務數：{len(conversation_results)}")
        avg_turns = sum(r.get("total_turns", 0) for r in conversation_results) / len(conversation_results)
        print(f"平均對話輪數：{avg_turns:.1f}")

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

    if runs > 1:
        metric_keys = [
            ("elicitation_ratio", "IRE", "平均取得比例", "percent"),
            ("tkqr", "TKQR", "平均 TKQR", "float4"),
            ("ora", "ORA", "平均 ORA", "float4"),
        ]
        print("\n多次執行結果統計（平均值 ± 標準差）：")
        summary_metrics = {}
        if run_metrics:
            for src_key, out_key, label, fmt in metric_keys:
                vals = []
                for m in run_metrics:
                    v = m.get(src_key, None)
                    if isinstance(v, (int, float)):
                        vals.append(float(v))
                if not vals:
                    continue
                mu = mean(vals)
                sd = float(np.std(vals))
                summary_metrics[out_key] = {
                    "mean": mu,
                    "std": sd,
                    "per_round_values": vals,
                }
                if fmt == "percent":
                    print(f"  {label}：{mu:.2%} ± {sd:.2%}")
                else:
                    print(f"  {label}：{mu:.4f} ± {sd:.4f}")

        summary_cost = None
        if run_costs_usd:
            cost_mu = float(np.mean(run_costs_usd))
            cost_sd = float(np.std(run_costs_usd))
            token_mu = float(np.mean(run_total_tokens))
            token_sd = float(np.std(run_total_tokens))
            rt_mu = float(np.mean(run_total_runtime_s))
            rt_sd = float(np.std(run_total_runtime_s))
            print(f"  平均 token：{token_mu:.1f} ± {token_sd:.1f}")
            print(f"  平均成本(USD)：{cost_mu:.8f} ± {cost_sd:.8f}")
            print(f"  平均執行時間(s)：{rt_mu:.3f} ± {rt_sd:.3f}")
            summary_cost = {
                "average_token": {
                    "mean": token_mu,
                    "std": token_sd,
                    "per_round_values": [int(x) for x in run_total_tokens],
                },
                "average_cost(USD)": {
                    "mean": cost_mu,
                    "std": cost_sd,
                    "per_round_values": [float(x) for x in run_costs_usd],
                },
                "average_run_time(s)": {
                    "mean": rt_mu,
                    "std": rt_sd,
                    "per_round_values": [float(x) for x in run_total_runtime_s],
                },
            }
        else:
            print("  平均成本(USD)：N/A（本次執行未成功產生成本檔）")

        # 固定欄位順序：runs -> metrics -> cost
        summary_payload = {"runs": runs}
        if summary_metrics:
            summary_payload["metrics"] = summary_metrics
        if summary_cost is not None:
            summary_payload["cost"] = summary_cost

        summary_path = RESULTS_DIR / f"summary_{RESULTS_FILE_PREFIX}.json"
        with summary_path.open("w", encoding="utf-8") as f:
            json_dump_no_scientific(summary_payload, f, indent=2, ensure_ascii=False)
        print(f"已儲存至：{summary_path}")

    return results

if __name__ == "__main__":
    main()
