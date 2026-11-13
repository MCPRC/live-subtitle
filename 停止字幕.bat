@echo off
cd /d "%~dp0"
if not exist "control" mkdir "control"
echo stop>"control\stop.request"
echo 已请求正常停止字幕，请等待当前处理结束。
