import json
import os

import httpx
from dotenv import load_dotenv

load_dotenv()


async def web_search(query: str) -> dict:
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "https://google.serper.dev/search",
            json={"q": query,
                  "gl": "cn",
                  "hl": "zh-cn",
                  "tbs": "qdr:d"},
            headers={"X-API-KEY": os.getenv("X_API_KEY"), 'Content-Type': 'application/json'},
            timeout=20,
        )

        data = resp.json()

    results = []
    for item in data.get("organic", [])[:5]:
        results.append(
            {
                "title": item.get("title"),
                "snippet": item.get("snippet"),
                "link": item.get("link"),
            }
        )
    return {"results": results, "count": len(results)}


WEB_SEARCH_SCHEMA = {
    "description": "联网搜索，返回搜索结果列表",
    "parameters": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "搜索关键词"},
        },
        "required": ["query"],
    }
}
