"""把报告渲染成自包含的静态 HTML，用于 GitHub Pages 等静态托管。

用法:
    uv run python -m houseprice.scripts.build_static

复用 services/report_service 的聚合逻辑与 templates/report.html 模板，
生成 docs/index.html；手动更新流程 = 重跑本脚本 → git push。
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from houseprice.db_config import AsyncSession_Local, async_engine
from houseprice.services.report_service import build_price_report, build_report, make_data_json

TEMPLATES_DIR = Path(__file__).resolve().parents[1] / "templates"
OUTPUT_FILE = Path(__file__).resolve().parents[3] / "docs" / "index.html"


async def main() -> None:
    async with AsyncSession_Local() as session:
        data = await build_report(session)
        price = await build_price_report(session)

    env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)), autoescape=True)
    html = env.get_template("report.html").render(
        **data,
        price_report=price,
        data_json=make_data_json(data["overall"], data["districts"], price),
    )

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_FILE.write_text(html, encoding="utf-8")
    print(f"已生成 {OUTPUT_FILE}（{len(html) / 1024:.1f} KB）")
    await async_engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
