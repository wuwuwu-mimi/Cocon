"""飞书机器人：WebSocket 长连接接收 @消息 → Cocon pipeline → 回复"""
import asyncio
import json
import logging
import os
import threading

from dotenv import load_dotenv
from fastapi import APIRouter

import lark_oapi as lark
from lark_oapi.api.im.v1 import P2ImMessageReceiveV1, CreateMessageRequest, CreateMessageRequestBody
from lark_oapi.event.dispatcher_handler import EventDispatcherHandler

from orchestrator.graph import graph

load_dotenv()
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/feishu")

APP_ID = os.getenv("FEISHU_APP_ID", "")
APP_SECRET = os.getenv("FEISHU_APP_SECRET", "")

# 飞书 API 客户端
_client = lark.Client.builder() \
    .app_id(APP_ID) \
    .app_secret(APP_SECRET) \
    .build()

# 保存主线程事件循环，供 lark 回调线程提交 async 任务
_main_loop: asyncio.AbstractEventLoop | None = None


# ---------------------------------------------------------------------------
# 发送消息
# ---------------------------------------------------------------------------

def send_text(chat_id: str, text: str):
    """发送文本消息到群聊或私聊"""
    if not chat_id:
        return
    if len(text) > 4000:
        text = text[:4000] + "\n...(truncated)"

    req = CreateMessageRequest.builder() \
        .receive_id_type("chat_id") \
        .request_body(
            CreateMessageRequestBody.builder()
            .receive_id(chat_id)
            .msg_type("text")
            .content(json.dumps({"text": text}))
            .build()
        ).build()
    _client.im.v1.message.create(req)


# ---------------------------------------------------------------------------
# 消息处理
# ---------------------------------------------------------------------------

def on_message(event: P2ImMessageReceiveV1) -> None:
    """收到 @机器人 消息"""
    msg = event.event.message
    chat_id = msg.chat_id
    msg_id = msg.message_id

    # 解析文本
    text = ""
    try:
        content = json.loads(msg.content)
        text = content.get("text", "")
    except (json.JSONDecodeError, TypeError):
        text = str(msg.content)

    # 去掉 @ 前缀
    import re
    text = re.sub(r'@\S+\s*', '', text).strip()

    logger.info("[feishu] chat=%s text=%s", chat_id, text[:100])

    if not text:
        send_text(chat_id, "请告诉我你想做什么？例如：搜索最新Python框架")
        return

    # 后台异步执行 pipeline（lark 回调在独立线程，用 call_soon_threadsafe 提交到主事件循环）
    async def run():
        try:
            result = await graph.ainvoke(
                {"original_query": text},
                {"configurable": {"thread_id": msg_id}},
            )
            final = result.get("final_output", "")
            if not final:
                final = "未能生成结果。"
            send_text(chat_id, final)
        except Exception as e:
            logger.error("[feishu] pipeline: %s", str(e))
            send_text(chat_id, f"内部错误: {str(e)[:200]}")

    if _main_loop:
        asyncio.run_coroutine_threadsafe(run(), _main_loop)


# ---------------------------------------------------------------------------
# 注册事件处理器 & 启动长连接
# ---------------------------------------------------------------------------

_handler = EventDispatcherHandler.builder("", "") \
    .register_p2_im_message_receive_v1(on_message) \
    .build()


def _run_ws_loop():
    """在独立线程中运行飞书 WebSocket 长连接"""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    # 直接替换 ws.client 模块的 loop 变量（它在 import 时固定了事件循环）
    import lark_oapi.ws.client as ws_client_module
    ws_client_module.loop = loop

    try:
        from lark_oapi.ws import Client
        ws_client = Client(
            app_id=APP_ID,
            app_secret=APP_SECRET,
            event_handler=_handler,
            log_level=lark.LogLevel.DEBUG,
        )
        ws_client.start()
    except Exception as e:
        logger.error("[feishu] 长连接失败: %s", str(e))
    finally:
        loop.close()


def start_event_listener():
    """启动飞书 WebSocket 长连接（独立线程 + 独立事件循环）"""
    logger.info("[feishu] 启动 WebSocket 长连接...")
    t = threading.Thread(target=_run_ws_loop, daemon=True)
    t.start()
