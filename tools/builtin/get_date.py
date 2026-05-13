"""获取当前日期和时间工具"""
from datetime import datetime, timezone, timedelta

# 上海时区 UTC+8
_CST = timezone(timedelta(hours=8))


async def get_date() -> dict:
    """获取当前北京时间（年、月、日、时、分、星期）"""
    now = datetime.now(_CST)
    weekday_cn = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]

    return {
        "date": now.strftime("%Y-%m-%d"),
        "date_cn": now.strftime("%Y年%m月%d日"),
        "time": now.strftime("%H:%M:%S"),
        "weekday": weekday_cn[now.weekday()],
        "iso": now.isoformat(),
    }


GET_DATE_SCHEMA = {
    "description": "获取当前北京时间，返回日期、时间、星期。搜索时如需限定'最新''最近''今天'等需要获取日期时可使用此工具获取当前时间。",
    "parameters": {
        "type": "object",
        "properties": {},
        "required": [],
    },
}
