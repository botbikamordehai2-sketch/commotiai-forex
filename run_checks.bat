@echo off
chcp 65001 >nul
echo ============================================================
echo   commotiai-forex - PRE-FLIGHT CHECKS
echo   Do NOT deploy to live money until you see the green mark.
echo ============================================================
echo.

cd /d "%~dp0"

echo [1/2] Ruff lint...
ruff check .
if %errorlevel% neq 0 (
    echo.
    echo [FAIL] Ruff found issues. Fix before running tests.
    pause
    exit /b 1
)
echo   OK.
echo.

echo [2/2] Pytest...
python -m pytest tests/ -n 1 -q --maxfail=3
if %errorlevel% neq 0 (
    echo.
    echo [FAIL] Tests failed. Do NOT deploy.
    pause
    exit /b 1
)
echo   OK.
echo.

echo ============================================================
echo   [READY] All checks green.
echo ============================================================
pause
