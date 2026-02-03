import logging

from datetime import datetime
from typing import Dict, Any, List, Tuple
from pathlib import Path
from store import Store

# 系統日誌管理
class Logger:    
    def __init__(self, log_dir: str = "log"):
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        
        # 每次執行產生新的 log 檔案
        timestamp = datetime.now().strftime("%H%M%S")
        log_file = self.log_dir / f"system_{timestamp}.log"
        
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler(log_file, encoding='utf-8'),
                logging.StreamHandler()
            ]
        )
        self.logger = logging.getLogger("Plant")
    
    def info(self, message: str):
        """記錄資訊"""
        self.logger.info(message)
    
    def warning(self, message: str):
        """記錄警告"""
        self.logger.warning(message)
    
    def error(self, message: str):
        """記錄錯誤"""
        self.logger.error(message)
    
    def debug(self, message: str):
        """記錄除錯訊息"""
        self.logger.debug(message)

# 會議記錄(MoM)管理
class MoMManager:
    def __init__(self):
        self.current_round = 0
        self.mom_data = {"rounds": []}
    
    def start_round(self, round_number: int):
        """開始新的一輪"""
        self.current_round = round_number
        self.mom_data["rounds"].append({
            "round": round_number,
            "timestamp": datetime.now().isoformat(),
            "stages": []
        })
    
    def add_stage(self, stage_name: str, agent: str, description: str = "", outputs: Any = None):
        """
        記錄階段資訊
        
        Args:
            stage_name: 階段名稱
            agent: 執行的 Agent 名稱
            description: 簡短描述
            outputs: Agent 的輸出數據（可選）
        """
        if not self.mom_data["rounds"]:
            raise ValueError("請先呼叫 start_round() 開始一輪")
        
        stage_data = {
            "stage": stage_name,
            "agent": agent,
            "description": description,
            "timestamp": datetime.now().isoformat()
        }
        
        # 只在有輸出時記錄
        if outputs is not None:
            stage_data["outputs"] = outputs
        
        current_round = self.mom_data["rounds"][-1]
        current_round["stages"].append(stage_data)
    
    def add_conflict_resolution(self, conflict_title: str, decision: str, rationale: str):
        """記錄衝突解決"""
        if not self.mom_data["rounds"]:
            raise ValueError("請先呼叫 start_round() 開始一輪")
        
        current_round = self.mom_data["rounds"][-1]
        if "conflict_resolutions" not in current_round:
            current_round["conflict_resolutions"] = []
        
        current_round["conflict_resolutions"].append({
            "conflict_title": conflict_title,
            "decision": decision,
            "rationale": rationale,
            "timestamp": datetime.now().isoformat()
        })
    
    def get_mom_data(self) -> Dict[str, Any]:
        """取得完整的 MoM 資料"""
        return self.mom_data

# 人類的選擇和決策
class Collect: 
    @staticmethod
    # 人類選擇的利害關係人
    def user_selection(proposed: List[Dict[str, str]]) -> List[int]:
        """
        Args:
            proposed: 建議的利害關係人列表 (包含 name 和 reason)
        
        Returns:
            List[int]: 選擇的索引列表
        """
        while True:
            print("\n建議選擇的利害關係人：")
            for i, sh in enumerate(proposed, 1):
                print(f"{i}. {sh['name']}，理由: {sh['reason']}")
            
            print("\n提示: 可以輸入編號或直接輸入新的利害關係人名稱(例如: 1,3,系統管理員)")
            user_input = input("\n請選擇利害關係人(最多選擇 5 位)：").strip()
            
            if not user_input:
                print("\n❌ 錯誤：請至少選擇或輸入 1 個利害關係人")
                continue
            
            try:
                selected_indices = []
                parts = [x.strip() for x in user_input.split(',')]
                
                for part in parts:
                    try:
                        idx = int(part) - 1
                        if 0 <= idx < len(proposed):
                            selected_indices.append(idx)
                        else:
                            print(f"\n⚠️  警告：編號 {part} 無效，已忽略")
                    except ValueError:
                        # 不是數字，當作自訂利害關係人
                        if part:  # 確保不是空字串
                            # 新增自訂利害關係人到 proposed
                            proposed.append({"name": part, "reason": "使用者自訂"})
                            selected_indices.append(len(proposed) - 1)
                
                # 驗證數量
                if len(selected_indices) > 5:
                    print(f"\n⚠️  錯誤：選擇超過 5 個（已選 {len(selected_indices)} 個），請重新選擇")
                    continue
                
                if len(selected_indices) == 0:
                    print(f"\n❌ 錯誤：至少需要選擇 1 個利害關係人")
                    continue
                
                # 顯示選擇結果
                print(f"\n✓ 已選擇的利害關係人：")
                for i, idx in enumerate(selected_indices, 1):
                    print(f"  {i}. {proposed[idx]['name']}")
                
                return selected_indices
                
            except Exception as e:
                print(f"\n❌ 錯誤：{str(e)}")
                continue
    
    @staticmethod
    # 人類對衝突需求的決策
    def user_decision(decision_option: Dict) -> Dict:
        print(f"衝突標題: {decision_option.get('title', 'N/A')}")
        print(f"\n決策選項(0. 自行輸入解決方法)：")
        
        # 顯示選項及其理由
        rationales = decision_option.get('rationales', [])
        for i, opt in enumerate(decision_option['options'], 1):
            print(f"\n{i}. {opt}")
            if rationales and i-1 < len(rationales) and rationales[i-1]:
                print(f"理由：{rationales[i-1]}")
        
        print(f"\n💡 推薦：{decision_option.get('recommendation', '無')}")
        
        user_input = input("\n請選擇方案(輸入編號或 skip)：").strip()
        
        if user_input.lower() == 'skip':
            return {
                "conflict_title": decision_option['title'],
                "decision": "跳過決策",
                "rationale": "人類選擇暫不處理此衝突"
            }
        
        try:
            choice_idx = int(user_input)
            
            # 自行輸入解決方法
            if choice_idx == 0:
                custom_solution = input("\n請輸入您的解決方法：").strip()
                
                if not custom_solution:
                    print("未輸入解決方法，預設跳過")
                    return {
                        "conflict_title": decision_option['title'],
                        "decision": "跳過決策",
                        "rationale": "未輸入解決方法"
                    }
                
                return {
                    "conflict_title": decision_option['title'],
                    "decision": "手動方案",
                    "rationale": custom_solution
                }
            
            # 預設方案
            elif 1 <= choice_idx <= len(decision_option['options']):
                chosen = decision_option['options'][choice_idx - 1]
                chosen_rationale = rationales[choice_idx - 1] if rationales and choice_idx-1 < len(rationales) else decision_option.get('recommendation', '')
                
                return {
                    "conflict_title": decision_option['title'],
                    "decision": chosen,
                    "rationale": chosen_rationale
                }
            else:
                print("無效的選項，預設跳過")
                return {
                    "conflict_title": decision_option['title'],
                    "decision": "跳過決策",
                    "rationale": "無效輸入"
                }
        except ValueError:
            print("無效的輸入，預設跳過")
            return {
                "conflict_title": decision_option['title'],
                "decision": "跳過決策",
                "rationale": "無效輸入"
            }
    # 人類的額外想法
    def additional_idea(self, round_num: int) -> str:
        print(f"\n{'='*60}")
        print(f"Round {round_num} - 額外想法輸入")
        print("="*60)
        print("您是否有新的想法(例如：新功能、新的利害關係人、調整需求優先級等)，若無，請直接按 Enter 跳過")
        print()
        
        additional_idea = input("請輸入額外想法：").strip()
        
        if additional_idea:
            print(f"\n✓ 已接收額外想法")
            return additional_idea
        else:
            print("\n跳過額外想法輸入")
            return ""

# Agent 選擇和回合數設置
class AgentSelector:
    AGENT_MAP = {
        1: ("enable_user", "User（模擬利害關係人提出需求）"),
        2: ("enable_analyst", "Analyst（需求衝突分析）"),
        3: ("enable_expert", "Expert（專家建議）"),
        4: ("enable_mediator", "Mediator（調解）"),
        5: ("enable_modeler", "Modeler（系統建模）"),
        6: ("enable_documentor", "Documentor（文件產生）")
    }
    
    # 選擇要使用的代理並更新配置
    @staticmethod
    def select_agents(config: Dict[str, Any], agent: str = "\n請輸入要使用的 Agent (例如：1,3,5 或 0)：") -> List[int]:
        # 顯示代理選擇菜單
        print("Agent：")
        for idx, (_, name) in AgentSelector.AGENT_MAP.items():
            print(f"{idx}. {name}")
        print("0. 全部使用")
        
        while True:
            try:
                agent_input = input(agent).strip()
                
                # 處理輸入
                if agent_input == "0":
                    agent_choices = [1, 2, 3, 4, 5, 6]
                else:
                    agent_choices = [
                        int(x.strip()) for x in agent_input.split(",") if x.strip()
                    ]
                
                # 驗證輸入
                if not agent_choices:
                    print("錯誤：請至少選擇一個 Agent")
                    continue
                
                if not all(1 <= x <= 6 for x in agent_choices):
                    print("錯誤：請輸入有效的 Agent（0-6）")
                    continue
                
                # 更新配置：先禁用所有 Agent
                for idx in range(1, 7):
                    key = AgentSelector.AGENT_MAP[idx][0]
                    config[key] = False
                
                # 啟用選擇的 Agent
                selected_names = []
                for choice in agent_choices:
                    key, name = AgentSelector.AGENT_MAP[choice]
                    config[key] = True
                    selected_names.append(name)
                
                print(f"✓ 已選擇：{', '.join(selected_names)}")
                return agent_choices
                
            except ValueError:
                print("錯誤：輸入格式不正確，請輸入數字（用逗號分隔）")
    
    @staticmethod
    def set_rounds(
        round: str = "\n請輸入討論回合數：",
        allow_empty: bool = False,
    ) -> int:        
        while True:
            rounds_input = input(round).strip()
            
            # 處理空輸入
            if not rounds_input:
                if allow_empty:
                    return 0
                else:
                    print("❌ 錯誤：請輸入回合數")
                    continue
            
            # 驗證數字
            try:
                rounds = int(rounds_input)
                if rounds < 1:
                    print("❌ 錯誤：回合數必須大於 0，請重新輸入")
                    continue
                print(f"✓ 設定回合數：{rounds}")
                return rounds
            except ValueError:
                print("❌ 錯誤：回合數必須是數字，請重新輸入")

# 處理專案選擇和創建
class ProjectManager:
    @staticmethod
    # 選擇現有專案或創建新專案
    def select_or_create_project(store) -> Tuple[str, bool]:        
        # 列出所有專案
        temp_store = Store(store.base_dir)
        projects = temp_store.list_projects()
        
        if not projects:
            print("\n目前沒有任何專案，將創建新專案")
            return None, False
        
        print("\n" + "="*60)
        print("現有專案列表")
        print()
        
        for i, project in enumerate(projects, 1):
            created_at = project.get("created_at", "未知")
            if "T" in created_at:
                # 格式化日期時間
                try:
                    dt = datetime.fromisoformat(created_at)
                    created_at = dt.strftime("%Y-%m-%d %H:%M:%S")
                except:
                    pass
            
            rough_idea = project.get("rough_idea", "未知")
            
            print(f"{i}. 專案 ID: {project['project_id']}")
            print(f"   創建時間: {created_at}")
            print(f"   初始想法: {rough_idea}")
            print()
        
        print("="*60)
        print("0. 創建新專案")
        print()
        
        # 讓使用者選擇
        while True:
            try:
                choice = input("請選擇專案編號 (或輸入 0 創建新專案)：").strip()
                
                if not choice:
                    print("❌ 錯誤：請輸入專案編號")
                    continue
                
                choice_num = int(choice)
                
                if choice_num == 0:
                    # 創建新專案
                    return None, False
                elif 1 <= choice_num <= len(projects):
                    # 選擇現有專案
                    selected_project = projects[choice_num - 1]
                    project_id = selected_project["project_id"]
                    
                    print(f"\n✓ 已選擇專案：{project_id}")
                    print("將繼續此專案的討論 (視為額外討論輪數)\n")
                    
                    return project_id, True
                else:
                    print(f"❌ 錯誤：請輸入有效的專案編號 (0-{len(projects)})")
                    
            except ValueError:
                print("❌ 錯誤：請輸入數字")
    
    @staticmethod
    # 顯示專案資訊
    def display_project_info(store, project_id: str):
        # 從 artifact 載入資訊
        artifact = store.load_artifact()
        
        # 從 mom.json 計算完成的輪數
        completed_rounds = 0
        mom_data = store.load_mom()
        if mom_data and "rounds" in mom_data:
            completed_rounds = len(mom_data["rounds"])
        
        # 獲取創建時間
        created_at = "未知"
        if store.project_dir.exists():
            created_at = datetime.fromtimestamp(store.project_dir.stat().st_ctime).strftime("%Y-%m-%d %H:%M:%S")
        
        print("\n" + "="*60)
        print(f"專案資訊：{project_id}")
        print("="*60)
        print(f"創建時間: {created_at}")
        if artifact:
            print(f"初始想法: {artifact.get('rough_idea', '未知')}")
        print(f"已完成輪數: {completed_rounds}")
        print("="*60)
        print()