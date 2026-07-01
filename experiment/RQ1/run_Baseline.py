import os
import json
import sys
from time import perf_counter
from pathlib import Path

from typing import Any, Dict, List

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
EXPERIMENT_ROOT = Path(__file__).resolve().parent
if str(EXPERIMENT_ROOT) not in sys.path:
    sys.path.insert(0, str(EXPERIMENT_ROOT))

from utils.clean import apply_entrypoint_bootstrap

apply_entrypoint_bootstrap()


RQ1_DIR = Path(__file__).resolve().parent
BASE_DIR = RQ1_DIR.parent.parent

env_path = BASE_DIR / ".env"
load_dotenv(env_path)

DEFAULT_CONFIG_PATH = RQ1_DIR / "Baseline" / "config.json"

RESULTS_DIR = RQ1_DIR / "results"
RESULTS_FILE_PREFIX = "Baseline"

DEFAULT_DATA_FILE = "ReqElicitBench.json"

GEMINI_OPENAI_COMPAT_BASE = "https://generativelanguage.googleapis.com/v1beta/openai/"

DEFAULT_BASE_URL = "https://api.openai.com/v1"

from Baseline.config import ReqElicitGymConfig
from Baseline.env import ReqElicitGym
import Baseline.env.prompts as baseline_prompts
import Baseline.interviewer as baseline_interviewer_module
from Baseline.interviewer import Interviewer
from utils import CostTracker, json_dump_no_scientific, model_has_token_pricing


def resolve_data_path(raw: str) -> str:
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


def model_file_prefix(provider: str) -> str:
    normalized = str(provider or "").strip().lower()
    if normalized == "openai":
        return "gpt"
    if normalized in {"gemini", "claude"}:
        return normalized
    return normalized or "model"


def cost_summary_diff(before: Dict[str, Any], after: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "model": str(after.get("model") or before.get("model") or ""),
        "input_tokens": max(0, int(after.get("input_tokens", 0) or 0) - int(before.get("input_tokens", 0) or 0)),
        "output_tokens": max(0, int(after.get("output_tokens", 0) or 0) - int(before.get("output_tokens", 0) or 0)),
        "total_tokens": max(0, int(after.get("total_tokens", 0) or 0) - int(before.get("total_tokens", 0) or 0)),
        "run_time(s)": round(
            max(
                0.0,
                float(after.get("run_time(s)", 0.0) or 0.0)
                - float(before.get("run_time(s)", 0.0) or 0.0),
            ),
            3,
        ),
        "estimated_cost(USD)": round(
            max(
                0.0,
                float(after.get("estimated_cost(USD)", 0.0) or 0.0)
                - float(before.get("estimated_cost(USD)", 0.0) or 0.0),
            ),
            8,
        ),
    }


def cost_totals(rows: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    return {
        "input_tokens": sum(int(v.get("input_tokens", 0) or 0) for v in rows.values()),
        "output_tokens": sum(int(v.get("output_tokens", 0) or 0) for v in rows.values()),
        "total_tokens": sum(int(v.get("total_tokens", 0) or 0) for v in rows.values()),
        "run_time(s)": round(sum(float(v.get("run_time(s)", 0.0) or 0.0) for v in rows.values()), 3),
        "estimated_cost(USD)": round(
            sum(float(v.get("estimated_cost(USD)", 0.0) or 0.0) for v in rows.values()),
            8,
        ),
    }


def model_provider(model_name: str) -> str:
    normalized = str(model_name or "").strip().lower()
    if normalized.startswith("gemini-"):
        return "gemini"
    return "openai"


def endpoint_for_model(model_name: str) -> tuple[str, str]:
    provider = model_provider(model_name)
    if provider == "gemini":
        return (
            os.environ.get("GEMINI_API_KEY", ""),
            os.environ.get("GEMINI_BASE_URL") or GEMINI_OPENAI_COMPAT_BASE,
        )
    return (
        os.environ.get("OPENAI_API_KEY", ""),
        os.environ.get("OPENAI_BASE_URL") or DEFAULT_BASE_URL,
    )


def choose_application_types(tasks: List[dict]) -> List[str] | None:
    counts: dict[str, int] = {}
    for task in tasks:
        app_type = str(task.get("name") or "Unknown").strip() or "Unknown"
        counts[app_type] = counts.get(app_type, 0) + len(task.get("Implicit Requirements", []) or [])
    if not counts:
        print("錯誤：資料集中沒有可執行的情境")
        sys.exit(1)

    scenarios = list(counts.keys())
    print("可選情境：")
    for idx, scenario in enumerate(scenarios, start=1):
        print(f"  {idx}. {scenario}（{counts[scenario]} 個隱性需求）")

    raw = input("請選擇要執行的情境（Enter: 全部，可輸入 1,3,5）：").strip()
    if not raw:
        return None
    tokens = [token.strip() for token in raw.split(",") if token.strip()]
    if not tokens or any(not token.isdigit() for token in tokens):
        print("錯誤：請輸入情境編號；多個情境請使用 1,3,5 格式")
        sys.exit(1)

    selected: List[str] = []
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


def main():
    cfg_path = DEFAULT_CONFIG_PATH.resolve()
    file_cfg = load_baseline_file_config(cfg_path)

    def pick(key: str, default):
        v = file_cfg.get(key, default)
        return default if v is None else v

    interviewer_model = pick("interviewer_model", "gpt-4o-mini")
    gym_model = pick("gym_model", "gpt-5.2")
    api_key, base_url = endpoint_for_model(interviewer_model)
    gym_api_key, gym_base_url = endpoint_for_model(gym_model)
    data_path = resolve_data_path(DEFAULT_DATA_FILE)

    try:
        print(f"正在載入資料檔案：{data_path}")
        with open(data_path, "r", encoding="utf-8") as f:
            all_tasks = json.load(f)
        if not isinstance(all_tasks, list):
            raise TypeError("資料檔案必須是 list")
    except Exception as e:
        print(f"錯誤：無法載入資料檔案：{e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)

    total_tasks_in_file = len(all_tasks)
    selected_application_types = choose_application_types(all_tasks)
    if selected_application_types:
        selected_set = set(selected_application_types)
        all_tasks = [
            task for task in all_tasks
            if (str(task.get("name") or "Unknown").strip() or "Unknown") in selected_set
        ]
        if not all_tasks:
            print("錯誤：選擇的情境沒有可執行任務")
            sys.exit(1)

    print(
        f"資料檔案共 {total_tasks_in_file} 個任務，"
        f"本輪執行 {len(all_tasks)} 個任務"
    )

    if len(all_tasks) != total_tasks_in_file:
        subset_path = RQ1_DIR / ".reqelicit_subset.json"
        with open(subset_path, "w", encoding="utf-8") as f:
            json.dump(all_tasks, f, ensure_ascii=False, indent=2)
        data_path = str(subset_path)

    runs = 1
    verbose = bool(pick("verbose", True))

    judge_temperature = float(pick("judge_temperature", 0.0))
    judge_max_tokens = int(pick("judge_max_tokens", 1024))
    judge_timeout = float(pick("judge_timeout", 30.0))
    user_temperature = float(pick("user_temperature", 0.7))
    user_max_tokens = int(pick("user_max_tokens", 1024))
    user_timeout = float(pick("user_timeout", 30.0))
    user_answer_quality = str(pick("user_answer_quality", "high"))
    max_turns = int(pick("max_turns", 20))
    interviewer_temperature = float(pick("interviewer_temperature", 0.0))
    interviewer_timeout = float(pick("interviewer_timeout", 60.0))
    interviewer_max_tokens = int(pick("interviewer_max_tokens", 1024))


    judge_api_key = os.getenv("JUDGE_API_KEY", gym_api_key)
    user_api_key = os.getenv("USER_API_KEY", gym_api_key)
    judge_base_url = os.getenv("JUDGE_BASE_URL", gym_base_url)
    user_base_url = os.getenv("USER_BASE_URL", gym_base_url)

    if not api_key:
        provider = model_provider(interviewer_model)
        required_key = "GEMINI_API_KEY" if provider == "gemini" else "OPENAI_API_KEY"
        print(f"錯誤：interviewer_model={interviewer_model} 需要在 .env 設定 {required_key}")
        sys.exit(1)
    if not judge_api_key or not user_api_key:
        provider = model_provider(gym_model)
        required_key = "GEMINI_API_KEY" if provider == "gemini" else "OPENAI_API_KEY"
        print(f"錯誤：gym_model={gym_model} 需要在 .env 設定 {required_key}")
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


    if not os.path.exists(data_path):
        print(f"錯誤：找不到檔案 {data_path}")
        print("請確保資料檔案存在")
        sys.exit(1)


    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    llm = interviewer_model
    file_prefix = model_file_prefix(model_provider(interviewer_model))
    run_results: List[dict] = []

    for run_idx in range(runs):
        evaluation_result_path = str(RESULTS_DIR / f"{file_prefix}_result_{RESULTS_FILE_PREFIX}.json")
        conversation_result_path = str(RESULTS_DIR / f"{file_prefix}_record_{RESULTS_FILE_PREFIX}.json")
        cost_result_path = str(RESULTS_DIR / f"{file_prefix}_cost_{RESULTS_FILE_PREFIX}.json")

        print(f"\n=== Run {run_idx + 1}/{runs} ===")

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
            max_turns=max_turns,
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

        interviewer = Interviewer(
            api_key=api_key,
            base_url=base_url,
            model_name=llm,
            temperature=interviewer_temperature,
            max_tokens=interviewer_max_tokens,
            timeout=interviewer_timeout,
        )
        interviewer_cost_tracker = CostTracker(model_name=interviewer.model_name)
        user_cost_tracker = CostTracker(model_name=gym_model)
        task_cost_rows: List[Dict[str, Any]] = []
        task_cost_start: Dict[str, Dict[str, Any]] = {}
        orig_ask_question = interviewer.ask_question
        orig_prompt_model_call = baseline_prompts.model_call
        orig_interviewer_model_call = baseline_interviewer_module.model_call

        def tracked_ask_question(conversation_history, return_usage=False):
            start = perf_counter()
            out = orig_ask_question(conversation_history, return_usage=return_usage)
            elapsed = perf_counter() - start
            if return_usage:
                question, usage_info = out
                interviewer_cost_tracker.add_usage(
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
            response, usage_info = orig_prompt_model_call(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                model_config=model_config,
                return_json=return_json,
                return_usage=True,
            )
            elapsed = perf_counter() - start
            if system_prompt == baseline_prompts.PASSIVE_RESPONSE_SYSTEM:
                user_cost_tracker.add_usage(
                    usage_info or {},
                    metadata={"action": "baseline.user.generate_response"},
                    run_time_s=elapsed,
                )
            if return_usage:
                return response, usage_info
            return response

        def current_cost_snapshot() -> Dict[str, Dict[str, Any]]:
            return {
                "interviewer": interviewer_cost_tracker.export_summary_dict(),
                "user": user_cost_tracker.export_summary_dict(),
            }

        def task_cost_callback(event: str, task_id: str, task_data: Dict[str, Any]) -> None:
            nonlocal task_cost_start
            if event == "start":
                task_cost_start = current_cost_snapshot()
                return
            if event != "end":
                return
            after = current_cost_snapshot()
            agent_costs = {
                name: cost_summary_diff(task_cost_start.get(name, {}), summary)
                for name, summary in after.items()
            }
            task_cost_rows.append(
                {
                    "task_id": task_id,
                    "task_name": task_data.get("name", ""),
                    "totals": cost_totals(agent_costs),
                }
            )

        interviewer.ask_question = tracked_ask_question
        baseline_prompts.model_call = tracked_model_call
        baseline_interviewer_module.model_call = tracked_model_call
        config.task_cost_callback = task_cost_callback
        print(f"Interviewer 已建立：{interviewer}")

        print("\n" + "=" * 60)
        print("開始執行全量評估實驗...")
        print("=" * 60)
        results = env.run_all_tasks(interviewer)
        interviewer.ask_question = orig_ask_question
        baseline_prompts.model_call = orig_prompt_model_call
        baseline_interviewer_module.model_call = orig_interviewer_model_call

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

        try:
            interviewer_summary = interviewer_cost_tracker.export_summary_dict()
            user_summary = user_cost_tracker.export_summary_dict()
            agents = {
                "interviewer": interviewer_summary,
                "user": user_summary,
            }
            cost_payload = {
                "interviewer": interviewer_summary,
                "user": user_summary,
                "totals": {
                    "input_tokens": sum(
                        int(v.get("input_tokens", 0) or 0) for v in agents.values()
                    ),
                    "output_tokens": sum(
                        int(v.get("output_tokens", 0) or 0) for v in agents.values()
                    ),
                    "total_tokens": sum(
                        int(v.get("total_tokens", 0) or 0) for v in agents.values()
                    ),
                    "run_time(s)": round(
                        sum(float(v.get("run_time(s)", 0.0) or 0.0) for v in agents.values()),
                        3,
                    ),
                    "estimated_cost(USD)": round(
                        sum(
                            float(v.get("estimated_cost(USD)", 0.0) or 0.0)
                            for v in agents.values()
                        ),
                        8,
                    ),
                },
                "tasks": task_cost_rows,
            }
            with open(cost_result_path, "w", encoding="utf-8") as f:
                json_dump_no_scientific(cost_payload, f, indent=2, ensure_ascii=False)
            print(f"成本摘要已儲存至：{cost_result_path}")
        except Exception as e:
            print(f"儲存成本摘要時發生錯誤：{e}")
            import traceback
            traceback.print_exc()

        run_results.append(results)

    results = run_results[-1] if run_results else {}
    print("\n" + "=" * 60)
    print("所有任務完成！")
    print("=" * 60)
    conversation_results = results.get("conversation_results", [])
    if conversation_results:
        print(f"總任務數：{len(conversation_results)}")
        avg_turns = sum(r.get("turns", 0) for r in conversation_results) / len(conversation_results)
        print(f"平均 Turns：{avg_turns:.1f}")

    overall_metrics = results.get("overall_metrics", {})
    if overall_metrics:
        print("\n評估指標總結：")
        print(f"  總測試樣本數：{overall_metrics.get('total_tasks', 0)}")
        print(f"  總隱式需求數：{overall_metrics.get('total_requirements_all_tasks', 0)}")
        print("\n平均指標（基於測試樣本平均）：")
        print(f"  平均取得比例：{overall_metrics.get('elicitation_ratio', 0.0):.2%}")
        print(f"  平均 TKQR：{overall_metrics.get('tkqr', 0.0):.4f}")
        print(f"  平均 Turns：{overall_metrics.get('average_turn', 0.0):.2f}")
        print("\n標準差：")
        print(f"  取得比例標準差：{overall_metrics.get('std_elicitation_ratio', 0.0):.4f}")
        print(f"  TKQR 標準差：{overall_metrics.get('std_tkqr', 0.0):.4f}")
        print(f"  Turns 標準差：{overall_metrics.get('std_turn', 0.0):.2f}")

        app_type_stats = overall_metrics.get("application_type_statistics", {})
        if app_type_stats:
            print("\n依應用類型統計：")
            print(f"{'Application Type':<40} {'任務數':<10} {'平均取得比例':<15} {'平均TKQR':<12}")
            print("-" * 85)
            for app_type in sorted(app_type_stats.keys()):
                stats = app_type_stats[app_type]
                print(
                    f"{app_type:<40} {stats['num_tasks']:<10} "
                    f"{stats['average_elicitation_ratio']:>13.2%} "
                    f"{stats['average_tkqr']:>10.4f}"
                )

    return results

if __name__ == "__main__":
    main()
