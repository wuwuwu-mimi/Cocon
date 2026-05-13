import asyncio
import logging

from fastapi import FastAPI
from api.tasks import router as tasks_router
from api.feishu import router as feishu_router, start_event_listener
import api.feishu as feishu_module

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%H:%M:%S",
)

app = FastAPI()


@app.on_event("startup")
async def startup():
    """保存主事件循环引用，启动飞书 WebSocket 长连接"""
    feishu_module._main_loop = asyncio.get_running_loop()
    start_event_listener()
    logging.getLogger(__name__).info("飞书长连接已启动")


@app.get("/")
async def root():
    return {"message": "Hello World"}


@app.get("/hello/{name}")
async def say_hello(name: str):
    return {"message": f"Hello {name}"}


app.include_router(tasks_router)
app.include_router(feishu_router)