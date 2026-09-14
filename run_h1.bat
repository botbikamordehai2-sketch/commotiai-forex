@echo off
setlocal
cd /d C:\Users\User\fx_strength

echo.>> h1_scheduler.log
echo ==================================================>> h1_scheduler.log
echo H1 scan started: %date% %time%>> h1_scheduler.log

echo.| py .\fetch_data_to_csv.py >> h1_scheduler.log 2>&1
if errorlevel 1 (
    echo ERROR: fetch_data_to_csv.py failed.>> h1_scheduler.log
    exit /b 1
)

echo.| py .\strength_matrix.py >> h1_scheduler.log 2>&1
if errorlevel 1 (
    echo ERROR: strength_matrix.py failed.>> h1_scheduler.log
    exit /b 1
)

echo.| py .\signal_journal.py >> h1_scheduler.log 2>&1
if errorlevel 1 (
    echo ERROR: signal_journal.py failed.>> h1_scheduler.log
    exit /b 1
)


echo.| py .\append_price_history.py >> h1_scheduler.log 2>&1
if errorlevel 1 (
    echo ERROR: append_price_history.py failed.>> h1_scheduler.log
    exit /b 1
)

echo.| py .\detect_reversals.py >> h1_scheduler.log 2>&1
if errorlevel 1 (
    echo ERROR: detect_reversals.py failed.>> h1_scheduler.log
    exit /b 1
)

echo.| py .\build_dashboard_data_v2.py >> h1_scheduler.log 2>&1
if errorlevel 1 (
    echo ERROR: build_dashboard_data_v2.py failed.>> h1_scheduler.log
    exit /b 1
)
echo H1 scan completed: %date% %time%>> h1_scheduler.log
exit /b 0
