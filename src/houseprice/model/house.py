"""房源信息 ORM 模型。"""

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Float, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from houseprice.model.base import Base


class HouseListing(Base):
    """房源信息表。

    对应抓取的房源基础字段。
    """

    __tablename__ = "house_listings"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    district: Mapped[str | None] = mapped_column(String(50), index=True, nullable=True, comment="行政区（公寓等房源可能缺失）")
    community_name: Mapped[str] = mapped_column(String(100), comment="小区名称")
    brand: Mapped[str | None] = mapped_column(String(50), nullable=True, comment="品牌")
    listing_type: Mapped[str | None] = mapped_column(String(20), nullable=True, comment="房源类型（整租/合租）")
    layout: Mapped[str | None] = mapped_column(String(50), nullable=True, comment="户型")
    area: Mapped[float | None] = mapped_column(Float, nullable=True, comment="面积（㎡）")
    business_district: Mapped[str | None] = mapped_column(String(50), nullable=True, comment="商圈")
    monthly_rent: Mapped[float | None] = mapped_column(Float, nullable=True, comment="月租金（元）")
    floor_level: Mapped[str | None] = mapped_column(String(20), nullable=True, comment="楼层等级（低/中/高）")
    total_floors: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="总楼层")
    decoration: Mapped[str | None] = mapped_column(String(20), nullable=True, comment="装修")
    source_platform: Mapped[str] = mapped_column(String(50), index=True, comment="来源平台")
    source_url: Mapped[str] = mapped_column(String(255), unique=True, comment="房源链接（唯一，用于去重）")
    first_crawled_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), comment="首次抓取时间"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), comment="更新时间"
    )
