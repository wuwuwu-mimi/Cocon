from fastapi import FastAPI
# 导入 tasks 模块里的 router
from api.tasks import router as tasks_router

app = FastAPI()

@app.get("/")
async def root():
    return {"message": "Hello World"}

@app.get("/hello/{name}")
async def say_hello(name: str):
    return {"message": f"Hello {name}"}

app.include_router(tasks_router)