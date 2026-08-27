"""报告页面路由。"""

from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession

from houseprice.db_config import get_db
from houseprice.services.report_service import build_price_report, build_report, make_data_json

router = APIRouter(tags=["report"])

templates = Jinja2Templates(directory=str(Path(__file__).resolve().parents[1] / "templates"))


@router.get("/")
async def report_page(
    request: Request, db: AsyncSession = Depends(get_db)
) -> "TemplateResponse":
    """渲染按行政区整理的报告仪表盘。"""
    data = await build_report(db)
    price = await build_price_report(db)
    return templates.TemplateResponse(
        request,
        "report.html",
        {
            "request": request,
            **data,
            "price_report": price,
            "data_json": make_data_json(data["overall"], data["districts"], price),
        },
    )
