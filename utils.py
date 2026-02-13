import logging

from datetime import datetime
from typing import Dict, Any, List, Tuple
from pathlib import Path
from store import Store


class Logger:
    def __init__(self, log_dir: str = "log"):
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)

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
        self.logger.info(message)

    def warning(self, message: str):
        self.logger.warning(message)

    def error(self, message: str):
        self.logger.error(message)

    def debug(self, message: str):
        self.logger.debug(message)


class MoMManager:
    def __init__(self):
        self.current_round = 0
        self.mom_data = {"rounds": []}

    def start_round(self, round_number: int):
        self.current_round = round_number
        self.mom_data["rounds"].append({
            "round": round_number,
            "timestamp": datetime.now().isoformat(),
            "stages": []
        })

    def add_stage(self, stage_name: str, agent: str, description: str = "", outputs: Any = None):
        if not self.mom_data["rounds"]:
            raise ValueError("請先呼叫 start_round()")

        stage_data = {
            "stage": stage_name,
            "agent": agent,
            "description": description,
            "timestamp": datetime.now().isoformat()
        }
        if outputs is not None:
            stage_data["outputs"] = outputs

        self.mom_data["rounds"][-1]["stages"].append(stage_data)

    def add_meeting(self, round_num: int, topic: Dict, contributions: List[Dict],
                    resolution: Dict, escalated_to_human: bool = False):
        if not self.mom_data["rounds"]:
            raise ValueError("請先呼叫 start_round()")

        current_round = self.mom_data["rounds"][-1]
        if "meetings" not in current_round:
            current_round["meetings"] = []

        meeting_count = len(current_round["meetings"]) + 1

        current_round["meetings"].append({
            "meeting_id": f"R{round_num}-M{meeting_count:02d}",
            "topic": {
                "id": topic.get("id", ""),
                "title": topic.get("title", ""),
                "type": topic.get("type", ""),
            },
            "contributions": contributions,
            "resolution": {
                "status": resolution.get("resolution", "unresolved"),
                "summary": resolution.get("summary", ""),
                "decision": resolution.get("decision", ""),
                "remaining_issues": resolution.get("remaining_issues", []),
                "action_items": resolution.get("action_items", []),
                "escalated_to_human": escalated_to_human,
            },
            "timestamp": datetime.now().isoformat(),
        })

    def get_latest_meeting(self) -> Dict:
        """取得最近一次新增的 meeting"""
        if not self.mom_data["rounds"]:
            return {}
        current_round = self.mom_data["rounds"][-1]
        meetings = current_round.get("meetings", [])
        return meetings[-1] if meetings else {}

    def update_meeting_resolution(self, round_num: int, meeting_idx: int, resolution: Dict):
        """更新指定 meeting 的 resolution（用於人類統一裁決後回填）"""
        for round_data in self.mom_data["rounds"]:
            if round_data.get("round") == round_num:
                meetings = round_data.get("meetings", [])
                idx = meeting_idx - 1  # meeting_idx 從 1 開始
                if 0 <= idx < len(meetings):
                    meetings[idx]["resolution"] = {
                        "status": resolution.get("resolution", "unresolved"),
                        "summary": resolution.get("summary", ""),
                        "decision": resolution.get("decision", ""),
                        "remaining_issues": resolution.get("remaining_issues", []),
                        "action_items": resolution.get("action_items", []),
                        "escalated_to_human": True,
                    }
                return

    def get_meeting_by_index(self, round_num: int, meeting_idx: int) -> Dict:
        """根據 round 和 meeting 索引取得 meeting 資料"""
        for round_data in self.mom_data["rounds"]:
            if round_data.get("round") == round_num:
                meetings = round_data.get("meetings", [])
                idx = meeting_idx - 1
                if 0 <= idx < len(meetings):
                    return meetings[idx]
        return {}

    def get_current_round(self) -> Dict:
        if self.mom_data["rounds"]:
            return self.mom_data["rounds"][-1]
        return {}

    def get_mom_data(self) -> Dict[str, Any]:
        return self.mom_data


class Collect:
    @staticmethod
    def user_selection(proposed: List[Dict[str, str]]) -> List[int]:
        while True:
            print("\n建議選擇的利害關係人：")
            for i, sh in enumerate(proposed, 1):
                print(f"{i}. {sh['name']}，理由: {sh['reason']}")

            print("\n提示: 可以輸入編號或直接輸入新的利害關係人名稱(例如: 1,3,系統管理員)")
            user_input = input("\n請選擇利害關係人(最多 5 位)：").strip()

            if not user_input:
                print("\n❌ 請至少選擇 1 個利害關係人")
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
                            print(f"\n⚠️ 編號 {part} 無效，已忽略")
                    except ValueError:
                        if part:
                            proposed.append({"name": part, "reason": "使用者自訂"})
                            selected_indices.append(len(proposed) - 1)

                if len(selected_indices) > 5:
                    print(f"\n⚠️ 選擇超過 5 個，請重新選擇")
                    continue

                if len(selected_indices) == 0:
                    print(f"\n❌ 至少需要選擇 1 個利害關係人")
                    continue

                print(f"\n✓ 已選擇的利害關係人：")
                for i, idx in enumerate(selected_indices, 1):
                    print(f"  {i}. {proposed[idx]['name']}")

                return selected_indices

            except Exception as e:
                print(f"\n❌ 錯誤：{e}")
                continue

    @staticmethod
    def human_decision_on_topic(topic: Dict, options: Dict) -> Dict:
        """人類裁決：顯示 Mediator 篩選的 3 個最佳方案 + 1 個折衷方案"""
        print(f"\n{'='*60}")
        print(f"需要人類裁決: {topic.get('title', '')}")
        print(f"議題描述: {topic.get('description', '')}")
        print(f"{'='*60}")

        best_options = options.get("best_options", [])
        compromise = options.get("compromise", {})

        # 顯示 3 個最佳方案
        print("\nMediator 推薦方案：")
        all_options = []
        for opt in best_options:
            idx = opt.get("id", len(all_options) + 1)
            print(f"\n  方案 {idx}. {opt.get('title', '')}")
            print(f"     來源: {opt.get('source', '?')}")
            print(f"     內容: {opt.get('description', '')}")
            all_options.append(opt)

        # 顯示折衷方案
        if compromise:
            c_idx = compromise.get("id", 4)
            print(f"\n  方案 {c_idx}. [折衷] {compromise.get('title', '')}")
            print(f"     內容: {compromise.get('description', '')}")
            print(f"     理由: {compromise.get('rationale', '')}")
            all_options.append(compromise)

        print(f"\n{'─'*40}")
        print("  0. 自行輸入裁決")

        user_input = input("\n請選擇方案編號（或 Enter 跳過）：").strip()

        if not user_input:
            return {
                "resolution": "unresolved",
                "summary": "人類選擇暫不裁決",
                "decision": "暫緩處理",
                "remaining_issues": [topic.get("title", "")],
                "action_items": [],
                "escalated_to_human": True,
            }

        try:
            choice = int(user_input)

            if choice == 0:
                custom = input("\n請輸入您的裁決：").strip()
                if not custom:
                    return {
                        "resolution": "unresolved",
                        "summary": "人類未輸入裁決",
                        "decision": "暫緩處理",
                        "remaining_issues": [topic.get("title", "")],
                        "action_items": [],
                        "escalated_to_human": True,
                    }
                return {
                    "resolution": "agreed",
                    "summary": f"由人類裁決: {custom}",
                    "decision": custom,
                    "remaining_issues": [],
                    "action_items": [],
                    "escalated_to_human": True,
                }

            # 在 all_options 中找到對應 id 的方案
            chosen = None
            for opt in all_options:
                if opt.get("id") == choice:
                    chosen = opt
                    break

            if chosen:
                title = chosen.get("title", "")
                desc = chosen.get("description", "")
                source = chosen.get("source", "折衷方案")
                return {
                    "resolution": "agreed",
                    "summary": f"人類採納方案 {choice}（{source}）: {title}",
                    "decision": desc,
                    "remaining_issues": [],
                    "action_items": [],
                    "escalated_to_human": True,
                }
            else:
                print("無效的選項，暫緩處理")
                return {
                    "resolution": "unresolved",
                    "summary": "無效輸入",
                    "decision": "暫緩處理",
                    "remaining_issues": [topic.get("title", "")],
                    "action_items": [],
                    "escalated_to_human": True,
                }
        except ValueError:
            print("無效的輸入，暫緩處理")
            return {
                "resolution": "unresolved",
                "summary": "無效輸入",
                "decision": "暫緩處理",
                "remaining_issues": [topic.get("title", "")],
                "action_items": [],
                "escalated_to_human": True,
            }

class AgentSelector:
    AGENT_MAP = {
        1: ("enable_user", "User（模擬利害關係人）"),
        2: ("enable_analyst", "Analyst（衝突分析）"),
        3: ("enable_expert", "Expert（專家建議）"),
        4: ("enable_mediator", "Mediator（調解）"),
        5: ("enable_modeler", "Modeler（系統建模）"),
        6: ("enable_documentor", "Documentor（文件產生）")
    }

    @staticmethod
    def select_agents(config: Dict[str, Any], agent: str = "\n請輸入要使用的 Agent (例如：1,3,5 或 0)：") -> List[int]:
        print("Agent：")
        for idx, (_, name) in AgentSelector.AGENT_MAP.items():
            print(f"{idx}. {name}")
        print("0. 全部使用")

        while True:
            try:
                agent_input = input(agent).strip()

                if agent_input == "0":
                    agent_choices = [1, 2, 3, 4, 5, 6]
                else:
                    agent_choices = [int(x.strip()) for x in agent_input.split(",") if x.strip()]

                if not agent_choices:
                    print("請至少選擇一個 Agent")
                    continue
                if not all(1 <= x <= 6 for x in agent_choices):
                    print("請輸入有效的 Agent（0-6）")
                    continue

                for idx in range(1, 7):
                    config[AgentSelector.AGENT_MAP[idx][0]] = False
                selected_names = []
                for choice in agent_choices:
                    key, name = AgentSelector.AGENT_MAP[choice]
                    config[key] = True
                    selected_names.append(name)

                print(f"✓ 已選擇：{', '.join(selected_names)}")
                return agent_choices

            except ValueError:
                print("輸入格式不正確，請輸入數字（用逗號分隔）")

    @staticmethod
    def set_rounds(round: str = "\n請輸入討論回合數：", allow_empty: bool = False) -> int:
        while True:
            rounds_input = input(round).strip()

            if not rounds_input:
                if allow_empty:
                    return 0
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


class ProjectManager:
    @staticmethod
    def select_or_create_project(store) -> Tuple[str, bool]:
        temp_store = Store(store.base_dir)
        projects = temp_store.list_projects()

        if not projects:
            print("\n目前沒有任何專案，將創建新專案")
            return None, False

        print("\n" + "="*60)
        print("現有專案列表\n")

        for i, project in enumerate(projects, 1):
            created_at = project.get("created_at", "未知")
            if "T" in created_at:
                try:
                    dt = datetime.fromisoformat(created_at)
                    created_at = dt.strftime("%Y-%m-%d %H:%M:%S")
                except:
                    pass
            print(f"{i}. 專案 ID: {project['project_id']}")
            print(f"   創建時間: {created_at}")
            print(f"   初始想法: {project.get('rough_idea', '未知')}\n")

        print("="*60)
        print("0. 創建新專案\n")

        while True:
            try:
                choice = input("請選擇專案編號 (或 0 創建新專案)：").strip()
                if not choice:
                    print("❌ 請輸入專案編號")
                    continue

                choice_num = int(choice)
                if choice_num == 0:
                    return None, False
                elif 1 <= choice_num <= len(projects):
                    project_id = projects[choice_num - 1]["project_id"]
                    print(f"\n✓ 已選擇專案：{project_id}")
                    return project_id, True
                else:
                    print(f"❌ 請輸入有效的專案編號 (0-{len(projects)})")
            except ValueError:
                print("❌ 請輸入數字")

    @staticmethod
    def display_project_info(store, project_id: str):
        artifact = store.load_artifact()

        completed_rounds = len(list(store.artifact_dir.glob("draft_*.json")))

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
        print("="*60 + "\n")
