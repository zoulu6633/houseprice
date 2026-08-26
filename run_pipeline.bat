@echo off
rem Scheduled pipeline launcher: crawl -> save -> static page -> git push.
rem Invoked by Windows Task Scheduler in unattended mode.
cd /d C:\Users\HP\Desktop\houseprice
if not exist logs mkdir logs
set PYTHONUNBUFFERED=1
uv run python -m houseprice.scripts.run_pipeline --pages 1 >> logs\pipeline.log 2>&1
