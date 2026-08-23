from sqlalchemy.ext.asyncio import create_async_engine,async_sessionmaker,AsyncSession
from sqlalchemy import text
import os

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "mysql+aiomysql://root:123456@localhost/houseprice?charset=utf8mb4"
)

# 异步数据库引擎
async_engine = create_async_engine(
    DATABASE_URL,
    echo=True,     # 打印SQL
    pool_size=10,
    max_overflow=10
)

# 异步会话工厂
AsyncSession_Local = async_sessionmaker(
    bind=async_engine, # 绑定异步引擎
    expire_on_commit=False, # 提交后会话不自动过期，需要手动关闭
    class_=AsyncSession # 使用异步会话类
)

# 异步会话依赖项
async def get_db():
    async with AsyncSession_Local() as session:
        try:
            yield session # 返回会话
            await session.commit() # 提交事务
        except Exception as e:
            await session.rollback() # 回滚事务
            raise e
        finally:
            await session.close() # 关闭会话

async def execute_sql_file(session: AsyncSession, file_path: str):
    with open(file_path, "r", encoding="utf-8") as f:
        sql_script = f.read()
    
    # 按分号分割（注意：SQLite 不支持多条语句一次执行，必须拆分）
    for statement in sql_script.split(";"):
        if statement.strip():
            await session.execute(text(statement))
    await session.commit()

async def create_tables() -> None:
    """自动创建所有不存在的表（幂等，可重复调用）。"""
    from houseprice.model import Base  # 延迟导入，避免循环依赖

    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
