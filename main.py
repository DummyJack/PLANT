import os
import sys
import traceback

from pathlib import Path
from dotenv import load_dotenv
from flow import Flow
from store import Store
from utils import Logger, ProjectManager

def main():
    print("=" * 60)
    print("Plant 系統")
    print("=" * 60)
    print()

    base_dir = Path(__file__).parent

    env_path = base_dir / "config" / ".env"
    load_dotenv(dotenv_path=env_path)

    base_store = Store(base_dir)

    try:
        config = base_store.load_config()
        am = config.get("agent_models") or {}
        default_cfg = am.get("default") or next(iter(am.values()), {})
        if isinstance(default_cfg, dict):
            print(f"✓ 載入配置：provider={default_cfg.get('provider')}, model={default_cfg.get('model')}")
        else:
            print("✓ 載入配置")
    except FileNotFoundError:
        print("錯誤：找不到 config/config.json 檔案")
        sys.exit(1)

    agent_models = config.get("agent_models") or {}
    providers_to_check = set()
    for agent_cfg in agent_models.values():
        if isinstance(agent_cfg, dict) and agent_cfg.get("provider"):
            providers_to_check.add(agent_cfg["provider"])
    if not providers_to_check and config.get("provider"):
        providers_to_check.add(config.get("provider"))

    api_key_env = {
        "openai": "OPENAI_API_KEY",
        "ollama": None
    }

    for used_provider in providers_to_check:
        if used_provider == "ollama":
            continue
        required_key = api_key_env.get(used_provider)
        if not required_key:
            print(f"錯誤：不支援的 provider: {used_provider}")
            sys.exit(1)
        if not os.getenv(required_key):
            print(f"錯誤：找不到 {required_key} 環境變數（provider={used_provider}）")
            print(f"請在 config/.env 檔案中設定 {required_key}=your_api_key")
            sys.exit(1)

    project_id, is_continue = ProjectManager.select_or_create_project(base_store)

    artifact = None
    if not is_continue:
        rough_idea = input("\n請輸入您的初始想法(可以是一個模糊的系統概念、問題描述或需求)：").strip()

        if not rough_idea:
            print("錯誤：請提供初始想法")
            sys.exit(1)

        project_id = base_store.create_project()
        print(f"\n✓ 已創建專案：{project_id}\n")
    else:
        project_store = Store(base_dir, project_id)
        ProjectManager.display_project_info(project_store, project_id)

        artifact = project_store.load_artifact()
        if artifact:
            rough_idea = artifact.get("rough_idea", "")
            print(f"專案的初始想法：{rough_idea}\n")
        else:
            print("⚠️  警告：無法載入專案的 artifact，將作為新專案處理\n")
            is_continue = False
            rough_idea = input("請輸入您的初始想法：").strip()
            if not rough_idea:
                print("錯誤：請提供初始想法")
                sys.exit(1)
            project_id = base_store.create_project()

    # 由人類設定討論回合數，寫入 config
    rounds = input_rounds("請輸入討論回合數：")
    config["rounds"] = rounds
    base_store.save_config(config)

    store = Store(base_dir, project_id)
    logger = Logger(store.log_dir)

    print()
    print("開始執行...")
    print()

    try:
        flow = Flow(config, store, logger)

        if is_continue:
            flow.run_continue(artifact)
        else:
            flow.run(rough_idea)

    except KeyboardInterrupt:
        print("\n\n使用者中斷執行")
        sys.exit(0)
    except Exception as e:
        logger.error(f"執行錯誤：{str(e)}")
        print(f"\n錯誤：{str(e)}")
        traceback.print_exc()
        sys.exit(1)


def input_rounds(prompt: str) -> int:
    while True:
        rounds_input = input(prompt).strip()
        if not rounds_input:
            print("❌ 請輸入回合數")
            continue
        try:
            rounds = int(rounds_input)
            if rounds < 1:
                print("❌ 回合數必須大於 0")
                continue
            print(f"✓ 設定回合數：{rounds}")
            return rounds
        except ValueError:
            print("❌ 回合數必須是數字")


if __name__ == "__main__":
    main()
