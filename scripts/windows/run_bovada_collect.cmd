@echo off
rem Recurring Bovada PGA odds snapshot for golf_props (research only).
rem Mirrors the horses Windows Task Scheduler pattern: one logical task per
rem cmd wrapper, separate log file, "Start in" set to the project root.
rem Research rule: odds stay outside the performance model.
cd /d C:\Users\muski\golf_props
set PYTHONUNBUFFERED=1
echo [%date% %time%] bovada collect start >> logs\bovada_collect.log
.venv\Scripts\python -m golf_props.cli collect-bovada-golf-odds >> logs\bovada_collect.log 2>&1
echo [%date% %time%] bovada collect exit=%errorlevel% >> logs\bovada_collect.log
exit /b %errorlevel%
