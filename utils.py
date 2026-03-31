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
            format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            handlers=[
                logging.FileHandler(log_file, encoding="utf-8"),
                logging.StreamHandler(),
            ],
        )
        self.logger = logging.getLogger("Plant")

    def info(self, msg, *args, **kwargs):
        """與標準 logging 相同，支援 info("a %s", x) 或 info("單一字串")。"""
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
    """
    追蹤 LLM token 使用量、執行時間與估算成本。
    """

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
        """結束目前計時區間，累加進 elapsed_seconds，回傳該區間秒數（供單次 API 的 run_time）。"""
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
        """
        支援多種欄位命名：
        - prompt_tokens / completion_tokens
        - input_tokens / output_tokens

        total_tokens 一律為 input + output（不採用供應商可能更大的 total），
        以便 agent_usage / cost_summary 彙總可核對 total = in + out。
        """
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


# ---------------------------------------------------------------------------
# 輸出語系（強制）：由 config.json 的 "output_language" 決定，不自動偵測。
# 有效值："zh-TW"（預設）、"en"。中文模式下敘述用繁中，標籤／FR／NFR／欄位名等維持英文。
# ---------------------------------------------------------------------------

OUTPUT_LANG_ZH = "zh-TW"
OUTPUT_LANG_EN = "en"
VALID_OUTPUT_LANGUAGES = (OUTPUT_LANG_ZH, OUTPUT_LANG_EN)


def resolve_output_language(config: Optional[Dict[str, Any]]) -> str:
    """從 config 讀取強制輸出語系；缺漏或無效時預設 zh-TW。"""
    if not config:
        return OUTPUT_LANG_ZH
    raw = config.get("output_language")
    if raw in VALID_OUTPUT_LANGUAGES:
        return raw
    return OUTPUT_LANG_ZH


def global_conventions_text(lang: str) -> str:
    if lang == OUTPUT_LANG_EN:
        return (
            "Use English for all human-visible descriptions, explanations, titles, statements, "
            "questions, summaries, and narrative fields; keep id, type, category, label, and "
            "other structural identifiers in English."
        )
    return (
        "對人可見的描述、說明、標題、敘述、statement、question、摘要等請使用繁體中文。"
        "下列維持英文（勿翻譯為中文）：id、type、category、label、JSON 鍵名、agent 識別名、"
        "需求編號（FR-…、NFR-… 等）、Conflict / Neutral 等狀態標籤、conflict_type、"
        "PlantUML 語法與圖上元素名、技術術語與結構化欄位名。"
    )


def directive_embed(lang: str) -> str:
    base = global_conventions_text(lang)
    override = (
        "If any skill or task text below conflicts with this language rule, follow this rule."
        if lang == OUTPUT_LANG_EN
        else "若 skill 或下文與上述語系要求衝突，以上述語系為準。"
    )
    return f"{base} {override}"


def mediator_agenda_language_line(lang: str) -> str:
    if lang == OUTPUT_LANG_EN:
        return (
            "Write title and description in English; keep category, discussion_mode, "
            "and participants as English identifiers."
        )
    return (
        "title、description 請使用繁體中文；category、discussion_mode、participants 等 id 維持英文"
    )


def short_reasoning_line(lang: str) -> str:
    if lang == OUTPUT_LANG_EN:
        return "Write reasoning in English."
    return "reasoning 請使用繁體中文"


def mediator_reasoning_line(lang: str) -> str:
    if lang == OUTPUT_LANG_EN:
        return (
            "Write reasoning in English, in a concise meeting-host tone: current consensus, "
            "why this action, expected outcome."
        )
    return (
        "reasoning 請使用繁體中文，並像真實會議主持人的口吻：簡短說明"
        "「目前共識狀態、為何採此動作、預期產出」"
    )


def mediator_prose_line(lang: str) -> str:
    if lang == OUTPUT_LANG_EN:
        return "Write in English; ids and field names may stay in English."
    return "用繁體中文撰寫；id 與欄位名稱可維持英文。"


def mediator_summary_decision_line(lang: str) -> str:
    if lang == OUTPUT_LANG_EN:
        return "Write summary and decision in English."
    return "summary、decision 請使用繁體中文"


def mediator_unresolved_vote_task_line(lang: str) -> str:
    if lang == OUTPUT_LANG_EN:
        return (
            "Topics below did not reach majority consensus. Summarize key discussion points in "
            "`summary` only; leave `decision` empty. Use English."
        )
    return (
        "以下議題經討論後以多數決判定為「未達成共識」。請簡要總結各方討論重點（summary 即可，decision 留空）。"
        "summary 請使用繁體中文。"
    )


def mediator_human_options_line(lang: str) -> str:
    if lang == OUTPUT_LANG_EN:
        return "3. Write title, description, rationale, and all narrative fields in English."
    return "3. title、description、rationale 等所有輸出文字請使用繁體中文"


def mediator_collect_line(lang: str) -> str:
    if lang == OUTPUT_LANG_EN:
        return (
            "In new_conflicts descriptions and new_decisions narrative text, use English. "
            "Keep label and conflict_type in English."
        )
    return (
        "new_conflicts 的 description、new_decisions 中與決策相關的描述文字請使用繁體中文。"
        "label、conflict_type 維持英文。"
    )


def modeler_review_field_language(lang: str) -> str:
    if lang == OUTPUT_LANG_EN:
        return (
            "- impact_summary: impact summary (English)\n"
            "- consistency_summary: overall consistency vs requirements (English)\n"
            "- gaps: list of gaps, one sentence each (English); [] if none"
        )
    return (
        "- impact_summary：影響摘要（繁體中文）\n"
        "- consistency_summary：與需求一致性的整體說明（繁體中文），例如：一致、部分一致、有缺口、或簡述哪些部分對齊、哪些未對齊\n"
        "- gaps：缺口或不一致項目列表，每項一句話描述（繁體中文）。例如：需求 FR-01 在模型中無對應、某圖與某圖命名不一致、某需求未被涵蓋。若無缺口則為空陣列 []"
    )


def modeler_name_field_language(lang: str) -> str:
    if lang == OUTPUT_LANG_EN:
        return "Use English for `name` (diagram display title)."
    return "name 使用繁體中文。"


def modeler_models_array_name_line(lang: str) -> str:
    if lang == OUTPUT_LANG_EN:
        return "Use English for each item's `name` (diagram display title) in `models`."
    return "models 陣列中的 name（圖表顯示名稱）請使用繁體中文。"


def analyst_draft_decision_table_note(lang: str) -> str:
    if lang == OUTPUT_LANG_EN:
        return (
            "Conflict requirements table: Issue | Requirements Affected | Decision. "
            "Requirements Affected: list each affected requirement ID with a one-line summary. "
            "Write Decision column in English. No Resolution Options. End draft at "
            '"Conflict requirements" / equivalent section heading.'
        )
    return (
        "Conflict 需求表格三欄：Issue | Requirements Affected（受影響需求）| Decision（決策）。"
        "Requirements Affected 欄位請寫詳細：列出受影響的需求 ID（FR-/NFR- 等，維持英文），並對每個 ID 附一句簡短摘要（該需求內容要點，繁中）；"
        "Decision 欄位標題與內容可使用繁體中文（如「待決」「已決：…」）。不要 Resolution Options。草稿結束於「Conflict 需求」。"
    )


def expert_topic_bullets_task(lang: str) -> str:
    if lang == OUTPUT_LANG_EN:
        return (
            "List 1–3 regulatory/compliance/safety bullet points for the topic (scope, risks). "
            "English only. No JSON."
        )
    return (
        "針對 Context 中的議題與專案狀態，簡要列出 1～3 點法規/合規/安全相關要點（可含適用範圍與風險），供會議發言參考。"
        "請使用繁體中文。只輸出簡短條列文字，勿 JSON。"
    )


def expert_fallback_viewpoint(lang: str) -> str:
    if lang == OUTPUT_LANG_EN:
        return (
            "As a domain expert, write 2–4 sentences with your professional view "
            "(regulations, best practices, risks). Do not leave empty; output English prose only."
        )
    return (
        "請以領域專家身份，用 2～4 句話簡要說明你對上述議題的專業看法（可含法規、最佳實務、技術建議或風險提醒）。"
        "勿留空，直接輸出繁體中文內容。"
    )


def user_stakeholder_name_reason(lang: str) -> str:
    if lang == OUTPUT_LANG_EN:
        return "Use English for each stakeholder name and reason."
    return "name、reason 請使用繁體中文"


def user_requirement_cards(lang: str) -> str:
    if lang == OUTPUT_LANG_EN:
        return "Use English for name and each text item in the arrays."
    return "name、text 陣列內容請使用繁體中文"


def srs_title_instruction(lang: str) -> str:
    if lang == OUTPUT_LANG_EN:
        return (
            "Document main title must be \"[<System Name>] Software Requirements Specification\"; "
            "derive the system name from scope, rough_idea, or draft."
        )
    return (
        "文件主標題必須為「[系統名稱]軟體需求規格書」，例如「外送平台系統軟體需求規格書」。"
        "系統名稱請從 Context 的 scope、rough_idea 或 draft 內容推得。"
        "勿使用 \"Software Requirements Specification\" 或 \"SRS\" 作為主標題。"
    )


def documentor_srs_body_lang(lang: str) -> str:
    if lang == OUTPUT_LANG_EN:
        return (
            "Write the full SRS narrative in English; keep requirement IDs (FR-…, NFR-…) in English."
        )
    return (
        "產出的 SRS 敘述全文請使用繁體中文；需求編號（FR-…、NFR-…）與章節中的英文標籤／欄位名維持英文。"
    )
