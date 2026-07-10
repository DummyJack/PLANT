# Defines available agent tools and tool execution behavior.
import copy
import logging
import re
from typing import Any, Dict, List, Optional, Set, Tuple
from urllib.parse import urlparse

from .base import BaseTool

logger = logging.getLogger("Plant.WebSearchTool")

MAX_TAVILY_QUERY_CHARS = 400


# ========
# Defines token set function for this module workflow.
# ========
def token_set(text: str, min_len: int = 2) -> Set[str]:
    if not text:
        return set()
    return {
        w.lower()
        for w in re.findall(r"[\w\u4e00-\u9fff]+", text)
        if len(w) >= min_len
    }


# ========
# Defines jaccard function for this module workflow.
# ========
def jaccard(a: Set[str], b: Set[str]) -> float:
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


# ========
# Defines netloc function for this module workflow.
# ========
def netloc(url: str) -> str:
    try:
        return (urlparse(url).netloc or "").lower().lstrip("www.")
    except Exception:
        return ""


# ========
# Defines credible source URL function for this module workflow.
# ========
def credible_source_url(url: str) -> bool:
    try:
        from agents.profile.expert.validation import credible_source_url as is_credible

        return is_credible(url)
    except Exception:
        host = netloc(url)
        return bool(host and (".gov" in host or ".edu" in host or ".org" in host))


def compact_search_query(query: str, *, max_chars: int = MAX_TAVILY_QUERY_CHARS) -> str:
    text = re.sub(r"\s+", " ", str(query or "")).strip()
    if len(text) <= max_chars:
        return text
    separators = r"[，。；、,;|｜\n\r\t]+"
    parts = [
        part.strip(" -:：")
        for part in re.split(separators, text)
        if part.strip(" -:：")
    ]
    kept: List[str] = []
    used_tokens: Set[str] = set()
    for part in parts:
        tokens = token_set(part, min_len=2)
        if tokens and tokens <= used_tokens:
            continue
        candidate = " ".join([*kept, part]).strip()
        if len(candidate) > max_chars:
            continue
        kept.append(part)
        used_tokens |= tokens
    if kept:
        return " ".join(kept)[:max_chars].strip()
    return text[:max_chars].strip()


# ========
# Defines WebSearchTool class for this module workflow.
# ========
class WebSearchTool(BaseTool):
    name = "web_search"
    description = (
        "搜尋網路上的法規、標準、技術文件、最佳實務等公開資訊。"
        "必須填 query 與 max_results，max_results 必須是大於 0 的整數。"
        "可選填 user_question 傳入使用者原始問題，以便判斷是否已累積足夠內容可作答。"
        "同一對話回合內若觸發停止條件，後續呼叫會直接拒絕搜尋（請改整理答案）。"
    )
    parameters = {
        "query": {
            "type": "string",
            "description": "搜尋關鍵字（建議使用英文以獲得更多結果）",
            "required": True,
        },
        "max_results": {
            "type": "integer",
            "description": "必填。此次搜尋要回傳的結果筆數，必須是大於 0 的整數。",
            "required": True,
        },
        "user_question": {
            "type": "string",
            "description": "選填。使用者原始問題全文；用於判斷關鍵詞是否已被搜尋結果涵蓋，以觸發停止條件。",
            "required": False,
        },
    }

    # Defines __init__ function for this module workflow.
    def __init__(
        self,
        api_key: Optional[str] = None,
        *,
        stop_config: Optional[Dict[str, Any]] = None,
    ):
        self.api_key = api_key
        self.parameters = copy.deepcopy(type(self).parameters)
        self.client = None
        cfg = stop_config or {}
        self.thr_redundant_query = float(cfg.get("redundant_query_jaccard", 0.58))
        self.thr_consistent_sources = float(cfg.get("consistent_sources_jaccard", 0.2))
        self.thr_user_coverage = float(cfg.get("user_question_coverage", 0.72))
        self.thr_novel_tokens = float(cfg.get("novel_token_ratio_min", 0.1))
        self.min_domain_tokens = int(cfg.get("min_domain_tokens", 8))
        self.reset_session()

    # Defines reset session function for this module workflow.
    def reset_session(self) -> None:
        self.halted = False
        self.halt_messages: List[str] = []
        self.queries: List[str] = []
        self.seen_urls: Set[str] = set()
        self.cumulative_tokens: Set[str] = set()
        self.domain_tokens: Dict[str, Set[str]] = {}
        self.user_question: Optional[str] = None

    # Defines get client function for this module workflow.
    def get_client(self):
        if self.client is None:
            api_key = self.api_key
            if not api_key:
                import os

                api_key = os.getenv("TAVILY_API_KEY")
            if not api_key:
                raise ValueError(
                    "TAVILY_API_KEY 未設定。請在 .env 中設定 TAVILY_API_KEY 或在初始化時傳入 api_key。"
                )
            from tavily import TavilyClient

            self.client = TavilyClient(api_key=api_key)
        return self.client

    # Defines maybe set user question function for this module workflow.
    def maybe_set_user_question(self, kwargs: Dict[str, Any]) -> None:
        uq = kwargs.get("user_question")
        if isinstance(uq, str) and uq.strip() and self.user_question is None:
            self.user_question = uq.strip()

    # Defines query redundant function for this module workflow.
    def query_redundant(self, query: str) -> bool:
        q_tokens = token_set(query)
        if len(q_tokens) < 2:
            return False
        for prev in self.queries:
            if jaccard(q_tokens, token_set(prev)) >= self.thr_redundant_query:
                return True
        return False

    # Defines two consistent sources function for this module workflow.
    def two_consistent_sources(self) -> bool:
        hosts = [
            h
            for h, toks in self.domain_tokens.items()
            if len(toks) >= self.min_domain_tokens
        ]
        if len(hosts) < 2:
            return False
        for i in range(len(hosts)):
            for j in range(i + 1, len(hosts)):
                if (
                    jaccard(self.domain_tokens[hosts[i]], self.domain_tokens[hosts[j]])
                    >= self.thr_consistent_sources
                ):
                    return True
        return False

    # Defines can answer user question function for this module workflow.
    def can_answer_user_question(self) -> bool:
        if not self.user_question:
            return False
        g = token_set(self.user_question)
        if not g:
            return False
        hits = sum(1 for t in g if t in self.cumulative_tokens)
        return hits / len(g) >= self.thr_user_coverage

    # Defines merge result batch function for this module workflow.
    def merge_result_batch(self, items: List[Dict[str, Any]]) -> Tuple[int, float]:
        pre = set(self.cumulative_tokens)
        new_urls = 0
        batch_tokens: Set[str] = set()
        for item in items:
            url = (item.get("url") or "").strip()
            content = item.get("content") or ""
            title = item.get("title") or ""
            blob = f"{title}\n{content}"
            toks = token_set(blob)
            batch_tokens |= toks
            if url:
                if url not in self.seen_urls:
                    new_urls += 1
                self.seen_urls.add(url)
                host = netloc(url)
                if host:
                    self.domain_tokens.setdefault(host, set()).update(toks)
        novel = batch_tokens - pre
        ratio = len(novel) / max(1, len(batch_tokens))
        self.cumulative_tokens |= batch_tokens
        return new_urls, ratio

    # Defines evaluate stop after batch function for this module workflow.
    def evaluate_stop_after_batch(
        self, new_urls: int, novel_ratio: float, items: List[Dict[str, Any]]
    ) -> List[str]:
        reasons: List[str] = []
        if self.two_consistent_sources():
            reasons.append(
                "已累積至少兩個不同網域來源，且摘要詞彙高度重疊（一致來源），可停止再搜尋。"
            )
        if self.can_answer_user_question():
            reasons.append(
                "依目前累積的摘要內容，使用者原始問題中的關鍵詞多數已出現，可嘗試直接作答。"
            )
        if items and new_urls == 0 and novel_ratio < self.thr_novel_tokens:
            reasons.append(
                "本輪結果的網址皆已出現過，且內容詞彙與先前高度重疊，無明顯新資訊。"
            )
        return reasons

    # Defines footer stop function for this module workflow.
    def footer_stop(self, reasons: List[str]) -> str:
        if not reasons:
            return ""
        self.halted = True
        self.halt_messages = reasons
        lines = "\n".join(f"- {r}" for r in reasons)
        return (
            "\n\n---\n【web_search 停止條件】以下成立，請勿再呼叫 web_search，請整理並回答使用者。\n"
            f"{lines}\n"
        )

    # Defines execute function for this module workflow.
    def execute(self, **kwargs) -> str:
        query = kwargs.get("query", "")
        if not isinstance(query, str):
            query = str(query or "")
        query = query.strip()
        if not query:
            return "錯誤: 搜尋關鍵字不可為空"
        original_query = query
        query = compact_search_query(query)
        if query != original_query:
            logger.info(
                "搜尋 query 過長，已由 %s 字縮短為 %s 字",
                len(original_query),
                len(query),
            )

        self.maybe_set_user_question(kwargs)

        if self.halted:
            prev = "；".join(self.halt_messages) if self.halt_messages else "已觸發"
            return (
                "【web_search 已停止】本回合先前已滿足停止條件，請勿再搜尋。"
                f"原因摘要：{prev}"
            )

        if self.query_redundant(query):
            self.halted = True
            self.halt_messages = [
                "新的搜尋 query 與先前查詢高度重複，繼續搜尋效益極低。"
            ]
            return (
                "【web_search 停止】此次 query 與先前搜尋關鍵詞高度重複，已不執行 API 呼叫。"
                "請改用不同角度關鍵詞，或直接根據既有結果作答。"
            )

        n = kwargs.get("max_results")
        if not isinstance(n, int) or n < 1:
            return "錯誤: max_results 為必填且必須是大於 0 的整數"
        max_results = n
        search_results_limit = min(max(max_results * 3, max_results), 20)

        try:
            client = self.get_client()
            results = client.search(
                query=query, max_results=search_results_limit, search_depth="basic"
            )
        except ImportError:
            return "錯誤: tavily-python 套件未安裝，請執行 pip install tavily-python"
        except Exception as e:
            logger.error("網路搜尋失敗: %s", e)
            return f"搜尋失敗: {str(e)}"

        self.queries.append(query)
        raw_items = results.get("results") or []
        items = [
            item for item in raw_items
            if credible_source_url(str(item.get("url") or ""))
        ][:max_results]
        if not items:
            body = "未找到符合可信來源條件的相關結果。"
        else:
            filtered_results = dict(results)
            filtered_results["results"] = items
            body = self.format_results(filtered_results)

        new_urls, novel_ratio = self.merge_result_batch(items)
        reasons = self.evaluate_stop_after_batch(new_urls, novel_ratio, items)
        footer = self.footer_stop(reasons)
        return body + footer

    # Defines format results function for this module workflow.
    def format_results(self, results: Dict[str, Any]) -> str:
        items = results.get("results", [])
        if not items:
            return "未找到相關結果。"

        formatted = []
        for i, item in enumerate(items, 1):
            title = item.get("title", "無標題")
            url = item.get("url", "")
            content = item.get("content", "無內容")

            formatted.append(
                f"{i}. {title}\n"
                f"   URL: {url}\n"
                f"   摘要: {content}"
            )

        return "\n\n".join(formatted)
