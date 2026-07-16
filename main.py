import sys
from pathlib import Path

for stream_name in ("stdin", "stdout", "stderr"):
    stream = getattr(sys, stream_name, None)
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")

from utils.preflight import preflight_enabled, prepare_python_environment


BASE_DIR = Path(__file__).resolve().parent
prepare_python_environment(
    BASE_DIR,
    enabled=preflight_enabled(BASE_DIR, "server"),
)

# CLI entrypoint: selects project mode, collects input, and starts the flow.
import uuid

import traceback

from dotenv import load_dotenv
from flow.setup import Flow
from model import validate_provider_api_keys
from storage import Store
from storage.coordinator import FileRunCoordinator
from server.services.run_checkpoint import clear_run_checkpoint
from utils import (
    Logger,
    ProjectManager,
    format_loaded_models_summary,
    formal_meeting_enabled,
    general_formal_meeting_enabled,
)
from utils.language import sync_output_language
from utils.stage_validation import validate_stage_plan


def main():
    base_dir = BASE_DIR

    env_path = base_dir / ".env"
    load_dotenv(dotenv_path=env_path)

    print("=" * 60)
    print("PLANT 系統")
    print("=" * 60)
    print()

    base_store = Store(base_dir)
    try:
        config = base_store.load_config()
    except (OSError, ValueError) as exc:
        print(f"錯誤：無法讀取 config.json：{exc}")
        sys.exit(1)
    print(format_loaded_models_summary(config))

    try:
        validate_provider_api_keys(config)
        session = ProjectManager.prepare_project_session(base_dir, base_store)
    except ValueError as e:
        print(f"錯誤：{str(e)}")
        sys.exit(1)

    # 只有一般正式會議啟用時才需要由人類設定討論回合數；輸入值會覆蓋 config rounds。
    if general_formal_meeting_enabled(config):
        while True:
            rounds_input = input(
                "請輸入一般正式會議回合數（0 表示不執行一般正式會議）："
            ).strip()
            if not rounds_input:
                print("❌ 請輸入回合數")
                continue
            try:
                rounds = int(rounds_input)
                if rounds < 0:
                    print("❌ 回合數不可小於 0")
                    continue
                print()
                print(f"✓ 設定回合數：{rounds}")
                break
            except ValueError:
                print("❌ 回合數必須是數字")

        config["rounds"] = rounds
    elif formal_meeting_enabled(config):
        config["rounds"] = 1
    else:
        config["rounds"] = 0

    store = Store(base_dir, session.project_id)
    try:
        validate_stage_plan(
            config,
            session.artifact or {},
            store,
            mode="continue" if session.is_continue else "new",
        )
    except ValueError as exc:
        print(f"錯誤：{exc}")
        sys.exit(1)
    write_file_log = bool((config.get("export") or {}).get("log", False))
    logger = Logger(store.log_dir, write_file=write_file_log)
    coordinator = FileRunCoordinator(base_dir)
    run_id = f"cli_{uuid.uuid4().hex[:10]}"
    if not coordinator.claim_project(session.project_id, run_id):
        logger.close()
        print("錯誤：此專案已有執行中的流程")
        sys.exit(1)

    print("開始執行...")
    print()

    try:
        if not session.is_continue:
            sync_output_language(session.rough_idea)
        flow = Flow(config, store, logger)
        flow.run_id = run_id
        flow.run_mode = "continue" if session.is_continue else "new"

        if session.is_continue:
            flow.run_continue(session.artifact)
        else:
            flow.run(session.rough_idea)
        clear_run_checkpoint(store)

    except KeyboardInterrupt:
        print("\n\n使用者中斷執行")
        sys.exit(0)
    except Exception as e:
        logger.error(f"執行錯誤：{str(e)}")
        print(f"\n錯誤：{str(e)}")
        traceback.print_exc()
        sys.exit(1)
    finally:
        coordinator.release_project(session.project_id, run_id)
        logger.close()


if __name__ == "__main__":
    main()
