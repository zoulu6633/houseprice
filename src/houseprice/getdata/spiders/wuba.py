"""58同城租房平台模块。

用法:
    python -m houseprice.getdata.spiders.wuba --pages 5          # 南京全城5页
    python -m houseprice.getdata.spiders.wuba --district gulou   # 单个区域

注意：58 同城反爬较激进，页面结构与贝壳不同（列表项为 .house-cell，
分页第 1 页不带页码段、详情链接为 .shtml），本模块已按真实页面适配。
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

from houseprice.getdata.spiders.base import (
    DEFAULT_OUTPUT_DIR, Spider, build_output_name, save,
)

# 列表项选择器（58 租房常见结构为 .house-cell，若解析为空请按实际页面调整）
ITEM_SELECTOR = ".house-cell"
SOURCE_PLATFORM = "58同城"

# 南京各区：CLI 代码（与贝壳一致） -> (58 链接段, 中文行政区)
# 58 的区域链接段与贝壳并不完全相同，且列表项文本中不含行政区，需由区域 URL 推断。
DISTRICT_ALIAS = {
    "gulou": ("gulouqu", "鼓楼"),
    "jianye": ("jianye", "建邺"),
    "qinhuai": ("qinhuai", "秦淮"),
    "xuanwu": ("xuanwuqu", "玄武"),
    "yuhuatai": ("yuhuatai", "雨花台"),
    "qixia": ("qixiaqu", "栖霞"),
    "jiangning": ("jiangning", "江宁"),
    "pukou": ("pukouqu", "浦口"),
    "liuhe": ("liuhequ", "六合"),
    "lishui": ("lishuixian", "溧水"),
    "gaochun": ("gaochunxian", "高淳"),
}
NANJING_DISTRICTS = list(DISTRICT_ALIAS)


def page_url(base: str, i: int) -> str:
    """58 分页 URL：第 1 页不带页码段，其余为 base + pn{i}/。"""
    return base if i == 1 else f"{base}pn{i}/"


def parse_item(item, target: str | None = None) -> dict | None:
    """把一个列表项解析为 HouseListing 对应字段；无法解析时返回 None。"""
    title_ele = item.ele("css:.des h2 a", timeout=0.5)
    if not title_ele:
        return None
    source_url = title_ele.attr("href")  # 详情页链接（.shtml）
    title = (title_ele.text or "").strip()

    text = item.text  # 整个列表项的文本

    def search(pattern: str) -> str | None:
        m = re.search(pattern, text)
        return m.group(1) if m else None

    # 位置：.infor 下的链接，第一个是商圈、最后一个是小区名
    community_name = None
    infor_links = item.eles("css:.infor a", timeout=0.5)
    if infor_links:
        community_name = (infor_links[-1].text or "").strip() or None

    return {
        "district": _district_from_target(target),  # 列表项不含行政区，由区域 URL 推断
        "community_name": community_name or title,  # 小区名称
        "brand": None,
        # 58 整租/合租是不同频道（/zufang/、/hezu/），标题前两字并非租赁方式
        "listing_type": "合租" if target and "/hezu/" in target else "整租",
        "layout": search(r"(\d+\s*室(?:\s*\d+\s*厅)?(?:\s*\d+\s*卫)?)"),  # 58 常只有「2室」无厅
        "area": float(search(r"([\d.]+)\s*㎡")) if search(r"([\d.]+)\s*㎡") else None,  # 面积
        "monthly_rent": float(search(r"(\d+)\s*元/月")) if search(r"(\d+)\s*元/月") else None,  # 月租金
        "floor_level": search(r"(低|中|高)\s*楼层"),  # 楼层等级
        "total_floors": int(search(r"共?\s*(\d+)\s*层")) if search(r"共?\s*(\d+)\s*层") else None,  # 总楼层
        "decoration": search(r"(精装|简装|毛坯|豪装)"),  # 装修
        "source_platform": SOURCE_PLATFORM,
        "source_url": source_url,  # 房源链接（唯一，用于去重）
    }


def _district_from_target(target: str | None) -> str | None:
    """从区域列表 URL（如 https://nj.58.com/gulouqu/zufang/）反推中文行政区。"""
    if not target:
        return None
    m = re.search(r"58\.com/([^/]+)/zufang/", target)
    if not m:
        return None
    for _code, (url_seg, name) in DISTRICT_ALIAS.items():
        if url_seg == m.group(1):
            return name
    return None


def crawl(pages: int, city: str, districts: list[str] | None = None) -> list[dict]:
    """抓取 58 指定城市的分页房源列表，返回跨区域去重后的解析结果。"""
    if districts:
        targets = [f"https://{city}.58.com/{DISTRICT_ALIAS[d][0]}/zufang/" for d in districts]
    else:
        targets = [f"https://{city}.58.com/zufang/"]
    spider = Spider(item_selector=ITEM_SELECTOR, parse_item=parse_item,
                    page_url=page_url, targets=targets, pages=pages)
    return spider.run()


def main() -> None:
    parser = argparse.ArgumentParser(description="58同城租房爬虫")
    parser.add_argument("--pages", type=int, default=3, help="抓取页数（每页约40条），默认3")
    parser.add_argument("--city", default="nj", help="城市代码，默认 nj（南京）")
    parser.add_argument("--district", default=None,
                        help="区域代码（如 gulou/jianye），不填则抓全城")
    parser.add_argument("--all-districts", action="store_true",
                        help="遍历南京全部区域抓取")
    parser.add_argument("--output", default=None,
                        help="输出 JSON 路径（默认按 平台代码+行政区代码 自动命名）")
    args = parser.parse_args()

    if args.all_districts:
        districts = NANJING_DISTRICTS
    elif args.district:
        districts = [args.district]
    else:
        districts = None

    output = (Path(args.output) if args.output
              else DEFAULT_OUTPUT_DIR / build_output_name("wuba", args.city, districts))
    results = crawl(args.pages, args.city, districts)
    save(results, output)
    print(f"抓取完成：共 {len(results)} 条，已保存到 {output}")


if __name__ == "__main__":
    main()
