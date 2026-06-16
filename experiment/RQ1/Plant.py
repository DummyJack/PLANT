# Runs the RQ1 Plant experiment workflow and writes evaluation outputs.
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
EXPERIMENT_ROOT = Path(__file__).resolve().parent
if str(EXPERIMENT_ROOT) not in sys.path:
    sys.path.insert(0, str(EXPERIMENT_ROOT))

from dotenv import load_dotenv
import numpy as np

from utils.clean import apply_entrypoint_bootstrap

apply_entrypoint_bootstrap()

RQ1_DIR = Path(__file__).resolve().parent
BASE_DIR = RQ1_DIR.parent.parent

OUTPUT_PREFIX = "Plant"
RESULTS_DIR = RQ1_DIR / "results"
DEFAULT_CONFIG_PATH = RQ1_DIR / "Plant" / "config.json"
FLOW_CONFIG_PATH = (RQ1_DIR / "../../config.json").resolve()
DEFAULT_DATA_PATH = (RQ1_DIR / "ReqElicitBench.json").resolve()
ask_max_tasks = True
ask_runs = True

load_dotenv(BASE_DIR / ".env")

def main() -> None:
    from Plant.config import (
        apply_rq1_flow_overrides,
        assert_models_have_pricing,
        build_flow,
        build_oracle_configs,
        load_json,
    )
    from Plant.oracle_user import OracleUserAgent
    from Plant.records import (
        build_cost_payload,
        build_plant_models,
        build_result_payload,
        build_task_record,
        print_final_summary,
        resolve_plant_model_label,
    )
    from Plant.utils import (
        next_result_index,
        run_one_task,
        task_implicit_requirements,
        task_initial_requirements,
    )
    from utils import json_dump_no_scientific

    cfg_path = DEFAULT_CONFIG_PATH.resolve()
    exp_cfg = load_json(cfg_path)

    flow_cfg_path = FLOW_CONFIG_PATH
    flow_cfg = apply_rq1_flow_overrides(load_json(flow_cfg_path), exp_cfg)

    data_path = DEFAULT_DATA_PATH
    print(f"正在載入資料檔案：{data_path}")
    with data_path.open("r", encoding="utf-8") as f:
        tasks = json.load(f)
    if not isinstance(tasks, list):
        raise TypeError(f"資料檔格式錯誤，必須是 list: {data_path}")

    max_tasks = None
    if max_tasks is None:
        if ask_max_tasks:
            raw = input("請輸入要執行的任務數量（Enter: 全做）：").strip()
            if raw:
                try:
                    max_tasks = int(raw)
                except ValueError:
                    max_tasks = None

    if max_tasks is not None and max_tasks > 0:
        tasks = tasks[:max_tasks]

    runs = None
    if runs is None and ask_runs:
        raw_runs = input("請輸入要重複執行幾次：").strip()
        if not raw_runs:
            print("錯誤：請輸入重複執行次數")
            sys.exit(1)
        try:
            runs = int(raw_runs)
        except ValueError:
            print("錯誤：重複執行次數必須是整數")
            sys.exit(1)
    if runs is None:
        if ask_runs:
            print("錯誤：請在互動模式下輸入重複執行次數（正整數）")
            sys.exit(1)
        runs = 1
    if runs <= 0:
        print("錯誤：runs 必須為正整數")
        sys.exit(1)
    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        print("錯誤：請先在 .env 或環境變數設定 OPENAI_API_KEY")
        sys.exit(1)
    base_url = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")

    assert_models_have_pricing(flow_cfg, exp_cfg)

    verbose = bool(exp_cfg.get("verbose", True))
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    run_results: List[Dict[str, Any]] = []
    run_metrics: List[Dict[str, Any]] = []
    run_costs_usd: List[float] = []
    run_total_tokens: List[int] = []
    run_total_runtime_s: List[float] = []
    round_ids_used: List[str] = []

    for run_i in range(runs):
        run_id = str(next_result_index(OUTPUT_PREFIX, RESULTS_DIR))
        round_ids_used.append(run_id)

        print(f"\n=== Run {run_i + 1}/{runs}（run_id={run_id}）===")
        print("\n正在建立環境...")
        flow = build_flow(flow_cfg, verbose=verbose, results_dir=RESULTS_DIR)
        oracle_cfg = build_oracle_configs(exp_cfg, api_key, base_url)
        oracle_user = OracleUserAgent(
            model=flow.agent_models["user"],
            oracle_configs=oracle_cfg,
            registry=flow.registry,
            project_config=flow.config,
        )
        flow.user_agent = oracle_user
        flow.registry.register("user", oracle_user)
        oracle_user.rq1_logger = flow.logger
        print("\n" + "=" * 60)
        print("開始執行全量評估實驗...")
        print("=" * 60)

        records: List[Dict[str, Any]] = []
        task_result_rows: List[Dict[str, Any]] = []
        t0 = time.perf_counter()
        for i, task in enumerate(tasks, start=1):
            print()
            print(f"任務 {i}/{len(tasks)}：task_{i-1}")
            print(f"系統名稱：{task.get('name', 'N/A')}")
            print(f"應用類型：{task.get('application_type', 'N/A')}")
            print(f"初始需求：{task_initial_requirements(task)[:100]}...")
            print(f"總需求數：{len(task_implicit_requirements(task))}")
            print("\n開始需求擷取會議...\n")
            token_before = 0
            for m in flow.agent_models.values():
                if hasattr(m, "costTracker"):
                    token_before += int(m.costTracker.export_summary_dict().get("total_tokens", 0) or 0)
            one = run_one_task(flow, oracle_user, task)
            token_after = 0
            for m in flow.agent_models.values():
                if hasattr(m, "costTracker"):
                    token_after += int(m.costTracker.export_summary_dict().get("total_tokens", 0) or 0)
            task_token_cost = max(0, token_after - token_before)
            records.append(one)
            task_record = build_task_record(
                task_idx=i - 1,
                task=task,
                per_task=one,
                plant_model_label=resolve_plant_model_label(flow_cfg, one),
                user_answer_quality=str(exp_cfg.get("user_answer_quality", "high")),
                token_cost=task_token_cost,
            )
            task_result_rows.append(task_record)
            print(
                f"\n任務 {i} 完成：總輪數={int(task_record.get('turns', 0) or 0)}，"
                f"已取得需求數={int(task_record.get('total_elicited', 0) or 0)}"
            )

        _ = round(time.perf_counter() - t0, 3)
        print(f"\n已執行所有 {len(tasks)} 個任務，停止。")
        result = build_result_payload(
            flow_cfg=flow_cfg,
            exp_cfg=exp_cfg,
            task_results=task_result_rows,
        )

        prefix = OUTPUT_PREFIX
        result_path = RESULTS_DIR / f"result_{prefix}_{run_id}.json"
        record_path = RESULTS_DIR / f"record_{prefix}_{run_id}.json"
        cost_path = RESULTS_DIR / f"cost_{prefix}_{run_id}.json"

        with result_path.open("w", encoding="utf-8") as f:
            json_dump_no_scientific(result, f, indent=2, ensure_ascii=False)
        with record_path.open("w", encoding="utf-8") as f:

            json_dump_no_scientific(
                [
                    {
                        "task_id": t["task_id"],
                        "task_name": t["task_name"],
                        "initial_requirements": t["initial_requirements"],
                        "user_answer_quality": t["user_answer_quality"],
                        "Plant": build_plant_models(flow_cfg),
                        "conversation": t["conversation"],
                    }
                    for t in task_result_rows
                ],
                f,
                indent=2,
                ensure_ascii=False,
            )
        cost_payload = build_cost_payload(flow, oracle_user)
        with cost_path.open("w", encoding="utf-8") as f:
            json_dump_no_scientific(cost_payload, f, indent=2, ensure_ascii=False)

        print_final_summary(result, task_result_rows)

        run_results.append(result)
        run_metrics.append(result.get("overall_evaluation", {}) or {})
        totals = cost_payload.get("totals", {}) if isinstance(cost_payload, dict) else {}
        run_costs_usd.append(float(totals.get("estimated_cost(USD)", 0.0) or 0.0))
        run_total_tokens.append(int(totals.get("total_tokens", 0) or 0))
        run_total_runtime_s.append(float(totals.get("run_time(s)", 0.0) or 0.0))

    if runs > 1:
        metric_keys = [
            ("average_elicitation_ratio", "IRE", "平均取得比例", "percent"),
            ("average_tkqr", "TKQR", "平均 TKQR", "float4"),
            ("average_ora", "ORA", "平均 ORA", "float4"),
            ("average_turn", "Turns", "Turns", "float4"),
        ]
        print("\n多次執行結果統計（平均值 ± 標準差）：")
        summary_metrics: Dict[str, Any] = {}
        for src_key, out_key, label, fmt in metric_keys:
            vals = []
            for m in run_metrics:
                v = m.get(src_key, None)
                if isinstance(v, (int, float)):
                    vals.append(float(v))
            if not vals:
                continue
            mu = float(np.mean(vals))
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

        summary_cost: Optional[Dict[str, Any]] = None
        if run_costs_usd:
            cost_mu = float(np.mean(run_costs_usd))
            token_mu = float(np.mean(run_total_tokens))
            rt_mu = float(np.mean(run_total_runtime_s))
            print(f"  平均 token：{token_mu:.1f}")
            print(f"  平均成本(USD)：{cost_mu:.8f}")
            print(f"  平均執行時間(s)：{rt_mu:.3f}")
            summary_cost = {
                "average_token": token_mu,
                "average_cost(USD)": cost_mu,
                "average_run_time(s)": rt_mu,
            }
        else:
            print("  平均成本(USD)：N/A（本次執行未成功產生成本檔）")

        summary_payload = {"runs": runs}
        if summary_metrics:
            summary_payload["metrics"] = summary_metrics
        if summary_cost is not None:
            summary_payload["cost"] = summary_cost

        summary_path = RESULTS_DIR / f"summary_{OUTPUT_PREFIX}.json"
        with summary_path.open("w", encoding="utf-8") as f:
            json_dump_no_scientific(summary_payload, f, indent=2, ensure_ascii=False)
        print(f"已儲存至：{summary_path}")

if __name__ == "__main__":
    main()
