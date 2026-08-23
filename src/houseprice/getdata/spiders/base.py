"""多平台爬虫公共基础设施（平台无关）。

提供：浏览器启动（含登录态持久化）、分页循环、登录墙处理、跨页去重、JSON 保存。

平台模块只需提供三样东西：
    1. 列表项 CSS 选择器（item_selector）
    2. 条目解析函数（parse_item，输入 ChromiumElement，输出字段 dict 或 None）
    3. 分页 URL 构造函数（page_url，输入 (base_url, 页码)，输出完整 URL）

用法示例见 spiders/beike.py。
"""

from __future__ import annotations

import json
import random
import time
from pathlib import Path

from DrissionPage import ChromiumOptions, ChromiumPage
from DrissionPage.errors import ElementNotFoundError

# 项目根目录（本文件位于 src/houseprice/getdata/spiders/base.py，向上 4 级）
PROJECT_ROOT = Path(__file__).resolve().parents[4]

# 本机浏览器路径（Chrome 未安装则用 Edge；装了 Chrome 可替换，或直接留空让库自动查找）
BROWSER_PATH = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"

# 浏览器用户数据目录：持久化登录态（Cookie），首次登录后无需每次重新登录
USER_DATA_PATH = PROJECT_ROOT / ".browser_profile"

# 各平台 JSON 的默认输出目录（getdata/output）
DEFAULT_OUTPUT_DIR = Path(__file__).resolve().parents[1] / "output"


def create_page() -> ChromiumPage:
    """按公共配置启动浏览器（固定用户数据目录以保留登录态）。"""
    co = ChromiumOptions()
    if BROWSER_PATH:
        co.set_browser_path(BROWSER_PATH)
    co.set_user_data_path(str(USER_DATA_PATH))
    return ChromiumPage(co)


class Spider:
    """一个平台的分页列表爬取器。

    :param item_selector: 列表项的 CSS 选择器
    :param parse_item: 条目解析函数，输入 ChromiumElement，输出 dict 或 None
    :param page_url: 分页 URL 构造函数 (base_url, 页码) -> str
    :param targets: 目标 base_url 前缀列表（如各区域）；遍历其中的每个抓 pages 页
    :param pages: 每个 target 抓取的页数
    """

    def __init__(
        self,
        item_selector: str,
        parse_item,
        page_url,
        targets: list[str],
        pages: int,
    ) -> None:
        # 显式 css: 前缀更稳妥：DrissionPage 4.1.x 下不带前缀的类选择器
        # 在部分站点（如 58 同城）会匹配不到列表项
        self.item_selector = (
            item_selector if str(item_selector).startswith("css:") else f"css:{item_selector}"
        )
        self.parse_item = parse_item
        self.page_url = page_url
        self.targets = targets
        self.pages = pages

    def run(self, page: ChromiumPage | None = None) -> list[dict]:
        """执行抓取，返回跨 target 去重后的解析结果列表。"""
        results: list[dict] = []
        seen: set[str] = set()
        own_page = page is None
        page = page or create_page()

        try:
            for target in self.targets:
                for i in range(1, self.pages + 1):
                    url = self.page_url(target, i)
                    page.get(url)
                    page.scroll.to_bottom()

                    # 等待列表项出现；若被风控重定向到登录页，提示手动登录
                    try:
                        first = page.ele(self.item_selector, timeout=15)
                    except ElementNotFoundError:
                        first = None
                    if not first and "login" in page.url:
                        print(
                            f"[提示] 检测到登录页（{page.url}），请登录一次；"
                            f"登录态会保存在 {USER_DATA_PATH}，之后无需再登录。"
                        )
                        input("登录完成后按回车继续...")
                        page.get(url)
                        try:
                            first = page.ele(self.item_selector, timeout=15)
                        except ElementNotFoundError:
                            first = None
                    if not first:
                        print(f"[警告] 第 {i} 页未解析到房源，可能被风控，跳过。URL: {url}")
                        continue

                    for item in page.eles(self.item_selector):
                        data = self.parse_item(item, target)
                        if data and data["source_url"] not in seen:
                            seen.add(data["source_url"])
                            results.append(data)

                    print(f"第 {i} 页完成，累计 {len(results)} 条")
                    time.sleep(random.uniform(2, 5))  # 随机休眠，降低风控概率
        finally:
            if own_page:
                page.quit()

        return results


def save(results: list[dict], output: Path) -> None:
    """把结果列表写入 JSON 文件。"""
    output.parent.mkdir(parents=True, exist_ok=True)
    with open(output, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
