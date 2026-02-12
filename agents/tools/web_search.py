import logging

from typing import Dict, Any, Optional
from .base import BaseTool

logger = logging.getLogger("Plant.WebSearchTool")


class WebSearchTool(BaseTool):
    """網路搜尋工具，使用 Tavily API

    專為 AI Agent 設計的搜尋 API，回傳結構化的搜尋結果。
    ExpertAgent 在 ReAct 迴圈中使用此工具搜尋法規、標準、最佳實務。
    """

    name = "web_search"
    description = "搜尋網路上的法規、標準、技術文件、最佳實務等公開資訊"
    parameters = {
        "query": {
            "type": "string",
            "description": "搜尋關鍵字（建議使用英文以獲得更多結果）",
            "required": True
        }
    }

    def __init__(self, api_key: Optional[str] = None, max_results: int = 3):
        """初始化 Web Search 工具

        Args:
            api_key: Tavily API Key（若未提供，從環境變數 TAVILY_API_KEY 取得）
            max_results: 每次搜尋回傳的最大結果數
        """
        self.api_key = api_key
        self.max_results = max_results
        self._client = None

    def get_client(self):
        """延遲初始化 Tavily client"""
        if self._client is None:
            api_key = self.api_key
            if not api_key:
                import os
                api_key = os.getenv("TAVILY_API_KEY")
            if not api_key:
                raise ValueError(
                    "TAVILY_API_KEY 未設定。請在 .env 中設定 TAVILY_API_KEY 或在初始化時傳入 api_key。"
                )
            from tavily import TavilyClient
            self._client = TavilyClient(api_key=api_key)
        return self._client

    def execute(self, **kwargs) -> str:
        """執行網路搜尋

        Args:
            query: 搜尋關鍵字

        Returns:
            格式化的搜尋結果文字
        """
        query = kwargs.get("query", "")
        if not query:
            return "錯誤: 搜尋關鍵字不可為空"

        try:
            client = self.get_client()
            results = client.search(
                query=query,
                max_results=self.max_results,
                search_depth="basic"
            )
            return self.format_results(results)
        except ImportError:
            return "錯誤: tavily-python 套件未安裝，請執行 pip install tavily-python"
        except Exception as e:
            logger.error(f"網路搜尋失敗: {e}")
            return f"搜尋失敗: {str(e)}"

    def format_results(self, results: Dict[str, Any]) -> str:
        """格式化搜尋結果

        Args:
            results: Tavily API 回傳的原始結果

        Returns:
            格式化的文字
        """
        items = results.get("results", [])
        if not items:
            return "未找到相關結果。"

        formatted = []
        for i, item in enumerate(items, 1):
            title = item.get("title", "無標題")
            url = item.get("url", "")
            content = item.get("content", "無內容")
            # 截斷過長的內容
            if len(content) > 300:
                content = content[:300] + "..."

            formatted.append(
                f"{i}. {title}\n"
                f"   URL: {url}\n"
                f"   摘要: {content}"
            )

        return "\n\n".join(formatted)
