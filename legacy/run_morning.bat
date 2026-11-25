@echo off
REM ============================================================
REM  Morning trading run (buy mode)
REM  Scheduled via Windows Task Scheduler.
REM  Output is appended to logs\morning.log with a timestamp.
REM ============================================================

cd /d C:\Users\30939\trading_system

if not exist logs mkdir logs

echo. >> logs\morning.log
echo ===== Morning run started: %DATE% %TIME% ===== >> logs\morning.log

python run_daily.py --morning >> logs\morning.log 2>&1

echo ===== Morning run finished: %DATE% %TIME% (exit %ERRORLEVEL%) ===== >> logs\morning.log
