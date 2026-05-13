from .web_search import web_search, WEB_SEARCH_SCHEMA
from .get_date import get_date,GET_DATE_SCHEMA
BUILTIN_TOOLS_MANIFEST = [
    {
        "name": "web_search",
        "func": web_search,
        "schema": WEB_SEARCH_SCHEMA
    },
    {
        "name": "get_date",
        "func": get_date,
        "schema": GET_DATE_SCHEMA
    }
]
