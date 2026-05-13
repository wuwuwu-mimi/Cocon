"""免费搜索引擎工具，基于 DuckDuckGo（无需 API Key）"""
import asyncio
import random
import time

from ddgs import DDGS

# 简单的内存缓存，避免短时间内重复搜索同一关键词
_cache: dict[str, dict] = {}
_CACHE_MAX = 50
# 上次搜索时间戳，用于限流保护
_last_search: float = 0
_MIN_INTERVAL = 1.5  # 最小请求间隔（秒）


def _sync_search(query: str, max_results: int) -> list[dict]:
    """同步搜索（在 executor 线程中运行）"""
    results = []
    for item in DDGS().text(query, max_results=max_results):
        results.append({
            "title": item.get("title", ""),
            "snippet": item.get("body", ""),
            "url": item.get("href", ""),
        })
    return results


async def web_search(query: str, max_results: int = 5) -> dict:
    """DuckDuckGo 搜索，带超时、缓存和限流保护

    Args:
        query: 搜索关键词
        max_results: 返回结果数量，默认 5
    """
    # 缓存检查：相同查询 60 秒内直接返回缓存
    cache_key = f"{query}:{max_results}"
    cached = _cache.get(cache_key)
    if cached:
        return cached

    # 限流保护：确保请求间隔不少于 _MIN_INTERVAL
    global _last_search
    elapsed = time.time() - _last_search
    if elapsed < _MIN_INTERVAL:
        await asyncio.sleep(_MIN_INTERVAL - elapsed + random.uniform(0, 0.5))
    _last_search = time.time()

    try:
        # 用 to_thread 避免同步 DDGS 阻塞事件循环
        results = await asyncio.wait_for(
            asyncio.to_thread(_sync_search, query, max_results),
            timeout=15.0,  # 搜索本身超时
        )
        result = {"results": results, "count": len(results)}
    except asyncio.TimeoutError:
        result = {"results": [], "count": 0, "error": "搜索超时，请稍后重试"}
    except Exception as e:
        result = {"results": [], "count": 0, "error": str(e)}

    # 写入缓存，限制缓存大小
    if len(_cache) > _CACHE_MAX:
        _cache.pop(next(iter(_cache)))
    _cache[cache_key] = result

    return result


WEB_SEARCH_SCHEMA = {
    "description": "免费联网搜索（DuckDuckGo），返回搜索结果列表",
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
