@echo off
setlocal

:: =============================================================================
:: MT5 Automated Forex Trading Bot — Enable Autostart
:: =============================================================================
:: Registers the bot to start automatically at Windows logon using
:: Task Scheduler (primary) or the Startup folder (fallback).
::
:: Task name: MT5TradingBot
:: Trigger:   At logon
:: Action:    start_bot.bat (full path)
::
:: To undo: run disable_autostart.bat
:: =============================================================================

title MT5 Bot — Enable Autostart

echo.
echo ============================================================
echo  MT5 Automated Forex Trading Bot — Enable Autostart
echo ============================================================

set PYTHON_EXE=python
if exist "venv\Scripts\python.exe" set PYTHON_EXE=venv\Scripts\python.exe

"%PYTHON_EXE%" scripts\autostart.py --enable

if errorlevel 1 (
    echo.
    echo [ERROR] Could not enable autostart. See messages above.
    echo.
    pause
    exit /b 1
)

pause
endlocal
