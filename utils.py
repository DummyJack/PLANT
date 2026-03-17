import logging
import threading

from datetime import datetime
from typing import Dict, Any, List, Tuple, Optional
from pathlib import Path
from time import perf_counter
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


class Collect:
    @staticmethod
    def user_selection(proposed: List[Dict[str, str]], max_select: int = 5) -> List[int]:
        while True:
            print("\n建議選擇的利害關係人：")
            for i, sh in enumerate(proposed, 1):
                print(f"{i}. {sh['name']}，理由: {sh['reason']}")

            print("\n提示: 可以輸入編號或直接輸入新的利害關係人名稱(例如: 1,3,系統管理員)")
            user_input = input(f"\n請選擇利害關係人(最多 {max_select} 位)：").strip()

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

                if len(selected_indices) > max_select:
                    print(f"\n⚠️ 選擇超過 {max_select} 個，請重新選擇")
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
        print(f"\n{'='*60}")
        print(f"需要人類裁決: {topic.get('title', '')}")
        print(f"議題描述: {topic.get('description', '')}")
        print(f"{'='*60}")

        best_options = options.get("best_options", [])
        compromise = options.get("compromise", {})

        print("\nMediator 推薦方案：")
        all_options = []
        for opt in best_options:
            idx = opt.get("id", len(all_options) + 1)
            print(f"\n  方案 {idx}. {opt.get('title', '')}")
            print(f"     來源: {opt.get('source', '?')}")
            print(f"     內容: {opt.get('description', '')}")
            all_options.append(opt)

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
                    }
                return {
                    "resolution": "agreed",
                    "summary": f"由人類裁決: {custom}",
                    "decision": custom,
                }

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
                }
            else:
                print("無效的選項，暫緩處理")
                return {
                    "resolution": "unresolved",
                    "summary": "無效輸入",
                    "decision": "暫緩處理",
                }
        except ValueError:
            print("無效的輸入，暫緩處理")
            return {
                    "resolution": "unresolved",
                    "summary": "無效輸入",
                    "decision": "暫緩處理",
                }


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

        created_at = "未知"
        if store.project_dir.exists():
            created_at = datetime.fromtimestamp(store.project_dir.stat().st_ctime).strftime("%Y-%m-%d %H:%M:%S")

        print("\n" + "="*60)
        print(f"專案資訊：{project_id}")
        print("="*60)
        print(f"創建時間: {created_at}")
        if artifact:
            print(f"初始想法: {artifact.get('rough_idea', '未知')}")
            discussions = artifact.get("discussions", [])
            print(f"已完成輪數: {len(discussions)}")
        print("="*60 + "\n")


class CostTracker:
    """
    追蹤 LLM token 使用量、執行時間與估算成本。
    """

    # 單位：USD / 1M tokens
    DEFAULT_PRICING_PER_1M_TOKENS: Dict[str, Dict[str, float]] = {
        # OpenAI 官方定價（Text tokens, Standard）
        "gpt-5.4": {"input": 2.50, "output": 15.00},
        "gpt-4.1": {"input": 2.00, "output": 8.00},
        "gpt-4o-mini": {"input": 0.15, "output": 0.60},
    }

    def __init__(
        self,
        model_name: str,
        pricing_per_1m_tokens: Optional[Dict[str, Dict[str, float]]] = None,
    ):
        self.model_name = model_name
        self.pricing_per_1m_tokens = (
            pricing_per_1m_tokens or self.DEFAULT_PRICING_PER_1M_TOKENS
        )

        self.input_tokens = 0
        self.output_tokens = 0
        self.total_tokens = 0
        self.elapsed_seconds = 0.0
        self.estimated_cost_usd = 0.0

        self.startedAt = None
        self.lock = threading.Lock()

    def start(self):
        with self.lock:
            self.startedAt = perf_counter()

    def stop(self) -> float:
        with self.lock:
            if self.startedAt is None:
                return self.elapsed_seconds
            self.elapsed_seconds += perf_counter() - self.startedAt
            self.startedAt = None
            return self.elapsed_seconds

    def addUsage(self, usage: Optional[Dict[str, Any]]):
        """
        支援多種欄位命名：
        - prompt_tokens / completion_tokens
        - input_tokens / output_tokens
        - total_tokens（若缺少會自動相加）
        """
        if not usage:
            return

        input_count = int(
            usage.get("prompt_tokens", usage.get("input_tokens", 0)) or 0
        )
        output_count = int(
            usage.get("completion_tokens", usage.get("output_tokens", 0)) or 0
        )
        total_count = int(usage.get("total_tokens", input_count + output_count) or 0)

        with self.lock:
            self.input_tokens += input_count
            self.output_tokens += output_count
            self.total_tokens += total_count
            self.estimated_cost_usd += self.estimateCost(input_count, output_count)

    def reset(self):
        with self.lock:
            self.input_tokens = 0
            self.output_tokens = 0
            self.total_tokens = 0
            self.elapsed_seconds = 0.0
            self.estimated_cost_usd = 0.0
            self.startedAt = None

    def summary(self) -> Optional[Dict[str, Any]]:
        pricing = self.resolvePricing(self.model_name)
        if pricing is None:
            return None

        with self.lock:
            current_elapsed = self.elapsed_seconds
            if self.startedAt is not None:
                current_elapsed += perf_counter() - self.startedAt

        return {
            "model": self.model_name,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
            "run_time(s)": round(current_elapsed, 3),
            "estimated_cost(USD)": round(self.estimated_cost_usd, 8),
        }

    def resolvePricing(self, model_name: str) -> Optional[Dict[str, float]]:
        if model_name in self.pricing_per_1m_tokens:
            return self.pricing_per_1m_tokens[model_name]

        # 支援前綴比對，例如 gpt-4o-2024-xx
        for key, value in self.pricing_per_1m_tokens.items():
            if key != "default" and model_name.startswith(key):
                return value

        return None

    def estimateCost(self, input_tokens: int, output_tokens: int) -> float:
        pricing = self.resolvePricing(self.model_name)
        if not pricing:
            return 0.0

        input_price = float(pricing.get("input", 0.0))
        output_price = float(pricing.get("output", 0.0))

        input_cost = (input_tokens / 1_000_000) * input_price
        output_cost = (output_tokens / 1_000_000) * output_price
        return input_cost + output_cost
