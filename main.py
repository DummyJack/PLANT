import os
import sys
import traceback
from pathlib import Path
from dotenv import load_dotenv
from flow import Flow
from store import Store
from utils import Logger, AgentSelector, ProjectManager

# 主程式
def main():
    print("=" * 60)
    print("Plant 系統")
    print("=" * 60)
    print()
    
    # 初始化基礎目錄
    base_dir = Path(__file__).parent
    
    # 載入環境變數
    env_path = base_dir / "config" / ".env"
    load_dotenv(dotenv_path=env_path)
    
    # 初始化基礎 Store（用於專案管理）
    base_store = Store(base_dir)
    
    # 載入配置
    try:
        config = base_store.load_config()
        print(f"✓ 載入配置：provider={config.get('provider')}, model={config.get('model')}")
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
    
    # 選擇或創建專案
    project_id, is_continue = ProjectManager.select_or_create_project(base_store)
    
    # 取得使用者輸入
    if not is_continue:
        # 新專案
        rough_idea = input("\n請輸入您的初始想法(可以是一個模糊的系統概念、問題描述或需求)：").strip()
        
        if not rough_idea:
            print("錯誤：請提供初始想法")
            sys.exit(1)
        
        # 創建專案
        project_id = base_store.create_project()
        print(f"\n✓ 已創建專案：{project_id}\n")
        
        # 選擇要使用的代理
        print()
        AgentSelector.select_agents(config)
        
        # 設置回合數
        print()
        rounds = AgentSelector.set_rounds()
        config["rounds"] = rounds
        config["start_round"] = 1
        
    else:
        # 繼續現有專案
        # 使用專案特定的 Store 載入資料
        project_store = Store(base_dir, project_id)
        
        # 顯示專案資訊
        ProjectManager.display_project_info(project_store, project_id)
        
        # 載入現有 artifact
        artifact = project_store.load_artifact()
        if artifact:
            rough_idea = artifact.get("rough_idea", "")
            print(f"專案的初始想法：{rough_idea}\n")
        else:
            print("⚠️  警告：無法載入專案的 artifact，將作為新專案處理\n")
            rough_idea = input("請輸入您的初始想法：").strip()
            if not rough_idea:
                print("錯誤：請提供初始想法")
                sys.exit(1)
        
        # 選擇額外討論的代理
        agent_choices = AgentSelector.select_agents(config)
        
        # 設置額外回合數
        print()
        extra_rounds = AgentSelector.set_rounds()
        
        # 計算已完成的輪數（從 mom.json）
        completed_rounds = 0
        mom_data = project_store.load_mom()
        if mom_data and "rounds" in mom_data:
            completed_rounds = len(mom_data["rounds"])
        
        # 設置總輪數（已完成 + 額外）
        config["rounds"] = completed_rounds + extra_rounds
        config["start_round"] = completed_rounds + 1
    
    # 儲存配置
    base_store.save_config(config)
    
    # 使用專案特定的 Store 和 Logger
    store = Store(base_dir, project_id)
    logger = Logger(store.log_dir)
    
    logger.info(f"專案 ID: {project_id}")
    logger.info(f"載入配置：provider={config.get('provider')}, model={config.get('model')}")
    
    print()
    print("開始執行...")
    print()
    
    # 建立並執行流程
    try:
        flow = Flow(config, store, logger)
        
        if is_continue:
            # 繼續現有專案
            flow.run_continue(rough_idea, artifact)
        else:
            # 新專案
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