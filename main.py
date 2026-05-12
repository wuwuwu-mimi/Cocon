import logging

from fastapi import FastAPI
# 导入 tasks 模块里的 router
from api.tasks import router as tasks_router

# 应用入口配置日志，模块内使用 logging.getLogger(__name__) 获取 logger
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%H:%M:%S",
)

app = FastAPI()

@app.get("/")
async def root():
    return {"message": "Hello World"}

@app.get("/hello/{name}")
async def say_hello(name: str):
    return {"message": f"Hello {name}"}

app.include_router(tasks_router)