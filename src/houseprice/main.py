"""FastAPI 应用入口。"""

from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from houseprice.db_config import async_engine, create_tables, get_db
from houseprice.interfaces.report import router as report_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用启动时自动建表，关闭时释放连接池。"""
    await create_tables()
    yield
    await async_engine.dispose()


app = FastAPI(title="houseprice", lifespan=lifespan)

app.include_router(report_router)


@app.get("/health")
async def health(db: AsyncSession = Depends(get_db)) -> dict[str, str]:
    """健康检查：验证服务与数据库连接是否正常。"""
    await db.execute(text("SELECT 1"))
    return {"status": "ok", "database": "connected"}
