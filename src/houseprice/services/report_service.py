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
from houseprice.schemas.report import (
    BusinessTrend, DistrictReport, DistrictTrend, ListingItem, RentBucket, TopCommunity,
)

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
            business_district=r.business_district,
            community_name=r.community_name,
            layout=r.layout,
            listing_type=r.listing_type,
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


async def build_price_report(session: AsyncSession) -> dict:
    """对比最近两批区域快照，返回各行政区/商圈环比与全城租金走势。

    返回结构:
        has_data: 是否已有至少两批行政区快照
        current_at / last_at: 本次/上次快照时间（"%Y-%m-%d %H:%M"）
        trends: list[dict]，各区环比（DistrictTrend），固定顺序（"全部"在前 + 字典序）
        business_trends: list[dict]，各商圈环比（BusinessTrend），按租金变化率降序
        series: list[dict]，全城平均租金走势（date / avg_rent / count）
    """
    from houseprice.model.business_district_snapshot import BusinessDistrictSnapshot
    from houseprice.model.district_snapshot import DistrictSnapshot

    batch_times = list(
        (
            await session.scalars(
                select(DistrictSnapshot.recorded_at)
                .distinct()
                .order_by(DistrictSnapshot.recorded_at.desc())
                .limit(2)
            )
        ).all()
    )
    if len(batch_times) < 2:
        return {
            "has_data": False, "current_at": None, "last_at": None,
            "trends": [], "business_trends": [], "series": [],
        }

    last_at, current_at = batch_times[1], batch_times[0]

    async def map_snapshots(model, at, key_attr: str) -> dict:
        return {
            getattr(s, key_attr): s
            for s in (
                await session.scalars(
                    select(model).where(model.recorded_at == at)
                )
            ).all()
        }

    def pairwise_trends(
        last_map, current_map, model, name_field,
        district_attr: str | None = None, sort_by_pct: bool = False,
    ) -> list:
        """对比两批快照 map，产出环比列表（两批都需存在才计入）。

        默认按固定顺序（"全部"在前 + 名称字典序）；sort_by_pct=True 时按涨跌幅降序。
        district_attr 指定时从快照对象取行政区归属（用于商圈快照）。
        """
        trends = []
        for name in sorted(set(last_map) | set(current_map), key=lambda d: (d != "全部", d)):
            cur = current_map.get(name)
            last = last_map.get(name)
            if cur is None or last is None:
                continue  # 两批都需存在才有环比
            rent_delta = (
                round(cur.avg_rent - last.avg_rent)
                if cur.avg_rent is not None and last.avg_rent is not None
                else None
            )
            rent_delta_pct = (
                round(rent_delta / last.avg_rent * 100, 1)
                if rent_delta is not None and last.avg_rent
                else None
            )
            kwargs = {
                name_field: name,
                "last_count": last.count,
                "current_count": cur.count,
                "count_delta": cur.count - last.count,
                "last_avg_rent": last.avg_rent,
                "current_avg_rent": cur.avg_rent,
                "rent_delta": rent_delta,
                "rent_delta_pct": rent_delta_pct,
                "last_avg_area": last.avg_area,
                "current_avg_area": cur.avg_area,
            }
            if district_attr:
                # 行政区归属优先取本次快照（历史批次可能未记录 district，取不到时回退上次）
                kwargs["district"] = (
                    getattr(cur, district_attr, None) or getattr(last, district_attr, None)
                )
            trends.append(model(**kwargs))
        if sort_by_pct:
            # 涨价显著的排前面（无涨跌幅数据排最后）
            trends.sort(key=lambda t: (t.rent_delta_pct is None, -(t.rent_delta_pct or 0)))
        return trends

    last_map = await map_snapshots(DistrictSnapshot, last_at, "district")
    current_map = await map_snapshots(DistrictSnapshot, current_at, "district")
    trends = pairwise_trends(last_map, current_map, DistrictTrend, "district")

    # 商圈环比：独立取最近两批（商圈表可能晚于行政区表启用，批次更少）
    business_trends: list[BusinessTrend] = []
    biz_times = list(
        (
            await session.scalars(
                select(BusinessDistrictSnapshot.recorded_at)
                .distinct()
                .order_by(BusinessDistrictSnapshot.recorded_at.desc())
                .limit(2)
            )
        ).all()
    )
    if len(biz_times) >= 2:
        biz_last, biz_current = biz_times[1], biz_times[0]
        last_biz = await map_snapshots(BusinessDistrictSnapshot, biz_last, "business_district")
        current_biz = await map_snapshots(BusinessDistrictSnapshot, biz_current, "business_district")
        business_trends = pairwise_trends(
            last_biz, current_biz, BusinessTrend, "business_district",
            district_attr="district", sort_by_pct=True,
        )

    series = [
        {"date": s.recorded_at.strftime("%m-%d"), "avg_rent": s.avg_rent, "count": s.count}
        for s in (
            await session.scalars(
                select(DistrictSnapshot)
                .where(DistrictSnapshot.district == "全部")
                .order_by(DistrictSnapshot.recorded_at.asc())
            )
        ).all()
    ]

    return {
        "has_data": True,
        "current_at": current_at.strftime("%Y-%m-%d %H:%M"),
        "last_at": last_at.strftime("%Y-%m-%d %H:%M"),
        "trends": [t.model_dump() for t in trends],
        "business_trends": [t.model_dump() for t in business_trends],
        "series": series,
    }


def make_data_json(
    overall: DistrictReport, districts: list[DistrictReport], price_report: dict | None = None
) -> str:
    """生成前端可用的紧凑 JSON：统计与明细分离，明细只存一份。

    listings 为全量扁平数组，前端按 district 过滤渲染，避免各区重复内嵌。
    price_report 为价格监控数据，随报告一并下发。
    """
    def stats(rep: DistrictReport) -> dict:
        return {k: v for k, v in rep.model_dump().items() if k != "listings"}

    payload: dict = {
        "overall": stats(overall),
        "districts": [stats(d) for d in districts],
        "listings": [l.model_dump() for l in overall.listings],
    }
    if price_report:
        payload["price"] = price_report
    return json.dumps(payload, ensure_ascii=False)
