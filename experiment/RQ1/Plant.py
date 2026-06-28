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

from utils import json_dump_no_scientific
from utils.clean import apply_entrypoint_bootstrap

apply_entrypoint_bootstrap()

RQ1_DIR = Path(__file__).resolve().parent
BASE_DIR = RQ1_DIR.parent.parent

OUTPUT_PREFIX = "Plant"
RESULTS_DIR = RQ1_DIR / "results"
DEFAULT_CONFIG_PATH = RQ1_DIR / "Plant" / "config.json"
FLOW_CONFIG_PATH = (RQ1_DIR / "../../config.json").resolve()
DEFAULT_DATA_PATH = (RQ1_DIR / "ReqElicitBench.json").resolve()

load_dotenv(BASE_DIR / ".env")

def model_file_prefix(provider: str) -> str:
    normalized = str(provider or "").strip().lower()
    if normalized == "openai":
        return "gpt"
    if normalized in {"gemini", "claude"}:
        return normalized
    return normalized or "model"


def plant_model_file_prefix(flow_cfg: Dict[str, Any]) -> str:
    agent_models = flow_cfg.get("agent_models") if isinstance(flow_cfg.get("agent_models"), dict) else {}
    default_cfg = agent_models.get("default") if isinstance(agent_models.get("default"), dict) else {}
    provider = str(default_cfg.get("provider") or "").strip()
    if not provider:
        for row in agent_models.values():
            if isinstance(row, dict) and str(row.get("provider") or "").strip():
                provider = str(row.get("provider") or "").strip()
                break
    return model_file_prefix(provider)


def load_checkpoint_file(path: Path) -> Dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        with path.open("r", encoding="utf-8") as f:
            payload = json.load(f)
    except Exception as e:
        raise RuntimeError(f"checkpoint 檔案無法讀取，請修復或刪除後再續跑：{path}") from e
    if not isinstance(payload, dict):
        raise RuntimeError(f"checkpoint 檔案格式錯誤，最外層必須是 object：{path}")
    return payload


def write_json_atomic(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f".{path.name}.tmp")
    with tmp_path.open("w", encoding="utf-8") as f:
        json_dump_no_scientific(payload, f, indent=2, ensure_ascii=False)
    tmp_path.replace(path)


def merge_cost_payloads(previous: Dict[str, Any], current: Dict[str, Any]) -> Dict[str, Any]:
    if not previous:
        return current
    if not current:
        return previous
    merged_agents: Dict[str, Any] = {}
    previous_agents = previous.get("agents") or {}
    current_agents = current.get("agents") or {}
    for agent in sorted(set(previous_agents.keys()) | set(current_agents.keys())):
        prev = previous_agents.get(agent) or {}
        cur = current_agents.get(agent) or {}
        merged_agents[agent] = {
            "model": cur.get("model") or prev.get("model") or "",
            "input_tokens": int(prev.get("input_tokens", 0) or 0) + int(cur.get("input_tokens", 0) or 0),
            "output_tokens": int(prev.get("output_tokens", 0) or 0) + int(cur.get("output_tokens", 0) or 0),
            "total_tokens": int(prev.get("total_tokens", 0) or 0) + int(cur.get("total_tokens", 0) or 0),
            "run_time(s)": round(float(prev.get("run_time(s)", 0.0) or 0.0) + float(cur.get("run_time(s)", 0.0) or 0.0), 3),
            "estimated_cost(USD)": round(float(prev.get("estimated_cost(USD)", 0.0) or 0.0) + float(cur.get("estimated_cost(USD)", 0.0) or 0.0), 8),
        }
    totals = {
        "input_tokens": sum(int(v.get("input_tokens", 0) or 0) for v in merged_agents.values()),
        "output_tokens": sum(int(v.get("output_tokens", 0) or 0) for v in merged_agents.values()),
        "total_tokens": sum(int(v.get("total_tokens", 0) or 0) for v in merged_agents.values()),
        "run_time(s)": round(sum(float(v.get("run_time(s)", 0.0) or 0.0) for v in merged_agents.values()), 3),
        "estimated_cost(USD)": round(sum(float(v.get("estimated_cost(USD)", 0.0) or 0.0) for v in merged_agents.values()), 8),
    }
    return {"agents": merged_agents, "totals": totals}


def choose_application_types(tasks: List[Dict[str, Any]]) -> List[str] | None:
    counts: Dict[str, int] = {}
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


def task_index_from_id(task_id: str) -> Optional[int]:
    raw = str(task_id or "").strip()
    if not raw.startswith("task_"):
        return None
    try:
        return int(raw.split("_", 1)[1])
    except (IndexError, ValueError):
        return None


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
        run_one_task,
        task_implicit_requirements,
        task_initial_requirements,
    )

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

    total_tasks_in_file = len(tasks)
    selected_application_types = choose_application_types(tasks)
    if selected_application_types:
        selected_set = set(selected_application_types)
        tasks = [
            task for task in tasks
            if (str(task.get("name") or "Unknown").strip() or "Unknown") in selected_set
        ]
        if not tasks:
            print("錯誤：選擇的情境沒有可執行任務")
            sys.exit(1)

    print(f"資料檔案共 {total_tasks_in_file} 個任務，本輪執行 {len(tasks)} 個任務")

    file_prefix = plant_model_file_prefix(flow_cfg)

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    runs = 1
    assert_models_have_pricing(flow_cfg, exp_cfg)

    verbose = bool(exp_cfg.get("verbose", True))

    for run_i in range(runs):
        prefix = OUTPUT_PREFIX
        result_path = RESULTS_DIR / f"{file_prefix}_result_{prefix}.json"
        record_path = RESULTS_DIR / f"{file_prefix}_record_{prefix}.json"
        cost_path = RESULTS_DIR / f"{file_prefix}_cost_{prefix}.json"
        checkpoint_path = RESULTS_DIR / f"{file_prefix}_checkpoint_{prefix}.json"

        print(f"\n=== Run {run_i + 1}/{runs} ===")
        print("\n正在建立環境...")
        flow = build_flow(flow_cfg, verbose=verbose, results_dir=RESULTS_DIR)
        try:
            oracle_cfg = build_oracle_configs(exp_cfg)
        except Exception as e:
            print(f"錯誤：建立 oracle 設定失敗：{e}")
            sys.exit(1)
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

        checkpoint_payload: Dict[str, Any] = {}
        task_result_rows: List[Dict[str, Any]] = [
            row
            for row in (checkpoint_payload.get("task_result_rows", []) if isinstance(checkpoint_payload, dict) else [])
            if isinstance(row, dict)
        ]
        completed_task_ids = {str(row.get("task_id") or "") for row in task_result_rows}
        completed_indexes = [
            idx
            for idx in (task_index_from_id(task_id) for task_id in completed_task_ids)
            if idx is not None
        ]
        if completed_indexes and max(completed_indexes) >= len(tasks):
            print(
                "錯誤：checkpoint 已完成的 task 超出本次選擇的任務數量。"
                "續跑時請選擇與原 run 相同的情境。"
            )
            sys.exit(1)
        selected_task_count = (
            int(checkpoint_payload.get("selected_task_count", 0) or 0)
            if isinstance(checkpoint_payload, dict)
            else 0
        )
        if selected_task_count and selected_task_count != len(tasks):
            print(
                f"錯誤：checkpoint 原本任務數量為 {selected_task_count}，"
                f"本次選擇為 {len(tasks)}。續跑時請使用相同情境。"
            )
            sys.exit(1)
        previous_cost_payload = (
            checkpoint_payload.get("cost_payload", {})
            if isinstance(checkpoint_payload, dict)
            else {}
        )
        def persist_progress() -> Dict[str, Any]:
            result_payload = build_result_payload(
                flow_cfg=flow_cfg,
                exp_cfg=exp_cfg,
                task_results=task_result_rows,
            )
            with result_path.open("w", encoding="utf-8") as f:
                json_dump_no_scientific(result_payload, f, indent=2, ensure_ascii=False)
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
            cost_payload = merge_cost_payloads(
                previous_cost_payload,
                build_cost_payload(flow, oracle_user),
            )
            with cost_path.open("w", encoding="utf-8") as f:
                json_dump_no_scientific(cost_payload, f, indent=2, ensure_ascii=False)
            write_json_atomic(
                checkpoint_path,
                {
                    "selected_task_count": len(tasks),
                    "completed_task_count": len(task_result_rows),
                    "task_result_rows": task_result_rows,
                    "cost_payload": cost_payload,
                },
            )
            return cost_payload

        records: List[Dict[str, Any]] = []
        t0 = time.perf_counter()
        for i, task in enumerate(tasks, start=1):
            task_id = f"task_{i - 1}"
            if task_id in completed_task_ids:
                print(f"\n任務 {i}/{len(tasks)}：{task_id} 已完成，略過")
                continue
            print()
            print(f"任務 {i}/{len(tasks)}：{task_id}")
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
            completed_task_ids.add(task_id)
            cost_payload = persist_progress()
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

        persist_progress()

        print_final_summary(result, task_result_rows)

if __name__ == "__main__":
    main()
