"""商圈价格快照 ORM 模型。"""

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Float, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from houseprice.model.base import Base


class BusinessDistrictSnapshot(Base):
    """商圈价格快照表。

    与 district_snapshots 同期写入：每次抓取入库后，对本次抓取数据按商圈
    （business_district）聚合写一行，用于监控各商圈平均租金与在租数量的变化趋势。
    """

    __tablename__ = "business_district_snapshots"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime, index=True, comment="快照时间（同一批次相同）"
    )
    district: Mapped[str | None] = mapped_column(String(50), nullable=True, comment="所属行政区")
    business_district: Mapped[str] = mapped_column(String(50), comment="商圈")
    count: Mapped[int] = mapped_column(Integer, comment="该商圈在租数量")
    avg_rent: Mapped[float | None] = mapped_column(Float, nullable=True, comment="平均月租金（元）")
    median_rent: Mapped[float | None] = mapped_column(Float, nullable=True, comment="中位月租金（元）")
    avg_area: Mapped[float | None] = mapped_column(Float, nullable=True, comment="平均面积（㎡）")
    batch_count: Mapped[int] = mapped_column(Integer, comment="本批抓取总条数（判断抓取规模是否一致）")
    source_platform: Mapped[str] = mapped_column(String(50), comment="来源平台")
