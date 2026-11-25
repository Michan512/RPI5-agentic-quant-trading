@echo off
REM ============================================================
REM  Afternoon trading run (sell mode)
REM  Scheduled via Windows Task Scheduler.
REM  Output is appended to logs\afternoon.log with a timestamp.
REM ============================================================

cd /d C:\Users\30939\trading_system

if not exist logs mkdir logs

echo. >> logs\afternoon.log
echo ===== Afternoon run started: %DATE% %TIME% ===== >> logs\afternoon.log

python run_daily.py --afternoon >> logs\afternoon.log 2>&1

echo ===== Afternoon run finished: %DATE% %TIME% (exit %ERRORLEVEL%) ===== >> logs\afternoon.log
