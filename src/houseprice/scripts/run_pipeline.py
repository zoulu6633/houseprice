"""定时全流程编排脚本：爬取 → 入库 → 生成静态页 → 自动发布。

由 Windows 任务计划程序通过 run_pipeline.bat 触发，无人值守执行；
也可手动运行单次全流程：
    uv run python -m houseprice.scripts.run_pipeline [--pages N]

流程:
    0. 登录：正式爬取前直接打开登录页，人工完成登录（登录态持久化）
    1. 爬取：遍历南京全部行政区，自动解析商圈并逐商圈抓取（每商圈一个 JSON）
    2. 入库：合并 JSON 全量覆盖写入 MySQL（先删除上一次同平台数据），并落行政区/商圈快照
    3. 静态页：渲染 docs/index.html
    4. 发布：git add/commit/push docs/index.html，触发 GitHub Pages 更新
    5. 排程：注册一次性任务，在本次爬取后的下一个 09:00 推送企业微信日报
"""

from __future__ import annotations

import argparse
import asyncio
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

from houseprice.getdata.save import save_output_files
from houseprice.getdata.spiders.base import DEFAULT_OUTPUT_DIR, PROJECT_ROOT
from houseprice.getdata.spiders.beike import crawl_all_district_businesses, login_beike
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


def schedule_wecom_notify() -> None:
    """注册一次性任务：在「本次爬取后的下一个 09:00」推送企业微信日报。

    固定任务名 houseprice_wecom，/F 覆盖式注册：同一天多次爬取只保留
    最近一次安排（只推一次），任务列表不堆积；当天不爬取则不会注册、
    不会推送。推送动作本身由根目录 wecom_notify.bat 承担。
    """
    now = datetime.now()
    target = now.replace(hour=9, minute=0, second=0, microsecond=0)
    if now >= target:  # 已过今天 9 点 → 安排明天 9 点
        target += timedelta(days=1)
    bat = PROJECT_ROOT / "wecom_notify.bat"
    tr = str(bat) if " " not in str(bat) else f'"{bat}"'
    try:
        subprocess.run(
            ["schtasks", "/Create", "/TN", "houseprice_wecom", "/SC", "ONCE",
             "/SD", target.strftime("%Y/%m/%d"), "/ST", target.strftime("%H:%M"),
             "/TR", tr, "/F"],
            check=True, cwd=PROJECT_ROOT, capture_output=True, text=True,
        )
    except subprocess.CalledProcessError as e:
        step(f"[警告] 注册企业微信推送任务失败：{(e.stderr or '').strip() or e}")
        return
    step(f"已安排企业微信日报于 {target:%Y-%m-%d %H:%M} 推送")


async def run_pipeline(
    pages: int,
    skip_crawl: bool = False,
    login_url: str | None = None,
    login_timeout: int | None = None,
) -> None:
    step(f"开始定时全流程（pages={pages}，skip_crawl={skip_crawl}，login_timeout={login_timeout}）")

    if skip_crawl:
        step("步骤 1/5：已跳过爬取（--skip-crawl），复用现有 JSON")
    else:
        step("步骤 1/5：人工登录（直接打开登录页）")
        if not login_beike(login_url=login_url, timeout=login_timeout):
            # 无人值守场景：登录超时直接中止，避免空数据全量覆盖清空数据库
            step("登录未完成（超时或未确认），中止流程，本次不更新数据")
            return
        step("步骤 2/5：爬取全城行政区商圈")
        # 同步阻塞的浏览器任务须留在主线程（DrissionPage 依赖），直接调用
        total = crawl_all_district_businesses(
            pages, "nj", output_dir=DEFAULT_OUTPUT_DIR
        )
        step(f"爬取完成，共 {total} 条")

    step("步骤 3/5：写入数据库（全量覆盖）")
    files = sorted(DEFAULT_OUTPUT_DIR.glob("*.json"))
    _, added, _ = await save_output_files(files)
    step(f"入库完成：全量覆盖 {added} 条（已删除上一次抓取的数据）")

    step("步骤 4/5：生成静态页面")
    await build_static.main()

    step("步骤 5/5：推送到 GitHub Pages")
    git_publish()

    schedule_wecom_notify()  # 安排下次 09:00 推送企业微信日报（内部打印结果）

    step("全流程完成")


def main() -> None:
    parser = argparse.ArgumentParser(description="定时爬取并更新静态页面（全流程编排）")
    parser.add_argument("--pages", type=int, default=3,
                        help="每个商圈抓取页数（每页约20条），默认3")
    parser.add_argument("--skip-crawl", action="store_true",
                        help="跳过爬取步骤，直接复用现有 JSON 跑入库/静态页/推送")
    parser.add_argument("--login-url", default=None,
                        help="贝壳登录页 URL（不传则用 beike.py 中 BEIKE_LOGIN_URL 常量）")
    parser.add_argument("--login-timeout", type=int, default=600,
                        help="登录等待超时（秒），默认600；超时未登录则中止流程，避免空数据覆盖数据库")
    args = parser.parse_args()
    asyncio.run(run_pipeline(args.pages, args.skip_crawl, args.login_url, args.login_timeout))


if __name__ == "__main__":
    main()
