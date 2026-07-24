@echo off
setlocal EnableDelayedExpansion

:: =============================================================================
:: MT5 Automated Forex Trading Bot — Start Script
:: =============================================================================
:: Starts main.py and watchdog.py as background processes.
:: Writes PIDs to data/bot.pid and data/watchdog.pid.
:: Safe to call from restart_bot.bat.
:: =============================================================================

title MT5 Bot — Starting

echo.
echo ============================================================
echo  MT5 Automated Forex Trading Bot — Start
echo ============================================================
echo.

:: ── Pre-flight checks ────────────────────────────────────────────────────────

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

:: Check if bot is already running
if exist "data\bot.pid" (
    set /p EXISTING_PID=<data\bot.pid
    tasklist /FI "PID eq !EXISTING_PID!" 2>nul | find "!EXISTING_PID!" >nul 2>&1
    if not errorlevel 1 (
        echo [!] Bot is already running ^(PID !EXISTING_PID!^).
        echo     Use restart_bot.bat to restart, or stop_bot.bat to stop.
        echo.
        pause
        exit /b 0
    ) else (
        echo [INFO] Stale PID file found — cleaning up...
        del "data\bot.pid" >nul 2>&1
    )
)

:: Activate venv
call venv\Scripts\activate.bat
if errorlevel 1 (
    echo [ERROR] Failed to activate virtual environment.
    pause
    exit /b 1
)

:: Ensure data directory exists
if not exist "data" mkdir data

:: ── Check MT5 terminal (optional warning) ────────────────────────────────────

set MT5_RUNNING=0
tasklist 2>nul | find /i "terminal64.exe" >nul 2>&1 && set MT5_RUNNING=1
tasklist 2>nul | find /i "terminal.exe"   >nul 2>&1 && set MT5_RUNNING=1

if !MT5_RUNNING! EQU 0 (
    echo [!] MT5 terminal does not appear to be running.
    echo     The bot will start but cannot trade until MT5 is open.
    echo.
)

:: ── Start main bot ───────────────────────────────────────────────────────────

echo [1/2] Starting main bot process...
start /B "" venv\Scripts\python.exe main.py > logs\bot_stdout.log 2>&1
timeout /t 1 /nobreak >nul

:: Capture PID of the python process just launched (last python in list)
for /f "tokens=2" %%p in ('tasklist /FI "IMAGENAME eq python.exe" /NH 2^>nul ^| findstr /V "^$"') do set BOT_PID=%%p

if defined BOT_PID (
    echo !BOT_PID!> data\bot.pid
    echo        Main bot started — PID !BOT_PID!
) else (
    echo [WARNING] Could not capture bot PID. Check logs\bot_stdout.log for errors.
)

:: ── Start watchdog ───────────────────────────────────────────────────────────

echo [2/2] Starting watchdog process...
start /B "" venv\Scripts\python.exe watchdog.py > logs\watchdog_stdout.log 2>&1
timeout /t 1 /nobreak >nul

for /f "tokens=2" %%p in ('tasklist /FI "IMAGENAME eq python.exe" /NH 2^>nul ^| findstr /V "^$"') do set WD_PID=%%p

if defined WD_PID (
    echo !WD_PID!> data\watchdog.pid
    echo        Watchdog started — PID !WD_PID!
) else (
    echo [WARNING] Could not capture watchdog PID.
)

:: ── Wait and confirm ─────────────────────────────────────────────────────────

echo.
echo  Waiting 3 seconds for startup...
timeout /t 3 /nobreak >nul

echo.
echo ============================================================
echo  Bot started. Use status.bat to check live status.
echo  Use stop_bot.bat to stop, restart_bot.bat to restart.
echo ============================================================
echo.

endlocal
