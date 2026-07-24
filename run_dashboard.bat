@echo off
setlocal

:: =============================================================================
:: MT5 Automated Forex Trading Bot — Dashboard
:: =============================================================================
:: Starts the Flask monitoring dashboard and opens it in the default browser.
:: The dashboard is read-only — it never places or modifies trades.
::
:: Runs in the foreground. Press Ctrl+C to stop.
:: =============================================================================

title MT5 Bot — Dashboard

echo.
echo ============================================================
echo  MT5 Automated Forex Trading Bot — Dashboard
echo ============================================================
echo.

if not exist "venv\Scripts\activate.bat" (
    echo [ERROR] Virtual environment not found. Please run setup.bat first.
    pause
    exit /b 1
)

call venv\Scripts\activate.bat

:: Load dashboard host/port from .env if present, otherwise use defaults
set DASHBOARD_HOST=127.0.0.1
set DASHBOARD_PORT=8080

if exist ".env" (
    for /f "usebackq tokens=1,2 delims==" %%a in (".env") do (
        if "%%a"=="DASHBOARD_HOST" set DASHBOARD_HOST=%%b
        if "%%a"=="DASHBOARD_PORT" set DASHBOARD_PORT=%%b
    )
)

echo  Dashboard URL: http://!DASHBOARD_HOST!:!DASHBOARD_PORT!
echo  Press Ctrl+C to stop the dashboard.
echo.

:: Open browser after a short delay
start "" /b cmd /c "timeout /t 2 /nobreak >nul && start http://!DASHBOARD_HOST!:!DASHBOARD_PORT!"

:: Start dashboard (foreground — blocks until Ctrl+C)
python app\dashboard\app.py

endlocal
