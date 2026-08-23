"""报告页聚合统计服务。

数据量不大（数千条），一次查出所需字段后在内存聚合，
避免多条 SQL 与复杂分组语句，逻辑更清晰。
"""

from __future__ import annotations

import json
from statistics import median

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from houseprice.model.house import HouseListing
from houseprice.schemas.report import DistrictReport, ListingItem, RentBucket, TopCommunity

# 租金分档边界（左闭右开）与对应标签，最后一档不限上限
RENT_BUCKET_BOUNDS = [1000, 2000, 3000, 4000, 5000, 7000, 10000]
RENT_BUCKET_LABELS = ["1k以下", "1-2k", "2-3k", "3-4k", "4-5k", "5-7k", "7-10k", "1w+"]


def rent_bucket_label(rent: float) -> str:
    """返回租金所属档位的标签。"""
    for i, upper in enumerate(RENT_BUCKET_BOUNDS):
        if rent < upper:
            return RENT_BUCKET_LABELS[i]
    return RENT_BUCKET_LABELS[-1]


def aggregate(rows: list[HouseListing]) -> DistrictReport:
    """对一批房源做聚合统计，district 字段由调用方补齐。"""
    count = len(rows)
    rents = [r.monthly_rent for r in rows if r.monthly_rent is not None]
    areas = [r.area for r in rows if r.area is not None]

    # 租金区间分布
    bucket_counts: dict[str, int] = {}
    for rent in rents:
        label = rent_bucket_label(rent)
        bucket_counts[label] = bucket_counts.get(label, 0) + 1
    rent_buckets = [
        RentBucket(label=label, count=bucket_counts.get(label, 0))
        for label in RENT_BUCKET_LABELS
    ]

    # 热门小区 TOP10（按房源数降序，同数再按平均租金升序）
    by_community: dict[str, list[float | None]] = {}
    for r in rows:
        by_community.setdefault(r.community_name, []).append(r.monthly_rent)

    def avg_rent(r_rents: list[float | None]) -> float | None:
        valid = [x for x in r_rents if x is not None]
        return round(sum(valid) / len(valid)) if valid else None

    top_communities = [
        TopCommunity(
            community_name=name,
            count=len(r_rents),
            avg_rent=avg_rent(r_rents),
        )
        for name, r_rents in sorted(
            by_community.items(),
            key=lambda kv: (-len(kv[1]), sum(x for x in kv[1] if x is not None)),
        )[:10]
    ]

    listings = [
        ListingItem(
            district=r.district,
            community_name=r.community_name,
            layout=r.layout,
            area=r.area,
            monthly_rent=r.monthly_rent,
            decoration=r.decoration,
            source_url=r.source_url,
        )
        for r in rows
    ]

    return DistrictReport(
        district="",
        count=count,
        avg_rent=round(sum(rents) / len(rents)) if rents else None,
        median_rent=round(median(rents)) if rents else None,
        avg_area=round(sum(areas) / len(areas), 1) if areas else None,
        rent_buckets=rent_buckets,
        top_communities=top_communities,
        listings=listings,
    )


async def build_report(session: AsyncSession) -> dict:
    """读取全部贝壳房源，返回 {overall, districts} 两个聚合结果。"""
    rows = list(
        (
            await session.scalars(
                select(HouseListing).where(HouseListing.source_platform == "贝壳租房")
            )
        ).all()
    )

    overall = aggregate(rows)
    overall.district = "全部"

    by_district: dict[str, list[HouseListing]] = {}
    for r in rows:
        key = r.district or "独栋"
        by_district.setdefault(key, []).append(r)

    districts = []
    for name in sorted(by_district, key=lambda d: len(by_district[d]), reverse=True):
        rep = aggregate(by_district[name])
        rep.district = name
        districts.append(rep)

    return {"overall": overall, "districts": districts}


def make_data_json(overall: DistrictReport, districts: list[DistrictReport]) -> str:
    """生成前端可用的紧凑 JSON：统计与明细分离，明细只存一份。

    listings 为全量扁平数组，前端按 district 过滤渲染，避免各区重复内嵌。
    """
    def stats(rep: DistrictReport) -> dict:
        return {k: v for k, v in rep.model_dump().items() if k != "listings"}

    return json.dumps(
        {
            "overall": stats(overall),
            "districts": [stats(d) for d in districts],
            "listings": [l.model_dump() for l in overall.listings],
        },
        ensure_ascii=False,
    )
