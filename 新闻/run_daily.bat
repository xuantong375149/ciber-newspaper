@echo off
rem Manually refresh the news page. The scheduled task runs the same fetch twice a day.
cd /d "%~dp0"
python fetch_news.py
if errorlevel 1 echo Update failed. See logs\run.log for details.
pause
