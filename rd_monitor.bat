@echo off
cd /d "%~dp0"
if not exist "data" mkdir data
echo Queud AIO monitor — logs: data\monitor.log
python rd_monitor.py
pause