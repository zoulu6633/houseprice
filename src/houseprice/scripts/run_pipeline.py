"""定时全流程编排脚本：爬取 → 入库 → 生成静态页 → 自动发布。

由 Windows 任务计划程序通过 run_pipeline.bat 触发，无人值守执行；
也可手动运行单次全流程：
    uv run python -m houseprice.scripts.run_pipeline [--pages N]

流程:
    1. 爬取：遍历南京全部行政区，自动解析商圈并逐商圈抓取（每商圈一个 JSON）
    2. 入库：合并 JSON 按 source_url upsert 到 MySQL，并落行政区/商圈快照
    3. 静态页：渲染 docs/index.html
    4. 发布：git add/commit/push docs/index.html，触发 GitHub Pages 更新
"""

from __future__ import annotations

import argparse
import asyncio
import subprocess
from datetime import datetime
from pathlib import Path

from houseprice.getdata.save import save_output_files
from houseprice.getdata.spiders.base import DEFAULT_OUTPUT_DIR, PROJECT_ROOT
from houseprice.getdata.spiders.beike import crawl_all_district_businesses
from houseprice.scripts import build_static


def step(msg: str) -> None:
    """打印带时间戳的步骤日志（stdout 由 bat 重定向到 logs/pipeline.log）。"""
    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}", flush=True)


def git_publish() -> bool:
    """提交并推送 docs/index.html 到远端，触发 GitHub Pages 更新。

    无变更时跳过提交与推送（幂等），返回是否实际推送。
    """
    subprocess.run(["git", "add", "docs/index.html"], check=True, cwd=PROJECT_ROOT)
    if subprocess.run(
        ["git", "diff", "--cached", "--quiet"], cwd=PROJECT_ROOT
    ).returncode == 0:
        step("docs/index.html 无变更，跳过提交与推送")
        return False
    subprocess.run(
        ["git", "commit", "-m", f"chore: 定时更新静态页面 {datetime.now():%Y-%m-%d}"],
        check=True, cwd=PROJECT_ROOT,
    )
    subprocess.run(["git", "push"], check=True, cwd=PROJECT_ROOT)
    step("已推送 GitHub Pages 更新")
    return True


async def run_pipeline(pages: int, skip_crawl: bool = False) -> None:
    step(f"开始定时全流程（pages={pages}，skip_crawl={skip_crawl}）")

    if skip_crawl:
        step("步骤 1/4：已跳过爬取（--skip-crawl），复用现有 JSON")
    else:
        step("步骤 1/4：爬取全城行政区商圈")
        # 同步阻塞的浏览器任务须留在主线程（DrissionPage 依赖），直接调用
        total = crawl_all_district_businesses(
            pages, "nj", output_dir=DEFAULT_OUTPUT_DIR
        )
        step(f"爬取完成，共 {total} 条")

    step("步骤 2/4：写入数据库")
    files = sorted(DEFAULT_OUTPUT_DIR.glob("*.json"))
    updated, added, _ = await save_output_files(files)
    step(f"入库完成：更新 {updated} 条，新增 {added} 条")

    step("步骤 3/4：生成静态页面")
    await build_static.main()

    step("步骤 4/4：推送到 GitHub Pages")
    # git_publish()
    step("全流程完成")


def main() -> None:
    parser = argparse.ArgumentParser(description="定时爬取并更新静态页面（全流程编排）")
    parser.add_argument("--pages", type=int, default=3,
                        help="每个商圈抓取页数（每页约20条），默认3")
    parser.add_argument("--skip-crawl", action="store_true",
                        help="跳过爬取步骤，直接复用现有 JSON 跑入库/静态页/推送")
    args = parser.parse_args()
    asyncio.run(run_pipeline(args.pages, args.skip_crawl))


if __name__ == "__main__":
    main()
