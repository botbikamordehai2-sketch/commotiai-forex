@echo off
setlocal

cd /d C:\Users\User\fx_strength

echo.>> metrics_scheduler.log
echo ==================================================>> metrics_scheduler.log
echo Metrics scan started: %date% %time%>> metrics_scheduler.log

py .\evaluate_signals.py >> metrics_scheduler.log 2>&1
if errorlevel 1 (
    echo ERROR: evaluate_signals.py failed.>> metrics_scheduler.log
    exit /b 1
)

py .\performance_report.py >> metrics_scheduler.log 2>&1
if errorlevel 1 (
    echo ERROR: performance_report.py failed.>> metrics_scheduler.log
    exit /b 1
)

echo Metrics scan completed: %date% %time%>> metrics_scheduler.log
exit /b 0