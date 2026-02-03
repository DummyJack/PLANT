import logging
from datetime import datetime
from typing import Dict, Any, List
from pathlib import Path

# 系統日誌管理
class Logger:    
    def __init__(self, log_dir: str = "log"):
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        
        # 每次執行產生新的 log 檔案
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
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
    
    def add_conflict_resolution(self, conflict_id: str, decision: str, rationale: str):
        """記錄衝突解決"""
        if not self.mom_data["rounds"]:
            raise ValueError("請先呼叫 start_round() 開始一輪")
        
        current_round = self.mom_data["rounds"][-1]
        if "conflict_resolutions" not in current_round:
            current_round["conflict_resolutions"] = []
        
        current_round["conflict_resolutions"].append({
            "conflict_id": conflict_id,
            "decision": decision,
            "rationale": rationale,
            "timestamp": datetime.now().isoformat()
        })
    
    def get_mom_data(self) -> Dict[str, Any]:
        """取得完整的 MoM 資料"""
        return self.mom_data

# 收集使用者的選擇和決策
class Collect: 
    @staticmethod
    # 收集使用者選擇的利害關係人
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
                print(f"{i}. {sh['name']}")
                print(f"   理由: {sh['reason']}")
            
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
    # 收集使用者對衝突需求的決策
    def user_decision(decision_option: Dict) -> Dict:
        """        
        Args:
            decision_option: 決策選項
        
        Returns:
            Dict: 包含 conflict_id, decision, rationale
        """
        print(f"\n衝突：{decision_option['conflict_title']}")
        print(f"\n選項：")
        print("0. 自行輸入解決方法")
        for i, opt in enumerate(decision_option['options'], 1):
            print(f"{i}. {opt}")
        
        print(f"\n建議：{decision_option['recommendation']}")
        
        user_input = input("\n請選擇方案(輸入編號或 skip)：").strip()
        
        if user_input.lower() == 'skip':
            return {
                "conflict_id": decision_option['conflict_id'],
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
                        "conflict_id": decision_option['conflict_id'],
                        "decision": "跳過決策",
                        "rationale": "未輸入解決方法"
                    }
                
                return {
                    "conflict_id": decision_option['conflict_id'],
                    "decision": "手動方案",
                    "rationale": custom_solution
                }
            
            # 預設方案
            elif 1 <= choice_idx <= len(decision_option['options']):
                chosen = decision_option['options'][choice_idx - 1]
                
                return {
                    "conflict_id": decision_option['conflict_id'],
                    "decision": chosen,
                    "rationale": decision_option['recommendation']
                }
            else:
                print("無效的選項，預設跳過")
                return {
                    "conflict_id": decision_option['conflict_id'],
                    "decision": "跳過決策",
                    "rationale": "無效輸入"
                }
        except ValueError:
            print("無效的輸入，預設跳過")
            return {
                "conflict_id": decision_option['conflict_id'],
                "decision": "跳過決策",
                "rationale": "無效輸入"
            }