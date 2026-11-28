@echo off
rem Scheduled stage B run (registered by schedule_research.ps1).
rem Usage: research_session.cmd <ideas> <budget_usd> [python]
setlocal
set IDEAS=%~1
set BUDGET=%~2
set PY=%~3
if "%PY%"=="" set PY=C:\Python313\python.exe
cd /d "%~dp0..\.."
if not exist research\agent\state mkdir research\agent\state
set LOG=research\agent\state\scheduled_runs.log
echo ===== %date% %time% ===== >> "%LOG%"
"%PY%" -m research.agent.drill >> "%LOG%" 2>&1
"%PY%" -m research.agent.session --ideas %IDEAS% --budget-usd %BUDGET% >> "%LOG%" 2>&1
"%PY%" -m research.agent.pipeline --resume-pending >> "%LOG%" 2>&1
endlocal
