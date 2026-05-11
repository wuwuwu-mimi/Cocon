from .web_search import web_search, WEB_SEARCH_SCHEMA

BUILTIN_TOOLS_MANIFEST = [
    {
        "name": "web_search",
        "func": web_search,
        "schema": WEB_SEARCH_SCHEMA
    },
]
