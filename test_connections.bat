@echo off
setlocal

:: =============================================================================
:: MT5 Automated Forex Trading Bot — Connection Test
:: =============================================================================
:: Tests MT5 terminal and Telegram bot connectivity before the first live run.
:: Safe to run at any time — never places orders or modifies configuration.
::
:: Tests performed:
::   1. MT5 terminal connection (Windows only — skipped on Linux)
::   2. Telegram bot token validation (getMe API call)
::   3. Telegram test message delivery (sendMessage to chat_id)
:: =============================================================================

title MT5 Bot — Connection Test

echo.
echo ============================================================
echo  MT5 Automated Forex Trading Bot — Connection Test
echo ============================================================
echo.

if not exist "venv\Scripts\activate.bat" (
    echo [ERROR] Virtual environment not found.
    echo         Please run setup.bat first.
    echo.
    pause
    exit /b 1
)

if not exist ".env" (
    echo [ERROR] .env not found.
    echo         Please run configure.bat first.
    echo.
    pause
    exit /b 1
)

call venv\Scripts\activate.bat

python scripts\test_connections.py

if errorlevel 1 (
    echo.
    echo [!] One or more connection tests failed.
    echo     Fix the issues above before enabling live trading.
) else (
    echo     All connections verified — bot is ready.
)

echo.
pause
endlocal
