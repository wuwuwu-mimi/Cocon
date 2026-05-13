"""免费搜索引擎工具，基于 DuckDuckGo（无需 API Key）"""
from ddgs import DDGS


async def web_search(query: str, max_results: int = 5) -> dict:
    """DuckDuckGo 搜索，免费、无需 API Key

    Args:
        query: 搜索关键词
        max_results: 返回结果数量，默认 5
    """
    try:
        results = []
        for item in DDGS().text(query, max_results=max_results):
            results.append({
                "title": item.get("title", ""),
                "snippet": item.get("body", ""),
                "url": item.get("href", ""),
            })
        return {"results": results, "count": len(results)}
    except Exception as e:
        return {"results": [], "count": 0, "error": str(e)}


WEB_SEARCH_SCHEMA = {
    "description": "联网搜索，返回搜索结果列表",
    "parameters": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "搜索关键词，支持中文和英文",
            },
            "max_results": {
                "type": "integer",
                "description": "返回结果数量，1-10，默认 5",
            },
        },
        "required": ["query"],
    },
}
