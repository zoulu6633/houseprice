"""将爬取到的房源数据写入数据库。

读取抓取的 JSON（字段与 houseprice.model.house.HouseListing 对齐），
按 source_url 作为唯一键 upsert 写入 house_listings 表：已存在则更新，不存在则插入。

用法:
    python -m houseprice.getdata.save                          # 处理 output 目录下全部 JSON
    python -m houseprice.getdata.save --input 其它.json        # 只处理指定文件
"""

from __future__ import annotations

import argparse
import asyncio
import json
from collections import Counter
from datetime import datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from houseprice.db_config import AsyncSession_Local, async_engine, create_tables
from houseprice.model.house import HouseListing

DEFAULT_OUTPUT_DIR = Path(__file__).resolve().parent / "output"


async def save_to_db(data: list[dict]) -> tuple[int, int, bool]:
    """按 source_url upsert 写入 house_listings，返回 (更新条数, 新增条数, 是否写入快照)。

    已存在的房源用本次抓取字段覆盖（first_crawled_at 保持首次抓取时间），
    新出现的房源插入；写入后对本次抓取数据按行政区聚合，落一次区域快照。
    """
    if not data:
        return 0, 0, False

    await create_tables()  # 幂等建表，保证表存在

    urls = [row["source_url"] for row in data]
    async with AsyncSession_Local() as session:
        existing = await session.scalars(
            select(HouseListing).where(HouseListing.source_url.in_(urls))
        )
        existing_by_url = {h.source_url: h for h in existing}

        updated = 0
        for row in data:
            url = row["source_url"]
            if url in existing_by_url:
                house = existing_by_url[url]
                for key, value in row.items():
                    setattr(house, key, value)
                updated += 1
            else:
                session.add(HouseListing(**row))

        new_count = len(data) - updated
        await session.commit()
        snapshot_written = await save_snapshots(session, data)
        return updated, new_count, snapshot_written


async def save_snapshots(session: AsyncSession, data: list[dict]) -> bool:
    """对本次抓取数据按行政区和商圈聚合，写一批区域快照。

    （"每天仅记录一次"的门槛已在本地临时关闭：每次 save 都会落快照，
    便于尽快积累两批快照用于趋势对比。）
    

    统计口径与报告页 services.report_service.aggregate 完全一致，
    便于不同批次间直接对比平均租金与在租数量。
    """
    from houseprice.model.business_district_snapshot import BusinessDistrictSnapshot
    from houseprice.model.district_snapshot import DistrictSnapshot
    from houseprice.services.report_service import aggregate
    
    # # 每天限定一次写入快照
    # today_start = datetime.combine(datetime.now().date(), time.min)
    # already = await session.scalar(
    #     select(DistrictSnapshot.id)
    #     .where(DistrictSnapshot.recorded_at >= today_start)
    #     .limit(1)
    # )
    # if already is not None:
    #     return False

    platform = data[0].get("source_platform", "贝壳租房")
    batch_count = len(data)
    recorded_at = datetime.now()
    rows = [HouseListing(**row) for row in data]

    def make(district: str, items: list[HouseListing]) -> DistrictSnapshot:
        rep = aggregate(items)
        return DistrictSnapshot(
            recorded_at=recorded_at,
            district=district,
            count=rep.count,
            avg_rent=rep.avg_rent,
            median_rent=rep.median_rent,
            avg_area=rep.avg_area,
            batch_count=batch_count,
            source_platform=platform,
        )

    by_district: dict[str, list[HouseListing]] = {}
    for r in rows:
        by_district.setdefault(r.district or "独栋", []).append(r)

    session.add(make("全部", rows))
    session.add_all(make(name, items) for name, items in by_district.items())

    def make_business(name: str, items: list[HouseListing]) -> BusinessDistrictSnapshot:
        rep = aggregate(items)
        # 商圈基本只属于一个行政区，取该商圈房源中出现最多的 district
        district = None
        if items:
            most = Counter(r.district for r in items if r.district).most_common(1)
            district = most[0][0] if most else None
        return BusinessDistrictSnapshot(
            recorded_at=recorded_at,
            district=district,
            business_district=name,
            count=rep.count,
            avg_rent=rep.avg_rent,
            median_rent=rep.median_rent,
            avg_area=rep.avg_area,
            batch_count=batch_count,
            source_platform=platform,
        )

    by_business: dict[str, list[HouseListing]] = {}
    for r in rows:
        if r.business_district:
            by_business.setdefault(r.business_district, []).append(r)

    session.add_all(make_business(name, items) for name, items in by_business.items())
    await session.commit()
    return True


async def main() -> None:
    parser = argparse.ArgumentParser(description="将爬取的房源 JSON 写入数据库")
    parser.add_argument("--input", action="append", default=None,
                        help="输入的 JSON 文件路径，可多次指定；不填则处理 output 目录下全部 JSON")
    args = parser.parse_args()

    if args.input:
        files = [Path(p) for p in args.input]
    else:
        files = sorted(DEFAULT_OUTPUT_DIR.glob("*.json"))
    if not files:
        print(f"未找到 JSON 文件（目录: {DEFAULT_OUTPUT_DIR}）")
        await async_engine.dispose()
        return

    # 合并所有文件为一批，保证行政区/商圈快照综合多文件数据、只落一批
    merged: list[dict] = []
    seen: set[str] = set()
    for file in files:
        with open(file, "r", encoding="utf-8") as f:
            for row in json.load(f):
                if row["source_url"] not in seen:
                    seen.add(row["source_url"])
                    merged.append(row)

    if not merged:
        print("未读取到任何房源数据，退出")
        await async_engine.dispose()
        return

    updated, added, snapshot_written = await save_to_db(merged)
    snapshot_msg = "已记录区域快照" if snapshot_written else "今日已有区域快照，跳过"
    print(f"完成：合并 {len(files)} 个文件共 {len(merged)} 条，"
          f"更新 {updated} 条，新增 {added} 条；{snapshot_msg}")
    await async_engine.dispose()  # 关闭连接池，避免退出时的告警


if __name__ == "__main__":
    asyncio.run(main())
