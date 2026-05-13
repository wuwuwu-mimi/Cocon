"""飞书 Webhook 消息发送工具"""
import os

import httpx
from dotenv import load_dotenv

load_dotenv()

FEISHU_WEBHOOK_URL = os.getenv("FEISHU_WEBHOOK_URL", "")
MAX_MSG_LENGTH = 3000  # 飞书富文本单段限制


async def feishu_send(title: str, content: str, source_urls: str = "") -> dict:
    """发送飞书消息卡片

    Args:
        title: 消息标题（如"任务完成摘要"）
        content: 消息正文（3-5条要点，支持 Markdown 基础语法）
        source_urls: 信息来源链接，换行分隔
    """
    if not FEISHU_WEBHOOK_URL:
        return {"ok": False, "error": "未配置 FEISHU_WEBHOOK_URL"}

    # 构建飞书 post 富文本消息
    body_content = []
    for line in content.strip().split("\n"):
        if line.strip():
            body_content.append([{"tag": "text", "text": line.strip()}])

    # 追加来源链接
    if source_urls:
        body_content.append([{"tag": "text", "text": "\n---\n信息来源:"}])
        for url in source_urls.strip().split("\n"):
            if url.strip():
                body_content.append([
                    {"tag": "a", "text": url.strip(), "href": url.strip()}
                ])

    post = {
        "msg_type": "post",
        "content": {
            "post": {
                "zh_cn": {
                    "title": title[:200],
                    "content": body_content,
                }
            }
        }
    }

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            FEISHU_WEBHOOK_URL,
            json=post,
            headers={"Content-Type": "application/json"},
            timeout=15,
        )
        data = resp.json()

    if data.get("code") == 0:
        return {"ok": True, "data": {"msg_id": data.get("data", {}).get("message_id", "")}}
    else:
        return {"ok": False, "error": f"飞书发送失败: {data.get('msg', data)}"}


FEISHU_SEND_SCHEMA = {
    "description": "发送消息到飞书群，支持 Markdown 格式和超链接",
    "parameters": {
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "消息标题"},
            "content": {"type": "string", "description": "消息正文，3-5条要点"},
            "source_urls": {"type": "string", "description": "信息来源链接列表"},
        },
        "required": ["title", "content"],
    },
}
