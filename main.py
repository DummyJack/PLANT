# CLI entrypoint: selects project mode, collects input, and starts the flow.
import sys
import traceback

from pathlib import Path
from dotenv import load_dotenv
from flow.setup import Flow
from model import validate_provider_api_keys
from storage import Store
from utils import (
    Logger,
    ProjectManager,
    format_loaded_models_summary,
    stage_enabled,
)
from utils.language import sync_output_language


def formal_meeting_enabled(config):
    return (
        stage_enabled(config, "default_formal_meeting", True)
        or stage_enabled(config, "general_formal_meeting", True)
    )


def general_formal_meeting_enabled(config):
    return stage_enabled(config, "general_formal_meeting", True)


def main():
    print("=" * 60)
    print("PLANT 系統")
    print("=" * 60)
    print()

    base_dir = Path(__file__).parent

    env_path = base_dir / ".env"
    load_dotenv(dotenv_path=env_path)

    base_store = Store(base_dir)

    try:
        config = base_store.load_config()
        print(format_loaded_models_summary(config))
    except FileNotFoundError:
        print("錯誤：找不到 config.json 檔案（請放在專案主目錄）")
        sys.exit(1)

    try:
        validate_provider_api_keys(config)
        session = ProjectManager.prepare_project_session(base_dir, base_store)
    except ValueError as e:
        print(f"錯誤：{str(e)}")
        sys.exit(1)

    # 只有一般正式會議啟用時才需要由人類設定討論回合數；預設正式會議固定跑 1 輪。
    if general_formal_meeting_enabled(config):
        while True:
            rounds_input = input("請輸入討論回合數：").strip()
            if not rounds_input:
                print("❌ 請輸入回合數")
                continue
            try:
                rounds = int(rounds_input)
                if rounds < 1:
                    print("❌ 回合數必須大於 0")
                    continue
                print()
                print(f"✓ 設定回合數：{rounds}")
                break
            except ValueError:
                print("❌ 回合數必須是數字")

        config["rounds"] = rounds
        base_store.save_config(config)
    elif formal_meeting_enabled(config):
        config["rounds"] = 1
        base_store.save_config(config)
    else:
        config["rounds"] = 0

    store = Store(base_dir, session.project_id)
    logger = Logger(store.log_dir)

    print("開始執行...")
    print()

    try:
        if not session.is_continue:
            sync_output_language(session.rough_idea)
        flow = Flow(config, store, logger)

        if session.is_continue:
            flow.run_continue(session.artifact)
        else:
            flow.run(session.rough_idea)

    except KeyboardInterrupt:
        print("\n\n使用者中斷執行")
        sys.exit(0)
    except Exception as e:
        logger.error(f"執行錯誤：{str(e)}")
        print(f"\n錯誤：{str(e)}")
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
