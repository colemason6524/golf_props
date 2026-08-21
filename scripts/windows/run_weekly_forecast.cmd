@echo off
rem Generic weekly frozen forecast task (discovery, evidence, identity, archive).
rem Idempotent and fail-closed: it waits, blocks, or archives with distinct exit
rem codes that the Task Scheduler records.
rem
rem Exit codes:
rem   0  waiting (evidence not ready yet / not due) or forecast already archived
rem   10 blocked (no next event, unreviewed structure, or frozen pipeline refusal)
rem   11 deadline missed (first tee passed without an archived forecast)
rem   12 identity blocked (unresolved field identities)
rem   20 hard error (schedule/source/archive failure)
cd /d C:\Users\muski\golf_props
set PYTHONUNBUFFERED=1
echo [%date% %time%] weekly forecast start >> logs\weekly_forecast.log
.venv\Scripts\python -m golf_props.cli weekly-forecast >> logs\weekly_forecast.log 2>&1
set EXIT_CODE=%errorlevel%
echo [%date% %time%] weekly forecast exit=%EXIT_CODE% >> logs\weekly_forecast.log
exit /b %EXIT_CODE%
