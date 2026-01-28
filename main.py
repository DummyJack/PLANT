import os
import sys
import traceback
from pathlib import Path
from dotenv import load_dotenv
from flow import Flow
from store import Store
from utils import Logger

# 主程式
def main():
    print("=" * 60)
    print("Plant 系統")
    print("=" * 60)
    print()
    
    # 初始化
    base_dir = Path(__file__).parent
    store = Store(base_dir)
    logger = Logger(base_dir / "log")
    
    # 載入環境變數
    env_path = base_dir / "config" / ".env"
    load_dotenv(dotenv_path=env_path)
    
    # 載入配置
    try:
        config = store.load_config()
        logger.info(f"載入配置：provider={config.get('provider')}, model={config.get('model')}")
    except FileNotFoundError:
        print("錯誤：找不到 config/config.json 檔案")
        sys.exit(1)
    
    # 檢查 API Key
    provider = config.get("provider", "anthropic")
    api_key_env = {
        "openai": "OPENAI_API_KEY",
        "anthropic": "ANTHROPIC_API_KEY",
        "gemini": "GEMINI_API_KEY",
        "ollama": None  # Ollama 不需要 API Key
    }
    
    if provider != "ollama":
        required_key = api_key_env.get(provider)
        if not os.getenv(required_key):
            print(f"錯誤：找不到 {required_key} 環境變數")
            print(f"請在 config/.env 檔案中設定 {required_key}=your_api_key")
            sys.exit(1)
    
    # 選擇要使用的代理
    print()
    print("請選擇要使用的代理：")
    print("0. 全部使用")
    print("1. User Agent（利害關係人需求表達）")
    print("2. Analyst Agent（需求分析）")
    print("3. Expert Agent（專家建議）")
    print("4. Mediator Agent（雜事處理）")
    print("5. Modeler Agent（系統建模）")
    print("6. Documentor Agent（文件產生）")
    print()
    
    agent_input = input("請輸入編號(可多選，用逗號分隔，例如：1,2,3)：").strip()
    
    if agent_input == "0":
        config["enable_user"] = True
        config["enable_analyst"] = True
        config["enable_expert"] = True
        config["enable_mediator"] = True
        config["enable_modeler"] = True
        config["enable_documentor"] = True
        print("✓ 已選擇全部代理")
    else:
        # 先全部設為 False
        config["enable_user"] = False
        config["enable_analyst"] = False
        config["enable_expert"] = False
        config["enable_mediator"] = False
        config["enable_modeler"] = False
        config["enable_documentor"] = False
        
        # 根據輸入啟用
        try:
            choices = [int(x.strip()) for x in agent_input.split(',')]
            agent_map = {
                1: ("enable_user", "User Agent"),
                2: ("enable_analyst", "Analyst Agent"),
                3: ("enable_expert", "Expert Agent"),
                4: ("enable_mediator", "Mediator Agent"),
                5: ("enable_modeler", "Modeler Agent"),
                6: ("enable_documentor", "Documentor Agent")
            }
            
            selected_agents = []
            for choice in choices:
                if choice in agent_map:
                    key, name = agent_map[choice]
                    config[key] = True
                    selected_agents.append(name)
            
            if selected_agents:
                print(f"✓ 已選擇：{', '.join(selected_agents)}")
            else:
                print("錯誤：未選擇任何有效的代理")
                sys.exit(1)
        except ValueError:
            print("錯誤：輸入格式不正確")
            sys.exit(1)
    
    # 設置回合數
    print()
    while True:
        rounds_input = input("請輸入討論回合數：").strip()
        if not rounds_input:
            print("❌ 錯誤：請輸入回合數")
            continue
        try:
            rounds = int(rounds_input)
            if rounds < 1:
                print("❌ 錯誤：回合數必須大於 0，請重新輸入")
                continue
            config["rounds"] = rounds
            print(f"✓ 設定回合數：{rounds}")
            break
        except ValueError:
            print("❌ 錯誤：回合數必須是數字，請重新輸入")
            continue
    
    # 儲存配置
    store.save_config(config)
    print()
    
    # 取得使用者輸入
    rough_idea = input("請輸入您的初始想法(可以是一個模糊的系統概念、問題描述或需求)：").strip()
    
    if not rough_idea:
        print("錯誤：請提供初始想法")
        sys.exit(1)
    
    print()
    print("初始想法已接收，開始執行...")
    print()
    
    # 建立並執行流程
    try:
        flow = Flow(config, store, logger)
        flow.run(rough_idea)
        
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