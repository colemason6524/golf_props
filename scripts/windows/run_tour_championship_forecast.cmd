@echo off
rem One-shot frozen prospective forecast for the 2026 TOUR Championship.
rem Research only. No odds enter the performance model.
rem
rem Prerequisites (manual, before first tee Thu 2026-08-27):
rem   1. After BMW concludes (2026-08-23), preserve the official top-30 field at
rem      data\raw\fields\tour_championship_2026_field.csv.
rem   2. Once tee times are posted, set TOUR_START_UTC to the VERIFIED first-tee
rem      UTC timestamp. It must be strictly after this task's creation time; the
rem      frozen workflow rejects the run otherwise (no post-tee backfilling).
rem
rem The task skips gracefully if the field is not yet preserved or if the
rem forecast bundle is already archived (never overwrites an archived forecast).
cd /d C:\Users\muski\golf_props
set FIELD=data\raw\fields\tour_championship_2026_field.csv
set OUT=data\interim\reports\tour_championship_2026_frozen_simulation
set MANIFEST=data\interim\reports\rolling_round_simulation_validation\frozen_model_manifest.json
set TOUR_START_UTC=2026-08-27T13:00:00Z
echo [%date% %time%] tour championship forecast start >> logs\tour_championship_forecast.log
if not exist "%FIELD%" (
  echo [%date% %time%] field not preserved yet; skipping. >> logs\tour_championship_forecast.log
  exit /b 0
)
if exist "%OUT%\run_manifest.json" (
  echo [%date% %time%] forecast bundle already archived; not overwriting. >> logs\tour_championship_forecast.log
  exit /b 0
)
.venv\Scripts\python -m golf_props.cli predict-current-event ^
  --manifest "%MANIFEST%" ^
  --field "%FIELD%" ^
  --output-dir "%OUT%" ^
  --event-name "TOUR Championship" ^
  --event-date 2026-08-27 ^
  --event-start-at-utc "%TOUR_START_UTC%" ^
  --cut-rule no_cut ^
  --simulations 20000 >> logs\tour_championship_forecast.log 2>&1
echo [%date% %time%] tour championship forecast exit=%errorlevel% >> logs\tour_championship_forecast.log
exit /b %errorlevel%
