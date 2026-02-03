import os
import sys
import traceback
from pathlib import Path
from dotenv import load_dotenv
from flow import Flow
from store import Store
from utils import Logger, AgentSelector

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
    AgentSelector.select_agents(config)
    
    # 設置回合數
    rounds = AgentSelector.set_rounds()
    config["rounds"] = rounds
    
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