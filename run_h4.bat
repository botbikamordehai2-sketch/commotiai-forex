@echo off
setlocal
cd /d C:\Users\User\fx_strength

echo.>> h4_scheduler.log
echo ==================================================>> h4_scheduler.log
echo H4 scan started: %date% %time%>> h4_scheduler.log

echo.| py .\fetch_4h_to_csv.py >> h4_scheduler.log 2>&1
if errorlevel 1 (
    echo ERROR: fetch_4h_to_csv.py failed.>> h4_scheduler.log
    exit /b 1
)

echo.| py .\strength_matrix_4h.py >> h4_scheduler.log 2>&1
if errorlevel 1 (
    echo ERROR: strength_matrix_4h.py failed.>> h4_scheduler.log
    exit /b 1
)

echo.| py .\signal_journal.py >> h4_scheduler.log 2>&1
if errorlevel 1 (
    echo ERROR: signal_journal.py failed.>> h4_scheduler.log
    exit /b 1
)


echo.| py .\append_price_history.py >> h4_scheduler.log 2>&1
if errorlevel 1 (
    echo ERROR: append_price_history.py failed.>> h4_scheduler.log
    exit /b 1
)

echo.| py .\detect_reversals.py >> h4_scheduler.log 2>&1
if errorlevel 1 (
    echo ERROR: detect_reversals.py failed.>> h4_scheduler.log
    exit /b 1
)

echo.| py .\build_dashboard_data_v2.py >> h4_scheduler.log 2>&1
if errorlevel 1 (
    echo ERROR: build_dashboard_data_v2.py failed.>> h4_scheduler.log
    exit /b 1
)
echo H4 scan completed: %date% %time%>> h4_scheduler.log
exit /b 0
