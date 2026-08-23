"""贝壳租房平台模块（beike_spider.py 的具体实现）。

用法:
    python -m houseprice.getdata.spiders.beike                          # 全城，默认3页
    python -m houseprice.getdata.spiders.beike --pages 5 --city nj      # 全城5页
    python -m houseprice.getdata.spiders.beike --district gulou         # 单个区域
    python -m houseprice.getdata.spiders.beike --all-districts --pages 100  # 遍历全部区域（数据量最大）
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

from houseprice.getdata.spiders.base import DEFAULT_OUTPUT_DIR, Spider, save

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

DEFAULT_OUTPUT = DEFAULT_OUTPUT_DIR / "nanjing_beike.json"


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
        "community_name": parts[-1] if parts else title.strip().lstrip("整租·合租·"),  # 小区名称
        "brand": None,  # 列表页无品牌信息
        "listing_type": title[:2] if title else None,  # 租赁方式取标题前两个字（整租/合租/独栋等，仅记录）
        "layout": search(r"(\d+\s*室\s*\d+\s*厅(?:\s*\d+\s*卫)?)"),  # 户型
        "area": float(search(r"([\d.]+)\s*㎡")) if search(r"([\d.]+)\s*㎡") else None,  # 面积
        "monthly_rent": float(search(r"(\d+)\s*元/月")) if search(r"(\d+)\s*元/月") else None,  # 月租金
        "floor_level": search(r"(低|中|高)\s*楼层"),  # 楼层等级
        "total_floors": int(search(r"共?\s*(\d+)\s*层")) if search(r"共?\s*(\d+)\s*层") else None,  # 总楼层
        "decoration": search(r"(精装|简装|毛坯|豪装)"),  # 装修
        "building_age": None,  # 列表页无建筑年龄
        "source_platform": SOURCE_PLATFORM,
        "source_url": source_url,  # 房源链接（唯一，用于去重）
    }


def crawl(pages: int, city: str, districts: list[str] | None = None) -> list[dict]:
    """抓取贝壳指定城市的分页房源列表，返回跨区域去重后的解析结果。

    districts 传区域代码列表则逐区抓取；传 None 抓全城。
    """
    if districts:
        targets = [f"https://{city}.zu.ke.com/zufang/{d}/" for d in districts]
    else:
        targets = [f"https://{city}.zu.ke.com/zufang/"]
    spider = Spider(item_selector=ITEM_SELECTOR, parse_item=parse_item,
                    page_url=page_url, targets=targets, pages=pages)
    return spider.run()


def fetch_listings(
    pages: int = 3,
    city: str = "nj",
    districts: list[str] | None = None,
    *,
    output: Path | str | None = None,
) -> list[dict]:
    """抓取贝壳房源并返回解析结果；output 传路径时同步保存为 JSON。

    供其他文件调用的便捷入口，例如:
        from houseprice.getdata.spiders.beike import fetch_listings
        data = fetch_listings(pages=5, districts=["gulou", "jianye"])
    """
    results = crawl(pages, city, districts)
    if output is not None:
        save(results, Path(output))
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="贝壳租房爬虫")
    parser.add_argument("--pages", type=int, default=3, help="抓取页数（每页约20条），默认3")
    parser.add_argument("--city", default="nj", help="城市代码，默认 nj（南京）")
    parser.add_argument("--district", default=None,
                        help="区域代码（如 gulou/jianye），不填则抓全城")
    parser.add_argument("--all-districts", action="store_true",
                        help="遍历南京全部区域抓取（突破全城100页上限，数据量最大）")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="输出 JSON 路径")
    args = parser.parse_args()

    if args.all_districts:
        districts = NANJING_DISTRICTS
    elif args.district:
        districts = [args.district]
    else:
        districts = None

    results = crawl(args.pages, args.city, districts)
    save(results, Path(args.output))
    print(f"抓取完成：共 {len(results)} 条，已保存到 {args.output}")


if __name__ == "__main__":
    main()
