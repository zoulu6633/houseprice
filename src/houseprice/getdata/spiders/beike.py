"""贝壳租房平台模块（beike_spider.py 的具体实现）。

用法:
    python -m houseprice.getdata.spiders.beike                          # 全城，默认3页
    python -m houseprice.getdata.spiders.beike --pages 5 --city nj      # 全城5页
    python -m houseprice.getdata.spiders.beike --district gulou         # 单个区域
    python -m houseprice.getdata.spiders.beike --all-districts --pages 100  # 遍历全部区域（数据量最大）
    python -m houseprice.getdata.spiders.beike --business ninghailu     # 单个商圈（无需行政区前缀）
    python -m houseprice.getdata.spiders.beike --business huaqiaolu hunanlu hanzhongmendaji  # 多个商圈（空格分隔）
    python -m houseprice.getdata.spiders.beike --district gulou --auto-business  # 自动解析商圈并逐商圈抓取（每个商圈一个 JSON）
    python -m houseprice.getdata.spiders.beike --all-districts --auto-business --pages 3  # 遍历全部区域并逐商圈抓取（定时任务全量模式）
"""

from __future__ import annotations

import argparse
import base64
import json
import re
import struct
from pathlib import Path

import requests
from DrissionPage.common import Actions
from DrissionPage.errors import ElementNotFoundError, NoRectError
from houseprice.getdata.spiders.base import (
    DEFAULT_OUTPUT_DIR, FilterOptionDiscoverer, Spider, build_output_name, save,
)

ITEM_SELECTOR = ".content__list--item"
SOURCE_PLATFORM = "贝壳租房"

# 南京行政区白名单：解析出的 district 不在此列说明是营销位/活动卡片等脏数据
VALID_DISTRICTS = {
    "鼓楼", "建邺", "秦淮", "玄武", "雨花台",
    "栖霞", "江宁", "浦口", "六合", "溧水", "高淳",
}

# 南京各区 URL 代码（全城分页约 100 页封顶，按区域拆分可突破上限、抓取更多）
NANJING_DISTRICTS = [
    "gulou", "jianye", "qinhuai", "xuanwu", "yuhuatai",
    "qixia", "jiangning", "pukou", "liuhe", "lishui", "gaochun",
]


def page_url(base: str, i: int) -> str:
    """贝壳分页 URL：第 1 页不带 pg 段，其余为 base + pg{i}/。"""
    return base if i == 1 else f"{base}pg{i}/"


def parse_item(item, target: str | None = None) -> dict | None:
    """把一个列表项解析为 HouseListing 对应字段；无法解析时返回 None。"""
    link = item.ele("css:a[href*='.html']", timeout=0.5)
    if not link:
        return None
    source_url = link.attr("href")  # 详情页链接（含普通房源与公寓/独栋）

    text = item.text  # 整个列表项的文本

    def search(pattern: str) -> str | None:
        m = re.search(pattern, text)
        return m.group(1) if m else None

    # 位置路径，如「浦口-天润城-天润城第十街区」
    m = re.search(r"([\u4e00-\u9fa5]+(?:-[\u4e00-\u9fa5]+){1,})", text)
    parts = m.group(1).split("-") if m else []
    # 营销位/活动卡片会把非区名解析到首位（如「房东直租」「九月开学季」），白名单校验后丢弃
    if parts and parts[0] not in VALID_DISTRICTS:
        return None

    title_ele = item.ele("css:.content__list--item--title a", timeout=0.5)
    title = title_ele.text if title_ele else ""

    return {
        "district": parts[0] if parts else None,  # 行政区（公寓等房源可能缺失）
        "business_district": parts[1] if len(parts) >= 3 else None,  # 商圈（如「浦口-天润城-天润城第十街区」中的天润城）
        "community_name": parts[-1] if parts else title.strip().lstrip("整租·合租·"),  # 小区名称
        "brand": None,  # 列表页无品牌信息
        "listing_type": title[:2] if title else None,  # 租赁方式取标题前两个字（整租/合租/独栋等，仅记录）
        "layout": (search(r"(\d+\s*室\s*\d+\s*厅\s*\d+\s*卫)")  # 户型：优先带卫的完整户型
                   or search(r"(\d+\s*室\s*\d+\s*厅)")),  # 匹配不到再退回 N室M厅
        "area": float(search(r"([\d.]+)\s*㎡")) if search(r"([\d.]+)\s*㎡") else None,  # 面积
        "monthly_rent": float(search(r"(\d+)\s*元/月")) if search(r"(\d+)\s*元/月") else None,  # 月租金
        "floor_level": search(r"(低|中|高)\s*楼层"),  # 楼层等级
        "total_floors": int(search(r"共?\s*(\d+)\s*层")) if search(r"共?\s*(\d+)\s*层") else None,  # 总楼层
        "decoration": search(r"(精装|简装|毛坯|豪装)"),  # 装修
        "source_platform": SOURCE_PLATFORM,
        "source_url": source_url,  # 房源链接（唯一，用于去重）
    }


def crawl(
    pages: int,
    city: str,
    districts: list[str] | None = None,
    business: list[str] | None = None,
) -> list[dict]:
    """抓取贝壳指定城市的分页房源列表，返回跨区域去重后的解析结果。

    区域限定规则（district/business 二选一，不组合）:
        business 传商圈代码 -> https://{city}.zu.ke.com/zufang/{business}/
        district 传行政区代码 -> https://{city}.zu.ke.com/zufang/{district}/
        都不传           -> 全城

    商圈 URL 无需行政区前缀（如 https://nj.zu.ke.com/zufang/ninghailu/ 直接可用）。
    """
    if business:
        targets = [f"https://{city}.zu.ke.com/zufang/{b}/" for b in business]
    elif districts:
        targets = [f"https://{city}.zu.ke.com/zufang/{d}/" for d in districts]
    else:
        targets = [f"https://{city}.zu.ke.com/zufang/"]
    spider = Spider(item_selector=ITEM_SELECTOR, parse_item=parse_item,
                    page_url=page_url, targets=targets, pages=pages,
                    captcha_handler=is_captcha_required)
    return spider.run()


def crawl_split(
    pages: int,
    city: str,
    districts: list[str] | None = None,
    business: list[str] | None = None,
    *,
    output_dir: Path,
) -> int:
    """逐区域抓取并分开保存，每个行政区/商圈一个 JSON，返回总条数。

    全城（districts/business 均为空）时保存为单个城市文件；
    指定多个区域时逐个抓取、各自保存，文件名用对应区域代码
    （如 beike_gulou.json / beike_ninghailu.json）。
    """
    if business:
        targets: list[tuple[list[str] | None, list[str] | None]] = [
            (None, [b]) for b in business
        ]
    elif districts:
        targets = [([d], None) for d in districts]
    else:
        targets = [(None, None)]

    total = 0
    for ds, bs in targets:
        data = crawl(pages, city, ds, bs)
        output = output_dir / build_output_name("beike", city, ds, bs)
        save(data, output)
        print(f"已保存 {output}（{len(data)} 条）")
        total += len(data)
    return total


def crawl_district_businesses(
    pages: int, city: str, district: str, *, output_dir: Path,
) -> int:
    """自动解析指定行政区的各商圈，逐商圈抓取并分开保存，返回总条数。

    商圈来源：复用 base.FilterOptionDiscoverer 打开区首页，从筛选区解析商圈链接
    （链接提取正则与非选项过滤规则使用 base 默认值），每个商圈保存一个 JSON。
    """
    businesses = FilterOptionDiscoverer(
        f"https://{city}.zu.ke.com/zufang/{district}/",
        "ul[data-target='area'] a[href*='/zufang/']",
        exclude_codes=set(NANJING_DISTRICTS) | {city, district},
        click_trigger="商圈",
        captcha_handler=is_captcha_required,
    ).run()

    if not businesses:
        print(f"[警告] 未能从 {city}/{district} 页面解析出商圈，"
              "请确认页面结构或改用 --business 手动指定商圈")
        return 0

    print(f"发现 {district} 商圈 {len(businesses)} 个：{', '.join(n for n, _ in businesses)}")
    return crawl_split(pages, city, business=[code for _, code in businesses],
                       output_dir=output_dir)


def crawl_all_district_businesses(pages: int, city: str, *, output_dir: Path) -> int:
    """遍历南京全部行政区，逐区自动解析商圈并逐商圈抓取，返回总条数。

    等价于对 NANJING_DISTRICTS 逐个执行 --district d --auto-business，
    供定时编排脚本全量抓取使用；每个商圈保存一个 JSON。
    """
    total = 0
    for district in NANJING_DISTRICTS:
        print(f"—— [{district}] 解析商圈并抓取 ——")
        total += crawl_district_businesses(pages, city, district, output_dir=output_dir)
    return total


def fetch_listings(
    pages: int = 3,
    city: str = "nj",
    districts: list[str] | None = None,
    business: list[str] | None = None,
    *,
    output: Path | str | None = None,
) -> list[dict]:
    """抓取贝壳房源并返回解析结果；output 传路径时同步保存为 JSON。

    供其他文件调用的便捷入口，例如:
        from houseprice.getdata.spiders.beike import fetch_listings
        data = fetch_listings(pages=5, districts=["gulou", "jianye"])
        data = fetch_listings(pages=5, business=["ninghailu"])
    """
    results = crawl(pages, city, districts, business)
    if output is not None:
        save(results, Path(output))
    return results


def get_code(bg_base64: str) -> list[dict] | None:
    """调用打码平台识别点选验证码，返回点击坐标列表；识别失败返回 None。"""
    if not bg_base64:
        print("[警告] 未提供验证码背景图base64编码，无法识别")
        return None
    data_1={
        "image": bg_base64,
        "token": "sL1xsiLxFGB5qHuU4l6VTIWbej3gTG_om2c_xaDAHfU",
        "type": "88888",
    }
    # data_2={
    #     "image": bg_base64,
    #     "extra": "je4_phrase",
    #     "token": "sL1xsiLxFGB5qHuU4l6VTIWbej3gTG_om2c_xaDAHfU",
    #     "type": "30114",
    # }
    # data_3={
    #     "image": bg_base64,
    #     "extra": "icon",
    #     "token": "sL1xsiLxFGB5qHuU4l6VTIWbej3gTG_om2c_xaDAHfU",
    #     "type": "30105",
    # }
    _headers = {"Content-Type": "application/json"}
    link = "http://api.jfbym.com/api/YmServer/customApi"

    # 依次尝试三种类型，前一个识别失败（接口报错或坐标无效）时用 else 换下一个
    try:
        # timeout=(连接超时, 读取超时)，避免 DNS/网络异常时长时间卡住
        response = requests.post(link, headers=_headers, json=data_1).json()
    except requests.RequestException as e:  # 网络异常（DNS/超时/断连）不崩溃
        print(f"[警告] 打码接口请求超时 （type={data_1['type']}）：{e}")
        return None
    if response.get("code") == 10000:
        data = response.get("data") or {}
        # 兼容 data.data 与 data 直接放结果的两种结构，避免 KeyError
        coords = data.get("data") if isinstance(data, dict) else data
        if coords:
            return coords
    else:
        print(f"[警告] 打码失败（type={data_1['type']}）：{response.get('msg')}")

    # response = requests.post(link, headers=_headers, json=data_2).json()
    # if response.get("code") == 10000:
    #     coords = response["data"]["data"]
    #     if coords:
    #         return coords
    # else:
    #     print(f"[警告] 打码失败（type={data_2['type']}）：{response.get('msg')}")

    # response = requests.post(link, headers=_headers, json=data_3).json()
    # if response.get("code") == 10000:
    #     coords = response["data"]["data"]
    #     if coords:
    #         return coords
    # else:
    #     print(f"[警告] 打码失败（type={data_3['type']}）：{response.get('msg')}")
    return None



def is_captcha_required(dp) -> bool:
    """检测并尝试自动通过极验人机验证，返回 True 表示页面出现了验证码。

    出现「点击按钮开始验证」时点击启动，对弹出的点选背景图截图并调用
    get_code() 识别坐标，逐个点击后点「确定」提交。页面（含已跳转到验证
    页的情况）找不到验证按钮时返回 False，由 ensure_loaded 按登录墙兜底。
    """
    # 不按 URL 提前返回：验证页若带验证按钮仍继续尝试自动通过；
    # 无验证控件时返回 False，ensure_loaded 仍能识别验证页并提示手动处理
    # 注意：ele() 找不到时返回 NoneElement（不抛异常），须用布尔判断而非 except
    btn = dp.ele("css:.geetest_btn_click", timeout=2)
    if not btn:  # 页面未出现「点击按钮开始验证」，本次无需处理
        return False
    btn.click()
    print("点击验证按钮")
    dp.wait(2)
    # 对验证码背景图 .geetest_box 截图（当前验证页的样式）
    img = dp.ele("css:.geetest_box", timeout=3)
    if not img:
        print("[警告] 未找到验证码背景图，请确认是否已点击开始验证")
        return True

    shot_b64 = img.get_screenshot(as_base64=True)

    result = get_code(shot_b64)
    if not result:  # 网络异常/识别失败返回 None 时不崩溃
        print("[警告] 打码未返回坐标，验证码未通过，可能需要人工处理")
        return True
    
    x_y_list = result.split("|")
    print(x_y_list)
    # 打码坐标基于截图（设备像素），move_to 的 offset 是 CSS 像素，
    # 需按「截图尺寸 / 元素 CSS 尺寸」换算，否则显示器缩放非 100% 时会点偏
    img = dp.ele("css:.geetest_box", timeout=2)  # 重新定位，避免截图后面板重渲染致引用失效
    if not img:
        print("[警告] 验证码面板已消失，无法换算点击坐标")
        return True
    shot_w, shot_h = struct.unpack(">II", base64.b64decode(shot_b64)[16:24])
    css_w, css_h = img.run_js("return [this.offsetWidth, this.offsetHeight];")
    if not shot_w or not shot_h or not css_w or not css_h:
        print("[警告] 截图或元素尺寸异常，无法换算点击坐标")
        return True
    scale_x, scale_y = shot_w / css_w, shot_h / css_h
    ac = Actions(dp)
    for x_y in x_y_list:
        x, y = (int(v) for v in x_y.split(","))
        # 面板可能二次渲染使 img 引用失效（无位置及大小），点击前重新定位并对 NoRectError 重试
        for _ in range(3):
            img = dp.ele("css:.geetest_box", timeout=2)
            if img:
                try:
                    ac.move_to(img, offset_x=x / scale_x, offset_y=y / scale_y).click()
                    break
                except NoRectError:
                    dp.wait(0.5)
        dp.wait(0.4)  # 留出点击间隔，避免过快被风控
    confirm_btn = dp.ele("text=确定", timeout=5)
    if confirm_btn:
        confirm_btn.click()
    else:
        print("[警告] 未找到「确定」按钮，可能已自动提交")
    return True
        


def main() -> None:
    parser = argparse.ArgumentParser(description="贝壳租房爬虫")
    parser.add_argument("--pages", type=int, default=3, help="抓取页数（每页约20条），默认3")
    parser.add_argument("--city", default="nj", help="城市代码，默认 nj（南京）")
    parser.add_argument("--district", default=None,
                        help="区域代码（如 gulou/jianye），不填则抓全城")
    parser.add_argument("--business", nargs="+", default=None,
                        help="商圈代码，可多个（如 ninghailu），无需行政区前缀；"
                             "与 --district/--all-districts 二选一")
    parser.add_argument("--all-districts", action="store_true",
                        help="遍历南京全部区域抓取（突破全城100页上限，数据量最大）")
    parser.add_argument("--auto-business", action="store_true",
                        help="配合 --district 自动解析该行政区商圈并逐商圈抓取（每个商圈一个 JSON）")
    parser.add_argument("--output", default=None,
                        help="输出目录（默认 getdata/output；每个行政区/商圈各保存一个 JSON）")
    args = parser.parse_args()

    if args.business and (args.district or args.all_districts):
        parser.error("--business 与 --district / --all-districts 不能同时使用")
    if args.auto_business and args.business:
        parser.error("--auto-business 与 --business 不能同时使用")
    if args.auto_business and not (args.district or args.all_districts):
        parser.error("--auto-business 需要配合 --district 或 --all-districts 指定行政区")

    if args.auto_business:
        output_dir = Path(args.output) if args.output else DEFAULT_OUTPUT_DIR
        if args.all_districts:
            total = crawl_all_district_businesses(
                args.pages, args.city, output_dir=output_dir
            )
        else:
            total = crawl_district_businesses(
                args.pages, args.city, args.district, output_dir=output_dir
            )
        print(f"抓取完成：共 {total} 条，已按商圈分开保存到 {output_dir}")
        return

    if args.all_districts:
        districts = NANJING_DISTRICTS
    elif args.district:
        districts = [args.district]
    else:
        districts = None
    business = args.business

    output_dir = Path(args.output) if args.output else DEFAULT_OUTPUT_DIR
    total = crawl_split(args.pages, args.city, districts, business, output_dir=output_dir)
    print(f"抓取完成：共 {total} 条，已保存到 {output_dir}")


if __name__ == "__main__":
    main()


#<div class="geetest_btn_click_7b6ceeba geetest_btn_click" aria-label="点击按钮开始验证" tabindex="0"></div>

#<div class="geetest_bg_7b6ceeba geetest_bg" style="background-image: url(&quot;https://static.geetest.com/captcha_v4/policy/68030fa7053b4d6ab4f9baf04438a54b/phrase/296064/2026-08-24T15/76d05b9461a743f6b5b3cd4aa969002f.jpg&quot;);"><div class="geetest_square_mark geetest_mark_show" style="left: 86.593%; top: 20.745%;"><div class="geetest_mark_no">1</div></div></div>
