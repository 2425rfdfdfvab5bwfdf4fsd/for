@echo off
setlocal

:: =============================================================================
:: MT5 Automated Forex Trading Bot — Status Script
:: =============================================================================
:: Reads heartbeat.txt and bot.pid to display a real-time bot status report.
:: No MT5 connection required — reads local data files only.
:: No secrets exposed in output.
::
:: Usage:
::   status.bat                    Show current status
:: =============================================================================

title MT5 Bot — Status

:: Ensure the data directory exists (in case bot has never run)
if not exist "data" mkdir data

:: Try to use venv Python if available, otherwise fall back to system Python
set PYTHON_EXE=python
if exist "venv\Scripts\python.exe" set PYTHON_EXE=venv\Scripts\python.exe

:: Run the status reader
"%PYTHON_EXE%" scripts\status_reader.py

if errorlevel 1 (
    echo.
    echo [ERROR] Status reader encountered an unexpected error.
    echo         Check that Python is installed and scripts\status_reader.py exists.
    echo.
)

endlocal
