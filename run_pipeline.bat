 @echo off
rem Scheduled pipeline launcher: login -> crawl -> save -> static page -> git push -> schedule wecom.
rem Invoked by Windows Task Scheduler in unattended mode.
rem 企业微信日报不再随 pipeline 立即推送，改由 run_pipeline 注册的一次性任务
rem （wecom_notify.bat）在本次爬取后的下一个 09:00 触发。
cd /d C:\Users\HP\Desktop\houseprice
if not exist logs mkdir logs
set PYTHONUNBUFFERED=1
uv run python -m houseprice.scripts.run_pipeline --pages 1 --login-timeout 600 >> logs\pipeline.log 2>&1
