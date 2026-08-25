"""报告页聚合结果的 Pydantic 模型。"""

from pydantic import BaseModel


class RentBucket(BaseModel):
    """租金区间分布的一个分档。"""

    label: str
    count: int


class TopCommunity(BaseModel):
    """热门小区排行的一项。"""

    community_name: str
    count: int
    avg_rent: float | None


class ListingItem(BaseModel):
    """房源明细表的一行。"""

    district: str | None
    business_district: str | None
    community_name: str
    layout: str | None
    listing_type: str | None
    area: float | None
    monthly_rent: float | None
    decoration: str | None
    source_url: str


class DistrictReport(BaseModel):
    """一个行政区（或全城）的聚合统计。"""

    district: str
    count: int
    avg_rent: float | None
    median_rent: float | None
    avg_area: float | None
    rent_buckets: list[RentBucket]
    top_communities: list[TopCommunity]
    listings: list[ListingItem]


class DistrictTrend(BaseModel):
    """一个行政区的环比变化（最近两批快照对比）。"""

    district: str
    last_count: int
    current_count: int
    count_delta: int
    last_avg_rent: float | None
    current_avg_rent: float | None
    rent_delta: float | None
    rent_delta_pct: float | None
    last_avg_area: float | None
    current_avg_area: float | None


class BusinessTrend(BaseModel):
    """一个商圈的环比变化（最近两批快照对比）。"""

    district: str | None
    business_district: str
    last_count: int
    current_count: int
    count_delta: int
    last_avg_rent: float | None
    current_avg_rent: float | None
    rent_delta: float | None
    rent_delta_pct: float | None
    last_avg_area: float | None
    current_avg_area: float | None
