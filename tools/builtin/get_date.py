"""获取当前日期工具"""
from datetime import datetime, timezone, timedelta

_CST = timezone(timedelta(hours=8))


async def get_date() -> dict:
    """返回当前北京时间"""
    now = datetime.now(_CST)
    return {
        "date": now.strftime("%Y-%m-%d"),
        "date_cn": now.strftime("%Y年%m月%d日"),
    }


GET_DATE_SCHEMA = {
    "description": "获取当前北京时间（YYYY-MM-DD格式）",
    "parameters": {
        "type": "object",
        "properties": {},
        "required": [],
    },
}
