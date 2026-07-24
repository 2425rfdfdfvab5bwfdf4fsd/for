@echo off
setlocal

:: =============================================================================
:: MT5 Automated Forex Trading Bot — Disable Autostart
:: =============================================================================
:: Removes the Task Scheduler entry and/or Startup folder shortcut
:: created by enable_autostart.bat.
::
:: Task name: MT5TradingBot
:: =============================================================================

title MT5 Bot — Disable Autostart

echo.
echo ============================================================
echo  MT5 Automated Forex Trading Bot — Disable Autostart
echo ============================================================

set PYTHON_EXE=python
if exist "venv\Scripts\python.exe" set PYTHON_EXE=venv\Scripts\python.exe

"%PYTHON_EXE%" scripts\autostart.py --disable

if errorlevel 1 (
    echo.
    echo [ERROR] Could not fully disable autostart. See messages above.
    echo.
    pause
    exit /b 1
)

pause
endlocal
