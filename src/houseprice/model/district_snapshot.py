"""区域价格快照 ORM 模型。"""

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Float, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from houseprice.model.base import Base


class DistrictSnapshot(Base):
    """区域价格快照表。

    每次抓取入库后，对本次抓取数据按行政区聚合写一行（含"全部"代表全城），
    用于监控各区平均租金与在租数量的变化趋势。
    """

    __tablename__ = "district_snapshots"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime, index=True, comment="快照时间（同一批次相同）"
    )
    district: Mapped[str] = mapped_column(String(50), comment="行政区（全部 表示全城）")
    count: Mapped[int] = mapped_column(Integer, comment="该区在租数量")
    avg_rent: Mapped[float | None] = mapped_column(Float, nullable=True, comment="平均月租金（元）")
    median_rent: Mapped[float | None] = mapped_column(Float, nullable=True, comment="中位月租金（元）")
    avg_area: Mapped[float | None] = mapped_column(Float, nullable=True, comment="平均面积（㎡）")
    batch_count: Mapped[int] = mapped_column(Integer, comment="本批抓取总条数（判断抓取规模是否一致）")
    source_platform: Mapped[str] = mapped_column(String(50), comment="来源平台")
