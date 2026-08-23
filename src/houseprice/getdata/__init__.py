"""数据采集模块。

统一导出爬虫接口，供其他文件调用:
    from houseprice.getdata import fetch_listings
"""

__all__ = ["crawl", "fetch_listings", "save"]


def __getattr__(name: str):
    """惰性导入 spiders.beike，避免包导入时加载浏览器依赖，也不影响 python -m 执行。"""
    if name in __all__:
        from houseprice.getdata.spiders import beike

        return getattr(beike, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
