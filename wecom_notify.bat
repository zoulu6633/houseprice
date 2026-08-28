@echo off
rem 企业微信日报入口：由 run_pipeline 注册的一次性任务（houseprice_wecom）
rem 在本次爬取后的下一个 09:00 触发；当天未爬取则不会运行。
rem 新电脑部署时请把 cd /d 改为项目实际路径。
cd /d C:\Users\HP\Desktop\houseprice
if not exist logs mkdir logs
set PYTHONUNBUFFERED=1
uv run python -m houseprice.services.wecom_notify >> logs\wecom.log 2>&1
