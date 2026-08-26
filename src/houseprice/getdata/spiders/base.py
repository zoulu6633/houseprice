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
import re
import time
from pathlib import Path
from typing import Callable

try:
    import msvcrt  # Windows 非阻塞键盘检测；其他平台不可用时退化为纯超时等待
except ImportError:  # pragma: no cover - 非 Windows 平台
    msvcrt = None

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

# 筛选条中常见的非选项导航文本（「不限」「全部」等），发现子区域时默认过滤，各平台通用
DEFAULT_FILTER_EXCLUDE_NAMES = {
    "不限", "全部", "全城", "更多", "筛选", "排序", "价格", "户型", "面积", "朝向",
}
# 子区域/商圈链接的默认提取正则：取链接中 zufang/ 后的段（如 ninghailu）；其他平台可传自定义正则覆盖
DEFAULT_BUSINESS_HREF_RE = re.compile(r"/zufang/([a-z0-9]+)/?")


def create_page() -> ChromiumPage:
    """按公共配置启动浏览器（固定用户数据目录以保留登录态）。"""
    co = ChromiumOptions()
    if BROWSER_PATH:
        co.set_browser_path(BROWSER_PATH)
    co.set_user_data_path(str(USER_DATA_PATH))
    return ChromiumPage(co)


# 常见登录页 URL 特征关键词（贝壳/链家登录中心为 passport.ke.com，不含 login 字样，需一并识别）
_LOGIN_URL_KEYWORDS = ("login", "passport", "verify", "captcha", "antibot", "signin")
# 人机验证页 URL 特征关键词（命中时按验证页提示，而非登录页）
_CAPTCHA_URL_KEYWORDS = ("captcha", "verify", "antibot")

# 无人值守模式下，遇到登录/验证码页等待人工处理的最长时间（秒），超时自动跳过
MANUAL_WAIT_TIMEOUT = 120


def _wait_manual(prompt: str, timeout: int = MANUAL_WAIT_TIMEOUT) -> bool:
    """等待人工处理登录/验证码：按回车立即继续，超时自动跳过（无人值守不卡死）。

    返回 True 表示收到回车；False 表示超时（打印提示后继续，不阻塞任务）。
    非 Windows 平台无 msvcrt 时退化为纯超时等待。
    """
    print(prompt)
    if msvcrt is None:
        time.sleep(timeout)
        return False
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if msvcrt.kbhit() and msvcrt.getch() in (b"\r", b"\n"):
            return True
        time.sleep(0.2)
    print(f"[超时] 等待 {timeout} 秒无人处理，跳过本次人工介入，任务继续。")
    return False


def _is_login_page(page: ChromiumPage) -> bool:
    """判断页面是否为登录页：URL 含登录特征关键词，或页面出现密码输入框兜底。"""
    url = page.url.lower()
    if any(k in url for k in _LOGIN_URL_KEYWORDS):
        return True
    try:
        return page.ele("css:input[type='password']", timeout=1) is not None
    except ElementNotFoundError:
        return False


def ensure_loaded(page: ChromiumPage, selector: str, url: str) -> bool:
    """等待页面出现 selector 匹配的元素；被重定向到登录页时提示手动登录并重载。

    最多尝试两次（首次 + 登录重载后）。返回是否成功加载（元素已出现）；
    元素始终未出现且不是登录页时返回 False，由调用方按风控/结构问题处理。
    selector 传 CSS 选择器，内部自动补 css: 前缀。
    """
    css = selector if selector.startswith("css:") else f"css:{selector}"
    for _ in range(2):
        try:
            page.ele(css, timeout=15)
            return True
        except ElementNotFoundError:
            if not _is_login_page(page):
                return False
            if any(k in page.url.lower() for k in _CAPTCHA_URL_KEYWORDS):
                _wait_manual(
                    f"[提示] 被重定向到人机验证页（{page.url}），\n"
                    "请在弹出的浏览器中完成验证，或等待超时自动跳过。"
                )
            else:
                _wait_manual(
                    f"[提示] 检测到登录页（{page.url}），请登录一次；\n"
                    f"登录态会保存在 {USER_DATA_PATH}，之后无需再登录。\n"
                    "登录完成后按回车继续，或等待超时自动跳过。"
                )
            page.get(url)
    return False


def collect_filter_options(
    page: ChromiumPage,
    url: str,
    link_selector: str,
    code_pattern: re.Pattern,
    *,
    exclude_codes: set[str] | None = None,
    exclude_names: set[str] | None = None,
    name_pattern: str = r"[\u4e00-\u9fa5]{2,10}",
    click_trigger: str | None = None,
    captcha_handler: Callable | None = None,
) -> list[tuple[str, str]]:
    """从页面筛选区收集 (中文名, 代码) 选项，平台通用。

    打开 url 并等待 link_selector 出现（登录页由 ensure_loaded 提示处理），
    收集 href 匹配 code_pattern 的链接：code 取第一个捕获组，中文名取链接文本。
    exclude_codes / exclude_names 命中即跳过（如行政区代码、"不限"等导航词），
    name_pattern 校验中文名（默认 2-10 个纯汉字）。首次收集为空且提供
    click_trigger 时，点击筛选条中该文本元素展开下拉后重试一次。
    captcha_handler: 可选，页面加载后 / 点击展开下拉后各调用一次，用于
        自动处理人机验证（如极验点选）；不传则跳过，行为不变。
    """
    page.get(url)
    if captcha_handler:  # 打开页面即可能触发验证码，先尝试自动通过
        captcha_handler(page)
    ensure_loaded(page, link_selector, url)

    def collect() -> list[tuple[str, str]]:
        found: list[tuple[str, str]] = []
        for a in page.eles(f"css:{link_selector}"):
            m = code_pattern.search(a.attr("href") or "")
            if not m:
                continue
            code = m.group(1)
            name = (a.text or "").strip()
            if (not name or code in (exclude_codes or ())
                    or name in (exclude_names or ())):
                continue
            if re.fullmatch(name_pattern, name) and (name, code) not in found:
                found.append((name, code))
        return found

    options = collect()
    if options:
        return options

    if click_trigger:
        try:
            trigger = page.ele(
                f"xpath://*[contains(@class,'filter')]//*[text()='{click_trigger}']", timeout=3
            )
            if trigger:
                trigger.click()
                page.wait(1.5)
                if captcha_handler:  # 点击展开下拉也可能触发验证码
                    captcha_handler(page)
                options = collect()
        except Exception:
            pass
    return options


class FilterOptionDiscoverer:
    """从页面筛选区发现子区域/商圈选项的爬取器，平台通用。

    与 Spider 同款生命周期管理：实例化时传入平台相关的 URL、选择器与正则，
    run() 内部创建浏览器 -> 打开页面 -> 收集 (中文名, 代码) -> 关闭浏览器，
    调用方无需关心浏览器细节。

    :param url: 子区域列表页（如行政区首页）
    :param link_selector: 筛选区子区域链接的 CSS 选择器
    :param code_pattern: 从 href 提取代码的正则，取第一个捕获组；默认复用
        DEFAULT_BUSINESS_HREF_RE
    :param exclude_codes: 需跳过的代码集合（如行政区代码）
    :param exclude_names: 需跳过的名称集合，默认复用 DEFAULT_FILTER_EXCLUDE_NAMES
    :param click_trigger: 首次收集为空时点击展开下拉的筛选条文本
    :param captcha_handler: 可选，页面加载后 / 点击展开下拉后自动处理人机验证
    """

    def __init__(
        self,
        url: str,
        link_selector: str,
        code_pattern: re.Pattern = DEFAULT_BUSINESS_HREF_RE,
        *,
        exclude_codes: set[str] | None = None,
        exclude_names: set[str] | None = DEFAULT_FILTER_EXCLUDE_NAMES,
        click_trigger: str | None = None,
        captcha_handler: Callable | None = None,
    ) -> None:
        self.url = url
        self.link_selector = link_selector
        self.code_pattern = code_pattern
        self.exclude_codes = exclude_codes
        self.exclude_names = exclude_names
        self.click_trigger = click_trigger
        self.captcha_handler = captcha_handler

    def run(self) -> list[tuple[str, str]]:
        """创建浏览器、打开页面收集选项，返回 [(中文名, 代码), ...]。"""
        page = create_page()
        try:
            return collect_filter_options(
                page, self.url, self.link_selector, self.code_pattern,
                exclude_codes=self.exclude_codes,
                exclude_names=self.exclude_names,
                click_trigger=self.click_trigger,
                captcha_handler=self.captcha_handler,
            )
        finally:
            page.quit()


class Spider:
    """一个平台的分页列表爬取器。

    :param item_selector: 列表项的 CSS 选择器
    :param parse_item: 条目解析函数，输入 ChromiumElement，输出 dict 或 None
    :param page_url: 分页 URL 构造函数 (base_url, 页码) -> str
    :param targets: 目标 base_url 前缀列表（如各区域）；遍历其中的每个抓 pages 页
    :param pages: 每个 target 抓取的页数
    :param captcha_handler: 可选验证码处理函数，输入 ChromiumPage，每页加载后调用；
        用于在等待列表项前自动处理人机验证（如极验点选）
    """

    def __init__(
        self,
        item_selector: str,
        parse_item,
        page_url,
        targets: list[str],
        pages: int,
        captcha_handler: Callable | None = None,
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
        self.captcha_handler = captcha_handler

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
                    if self.captcha_handler:  # 加载后先处理人机验证，再滚动等待列表项
                        self.captcha_handler(page)
                    page.scroll.to_bottom()

                    # 等待列表项出现；若被风控重定向到登录页，提示手动登录
                    if not ensure_loaded(page, self.item_selector, url):
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


def build_output_name(
    platform: str, city: str, districts: list[str] | None,
    business: list[str] | None = None,
) -> str:
    """按「平台代码+行政区/商圈代码」拼接输出文件名，多个以下划线连接；全城用城市代码。

    例: build_output_name("beike", "nj", None, ["ninghailu"])  -> "beike_ninghailu.json"
        build_output_name("beike", "nj", ["gulou", "jianye"]) -> "beike_gulou_jianye.json"
        build_output_name("wuba", "nj", None)                 -> "wuba_nj.json"
    """
    region_parts = list(districts or [])
    region_parts.extend(business or [])
    region = "_".join(region_parts) if region_parts else city
    return f"{platform}_{region}.json"

