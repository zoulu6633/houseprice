"""将爬取到的房源数据写入数据库。

读取抓取的 JSON（字段与 houseprice.model.house.HouseListing 对齐），
按 source_url 去重后批量写入 house_listings 表。

用法:
    python -m houseprice.getdata.save                          # 默认读取 output/nanjing_beike.json
    python -m houseprice.getdata.save --input 其它.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from sqlalchemy import select

from houseprice.db_config import AsyncSession_Local, async_engine, create_tables
from houseprice.model.house import HouseListing

DEFAULT_INPUT = Path(__file__).resolve().parent / "output" / "nanjing_beike.json"


async def save_to_db(data: list[dict]) -> tuple[int, int]:
    """按 source_url 去重写入 house_listings，返回 (跳过条数, 新增条数)。"""
    if not data:
        return 0, 0

    await create_tables()  # 幂等建表，保证表存在

    urls = [row["source_url"] for row in data]
    async with AsyncSession_Local() as session:
        existing = set(
            await session.scalars(
                select(HouseListing.source_url).where(HouseListing.source_url.in_(urls))
            )
        )
        new_rows = [
            HouseListing(**row) for row in data if row["source_url"] not in existing
        ]
        session.add_all(new_rows)
        await session.commit()
        return len(existing), len(new_rows)


async def main() -> None:
    parser = argparse.ArgumentParser(description="将爬取的房源 JSON 写入数据库")
    parser.add_argument("--input", default=str(DEFAULT_INPUT), help="输入的 JSON 文件路径")
    args = parser.parse_args()

    with open(args.input, "r", encoding="utf-8") as f:
        data = json.load(f)

    skipped, added = await save_to_db(data)
    print(f"完成：共 {len(data)} 条，跳过已存在 {skipped} 条，新增 {added} 条")
    await async_engine.dispose()  # 关闭连接池，避免退出时的告警


if __name__ == "__main__":
    asyncio.run(main())
