"""企业微信 Webhook 推送：各行政区平均租金、环比与数据数量。

独立于静态页报告，可在入库完成后单独运行，也可被编排脚本调用：
    uv run python -m houseprice.services.wecom_notify

数据口径与报告页一致：复用 report_service.build_price_report
（对比 district_snapshots 表最近两批快照），避免重复计算逻辑。
需要环境变量 WECOM_WEBHOOK_URL（企业微信群机器人 webhook 地址）。
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import requests
from dotenv import load_dotenv

from houseprice.db_config import AsyncSession_Local, async_engine
from houseprice.services.report_service import build_price_report

# 项目根目录（本文件位于 src/houseprice/services/wecom_notify.py，向上 3 级）
PROJECT_ROOT = Path(__file__).resolve().parents[3]
# 加载项目根目录的 .env（含 WECOM_WEBHOOK_URL），不依赖启动时的工作目录
load_dotenv(PROJECT_ROOT / ".env")

# 企业微信群机器人 webhook（群内添加机器人后获取）
WECOM_WEBHOOK_URL = os.getenv("WECOM_WEBHOOK_URL")


# GitHub Pages 静态详情页（完整报告）
GITHUB_PAGES_URL = "https://zoulu6633.github.io/houseprice/"


def format_message(trends: list[dict], current_at: str, last_at: str) -> str:
    """把各区环比数据格式化为企业微信 markdown 消息文本。

    trends 为 build_price_report 返回的各区环比列表（含"全部"，
    这里跳过），每个元素含行政区名、平均租金、环比与在租数量。
    """
    lines = ["**南京租房行情日报**", ""]
    lines.append(f"数据批次：{current_at}（对比 {last_at}）")
    lines.append("")

    for t in trends:
        if t["district"] in ("全部", "独栋"):
            continue  # "全部"为全城汇总，"独栋"是无行政区房源的兜底分组，均不单独推送

        avg_rent = t["current_avg_rent"]
        rent_desc = f"{avg_rent:g} 元" if avg_rent is not None else "无数据"
        pct, delta = t["rent_delta_pct"], t["rent_delta"]
        if pct is not None:
            sign = "+" if pct >= 0 else ""
            rent_desc += f"，环比 {sign}{pct}%（{delta:+g} 元）"
        else:
            rent_desc += "（暂无环比）"

        lines.append(f"**{t['district']}**：平均租金 {rent_desc}")
        lines.append(
            f"在租 {t['current_count']} 套（上期 {t['last_count']} 套，{t['count_delta']:+d}）"
        )
        lines.append("")

    lines.append(f"详情页：[点击查看完整报告]({GITHUB_PAGES_URL})")
    return "\n".join(lines).strip()


def send_message(content: str) -> None:
    """POST markdown 消息到企业微信机器人 webhook。"""
    resp = requests.post(
        WECOM_WEBHOOK_URL,
        json={"msgtype": "markdown", "markdown": {"content": content}},
        timeout=10,
    )
    resp.raise_for_status()
    data = resp.json()
    if data.get("errcode") != 0:
        raise RuntimeError(f"企业微信推送失败: {data}")


async def notify() -> bool:
    """读取最近两批行政区快照并推送日报；快照不足两批时不推送，返回是否已推送。"""
    async with AsyncSession_Local() as session:
        price = await build_price_report(session)
    if not price["has_data"]:
        print("快照不足两批，跳过企业微信推送")
        return False
    content = format_message(price["trends"], price["current_at"], price["last_at"])
    sent_count = sum(
        1 for t in price["trends"] if t["district"] not in ("全部", "独栋")
    )
    # print(content)
    send_message(content)
    print(f"企业微信推送成功（共 {sent_count} 个行政区）")
    return True


async def main() -> None:
    try:
        await notify()
    finally:
        await async_engine.dispose()  # 关闭连接池，避免退出时告警
    # print(WECOM_WEBHOOK_URL)


if __name__ == "__main__":
    asyncio.run(main())
