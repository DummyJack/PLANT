import logging
from datetime import datetime
from typing import Dict, Any
from pathlib import Path

# 系統日誌管理
class Logger:    
    def __init__(self, log_dir: str = "log"):
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        
        # 每次執行產生新的 log 檔案（使用時間戳）
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
    
    def generate_markdown(self) -> str:
        """生成 Markdown 格式的會議記錄"""
        md = "# Minutes of Meeting (MoM)\n\n"
        md += f"**產生時間**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
        md += "---\n\n"
        
        for round_data in self.mom_data["rounds"]:
            md += f"## Round {round_data['round']}\n\n"
            md += f"**開始時間**: {round_data['timestamp']}\n\n"
            
            # 階段記錄
            md += "### 執行階段\n\n"
            for i, stage in enumerate(round_data.get("stages", []), 1):
                md += f"#### {i}. {stage['stage']} ({stage['agent']})\n\n"
                md += f"- **時間**: {stage['timestamp']}\n"
                
                # 描述
                if stage.get('description'):
                    md += f"- **說明**: {stage['description']}\n"
                
                # 輸出數據
                if stage.get('outputs'):
                    md += "- **輸出**: "
                    outputs = stage['outputs']
                    if isinstance(outputs, dict):
                        md += "\n"
                        for key, value in outputs.items():
                            if isinstance(value, list):
                                md += f"  - {key}: {len(value)} 項\n"
                            elif isinstance(value, str) and len(value) > 100:
                                md += f"  - {key}: {value[:100]}...\n"
                            else:
                                md += f"  - {key}: {value}\n"
                    else:
                        md += f"{outputs}\n"
                
                md += "\n"
            
            # 衝突解決記錄
            if "conflict_resolutions" in round_data:
                md += "### 衝突解決\n\n"
                for resolution in round_data["conflict_resolutions"]:
                    md += f"#### {resolution['conflict_id']}\n"
                    md += f"- **決策**: {resolution['decision']}\n"
                    md += f"- **理由**: {resolution['rationale']}\n"
                    md += f"- **時間**: {resolution['timestamp']}\n\n"
            
            md += "---\n\n"
        
        return md