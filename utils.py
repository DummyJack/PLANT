import json
import logging
import re
import threading

from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence, Tuple
from pathlib import Path
from time import perf_counter
from store import Store

_SCI_JSON_NUMBER = re.compile(r"-?\d+(?:\.\d+)?[eE][+-]?\d+")


def json_dumps_no_scientific(
    obj: Any,
    *,
    indent: int = 2,
    ensure_ascii: bool = False,
) -> str:
    """json.dumps 後將數字字面上的科學記號改為十進位（避免 1.98e-05）。"""
    text = json.dumps(obj, indent=indent, ensure_ascii=ensure_ascii)

    def repl(m: re.Match) -> str:
        v = float(m.group(0))
        if v == 0.0:
            return "0"
        s = format(v, ".15f").rstrip("0").rstrip(".")
        return s if s else "0"

    return _SCI_JSON_NUMBER.sub(repl, text)


def json_dump_no_scientific(
    obj: Any,
    fp,
    *,
    indent: int = 2,
    ensure_ascii: bool = False,
) -> None:
    fp.write(
        json_dumps_no_scientific(obj, indent=indent, ensure_ascii=ensure_ascii)
    )


def _to_pos_int(value: Any, default: int) -> int:
    try:
        n = int(value)
        return n if n > 0 else default
    except (TypeError, ValueError):
        return default


def read_max_iterations(
    config: Dict[str, Any],
    *,
    default: int = 3,
) -> int:
    """讀取 max_iterations（僅支援單一整數設定）。"""
    raw = config.get("max_iterations")
    return _to_pos_int(raw, default)


def directive_embed() -> str:
    return "請使用繁體中文回覆。"


def global_conventions_text() -> str:
    return "請具體、精簡、可執行；避免空泛描述。引用網址時直接貼出完整 URL，不要使用 Markdown 超連結語法。"


def short_reasoning_line() -> str:
    return "reasoning 請使用一句繁體中文簡述。"


def user_requirement_cards() -> str:
    return "需求卡片請使用繁體中文。"


def user_stakeholder_name_reason() -> str:
    return "每位利害關係人需包含名稱與理由。"


def analyst_draft_decision_table_note() -> str:
    return "若有決策，請用精簡決策表呈現。"


def expert_topic_bullets_task() -> str:
    return "請提供 2～4 點重點，包含依據與風險。"


def expert_fallback_viewpoint() -> str:
    return "請以領域專家角度，簡短給出觀點與風險提醒。"


def mediator_agenda_language_line() -> str:
    return "title/description 請使用繁體中文。"


def mediator_collect_line() -> str:
    return "請清楚整理分歧與未解決事項。"


def mediator_human_options_line() -> str:
    return "請提供 2～4 個可選方案並附優缺點。"


def mediator_prose_line() -> str:
    return "請使用精簡敘述。"


def mediator_reasoning_line() -> str:
    return "reasoning 請使用一句繁體中文。"


def mediator_summary_decision_line() -> str:
    return "請簡述最終決議與理由。"


def mediator_unresolved_vote_task_line() -> str:
    return "若未解決，請明確說明是否升級為人類裁決。"


def modeler_models_array_name_line() -> str:
    return "陣列欄位名稱請使用 models。"


def modeler_name_field_language() -> str:
    return "name 欄位請使用繁體中文。"


def modeler_review_field_language() -> str:
    return "review 欄位說明請使用繁體中文。"


def documentor_srs_body_lang() -> str:
    return "內文請使用繁體中文。"


def srs_title_instruction() -> str:
    return "文件主標題必須為「[系統名稱]軟體需求規格書」。"


class Logger:
    def __init__(self, log_dir: str = "log"):
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime("%H%M%S")
        log_file = self.log_dir / f"system_{timestamp}.log"

        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            handlers=[
                logging.FileHandler(log_file, encoding="utf-8"),
                logging.StreamHandler(),
            ],
        )
        self.logger = logging.getLogger("Plant")

    def info(self, msg, *args, **kwargs):
        """同 logging.info，支援格式化參數。"""
        self.logger.info(msg, *args, **kwargs)

    def warning(self, msg, *args, **kwargs):
        self.logger.warning(msg, *args, **kwargs)

    def error(self, msg, *args, **kwargs):
        self.logger.error(msg, *args, **kwargs)


class Collect:
    @staticmethod
    def user_selection(
        proposed: List[Dict[str, str]], max_select: int = 5
    ) -> List[int]:
        while True:
            print("\n建議選擇的利害關係人：")
            for i, sh in enumerate(proposed, 1):
                print(f"{i}. {sh['name']}，理由: {sh['reason']}")

            print(
                "\n提示: 可以輸入編號或直接輸入新的利害關係人名稱(例如: 1,3,系統管理員)"
            )
            user_input = input(f"\n請選擇利害關係人(最多 {max_select} 位)：").strip()

            if not user_input:
                print("\n❌ 請至少選擇 1 個利害關係人")
                continue

            try:
                selected_indices = []
                parts = [x.strip() for x in user_input.split(",")]

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

        print("\n" + "=" * 60)
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

        print("=" * 60)
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
            created_at = datetime.fromtimestamp(
                store.project_dir.stat().st_ctime
            ).strftime("%Y-%m-%d %H:%M:%S")

        print("\n" + "=" * 60)
        print(f"專案資訊：{project_id}")
        print("=" * 60)
        print(f"創建時間: {created_at}")
        if artifact:
            print(f"初始想法: {artifact.get('rough_idea', '未知')}")
            discussions = artifact.get("discussions", [])
            print(f"已完成輪數: {len(discussions)}")
        print("=" * 60 + "\n")


class CostTracker:
    """LLM token、耗時與估算成本。"""

    # 單位：USD / 1M tokens
    DEFAULT_PRICING_PER_1M_TOKENS: Dict[str, Dict[str, float]] = {
        # 官方定價（Text tokens, Standard）
        "gpt-5.4": {"input": 2.50, "output": 15.00},
        "gpt-4.1": {"input": 2.00, "output": 8.00},
        "gpt-4o-mini": {"input": 0.15, "output": 0.60},
        "gemini-3.1-flash-lite-preview": {"input": 0.25, "output": 1.50},
        "gemini-3-flash-preview": {"input": 0.50, "output": 3.00},
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
        self.call_records: List[Dict[str, Any]] = []

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

    def end_segment(self) -> float:
        """結束本段計時並回傳秒數。"""
        with self.lock:
            if self.startedAt is None:
                return 0.0
            seg = perf_counter() - self.startedAt
            self.elapsed_seconds += seg
            self.startedAt = None
            return seg

    def addUsage(
        self,
        usage: Optional[Dict[str, Any]],
        metadata: Optional[Dict[str, Any]] = None,
        run_time_s: Optional[float] = None,
    ):
        """累加 token；total_tokens 固定為 input+output（可核對彙總）。"""
        if not usage:
            return

        input_count = int(usage.get("prompt_tokens", usage.get("input_tokens", 0)) or 0)
        output_count = int(
            usage.get("completion_tokens", usage.get("output_tokens", 0)) or 0
        )
        total_count = input_count + output_count

        with self.lock:
            record = {
                "input_tokens": input_count,
                "output_tokens": output_count,
                "total_tokens": total_count,
                "run_time(s)": round(float(run_time_s or 0.0), 3),
            }
            if metadata:
                record.update(metadata)
            self.call_records.append(record)
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
            self.call_records.clear()

    def get_call_records(self) -> List[Dict[str, Any]]:
        with self.lock:
            return list(self.call_records)

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

    def export_summary_dict(self) -> Dict[str, Any]:
        """匯出用：必回傳可序列化摘要（無定價表時 estimated_cost 可能為 0）。"""
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
                "has_pricing": self.resolvePricing(self.model_name) is not None,
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

VALID_DISCUSSION_MODES = {"sequential", "simultaneous"}
VALID_PRIORITY_HINTS = {"high", "medium", "low"}
VALID_ROUTING_ACTIONS = {
    "direct_apply",
    "direct_clarification",
    "formal_meeting",
    "human_decision",
}
VALID_IMPACT_LEVELS = {"high", "medium", "low"}


def normalize_topic_proposal(
    item: Dict[str, Any],
    *,
    allowed_categories: Sequence[str],
    default_participants: Sequence[str],
    proposed_by: str,
    round_num: int,
    index: int,
) -> Optional[Dict[str, Any]]:
    """驗證並正規化 agent topic proposal（固定 schema）。"""
    if not isinstance(item, dict):
        return None

    title = (item.get("title") or "").strip()
    description = (item.get("description") or "").strip()
    category = (item.get("category") or "").strip()
    why_now = (item.get("why_now") or "").strip()
    if not title or not description or not category or not why_now:
        return None
    if category not in set(allowed_categories):
        return None

    participants = [
        str(p).strip()
        for p in (item.get("participants") or [])
        if str(p).strip()
    ]
    participants = list(dict.fromkeys(participants))
    if not participants:
        participants = list(default_participants)
    if not participants:
        return None

    discussion_mode = (item.get("discussion_mode") or "sequential").strip()
    if discussion_mode not in VALID_DISCUSSION_MODES:
        discussion_mode = "sequential"

    speaking_order = [
        str(p).strip()
        for p in (item.get("speaking_order") or participants)
        if str(p).strip() in participants
    ]
    speaking_order = list(dict.fromkeys(speaking_order))
    if set(speaking_order) != set(participants):
        speaking_order = list(participants)

    source_ids = [
        str(s).strip() for s in (item.get("source_ids") or [])
        if str(s).strip()
    ]
    source_ids = list(dict.fromkeys(source_ids))

    priority_hint = (item.get("priority_hint") or "medium").strip().lower()
    if priority_hint not in VALID_PRIORITY_HINTS:
        priority_hint = "medium"
    impact_level = (item.get("impact_level") or priority_hint or "medium").strip().lower()
    if impact_level not in VALID_IMPACT_LEVELS:
        impact_level = priority_hint

    proposal_id = (item.get("proposal_id") or "").strip()
    if not proposal_id:
        proposal_id = f"P-R{round_num:02d}-{proposed_by}-{index:03d}"
    routing_preference = (item.get("routing_preference") or "formal_meeting").strip()
    if routing_preference not in VALID_ROUTING_ACTIONS:
        routing_preference = "formal_meeting"

    return {
        "schema_version": "topic_proposal.v1",
        "proposal_id": proposal_id,
        "title": title,
        "description": description,
        "category": category,
        "participants": participants,
        "discussion_mode": discussion_mode,
        "speaking_order": speaking_order,
        "source_ids": source_ids,
        "priority_hint": priority_hint,
        "impact_level": impact_level,
        "why_now": why_now,
        "proposed_by": proposed_by,
        "round": round_num,
        "deferred_rounds": int(item.get("deferred_rounds") or 0),
        "routing_preference": routing_preference,
        "requires_multi_party": bool(item.get("requires_multi_party")),
        "blocks_decision": bool(item.get("blocks_decision")),
        "needs_human": bool(item.get("needs_human")),
        "status": (item.get("status") or "proposed").strip() or "proposed",
    }


def normalize_agenda_topic(
    item: Dict[str, Any],
    *,
    allowed_categories: Sequence[str],
    registered_agents: Sequence[str],
    index: int,
) -> Optional[Dict[str, Any]]:
    """驗證並正規化正式 agenda topic（固定 schema）。"""
    if not isinstance(item, dict):
        return None
    title = (item.get("title") or "").strip()
    description = (item.get("description") or "").strip()
    category = (item.get("category") or "").strip()
    if not title or not category:
        return None
    if category not in set(allowed_categories):
        return None

    participants = [
        str(p).strip()
        for p in (item.get("participants") or [])
        if str(p).strip() in set(registered_agents)
    ]
    participants = list(dict.fromkeys(participants))
    if not participants:
        participants = list(registered_agents)
    if not participants:
        return None

    discussion_mode = (item.get("discussion_mode") or "sequential").strip()
    if discussion_mode not in VALID_DISCUSSION_MODES:
        discussion_mode = "sequential"

    speaking_order = [
        str(p).strip()
        for p in (item.get("speaking_order") or participants)
        if str(p).strip() in participants
    ]
    speaking_order = list(dict.fromkeys(speaking_order))
    if set(speaking_order) != set(participants):
        speaking_order = list(participants)

    source_ids = [
        str(s).strip()
        for s in (item.get("source_ids") or [])
        if str(s).strip()
    ]
    source_ids = list(dict.fromkeys(source_ids))
    source_proposal_ids = [
        str(s).strip()
        for s in (item.get("source_proposal_ids") or [])
        if str(s).strip()
    ]
    source_proposal_ids = list(dict.fromkeys(source_proposal_ids))
    routing_action = (item.get("triage_action") or "formal_meeting").strip()
    if routing_action not in VALID_ROUTING_ACTIONS:
        routing_action = "formal_meeting"

    topic_id = (item.get("id") or "").strip() or f"T-{index:02d}"
    return {
        "schema_version": "agenda_topic.v1",
        "id": topic_id,
        "title": title,
        "description": description,
        "category": category,
        "participants": participants,
        "discussion_mode": discussion_mode,
        "speaking_order": speaking_order,
        "source_ids": source_ids,
        "source_proposal_ids": source_proposal_ids,
        "status": (item.get("status") or "scheduled").strip() or "scheduled",
        "triage_action": routing_action,
    }

