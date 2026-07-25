@echo off
setlocal EnableDelayedExpansion

:: =============================================================================
:: MT5 Automated Forex Trading Bot — Boot-to-Trade Autostart Launcher
:: =============================================================================
::
:: PURPOSE
::   Full unattended startup: sleep prevention → MT5 launch → bot start.
::   Designed to be registered with Windows Task Scheduler via
::   scripts\install_autostart.ps1 and triggered at logon.
::
:: SMART DOUBLE-CLICK GUARD
::   When you double-click a .bat file Windows uses cmd /c — the window
::   closes instantly on exit, hiding any errors.  This script detects
::   that and relaunches itself under cmd /k (window stays open).
::   Task Scheduler is unaffected — it sets its own environment and
::   never defines _SMC_LAUNCHED, so the script exits cleanly after the
::   bot starts (allowing proper restart-on-failure tracking).
::
:: CONFIGURABLE CONSTANTS — edit the block below, no code changes needed
:: =============================================================================

:: ── Automation constants ──────────────────────────────────────────────────────
set MT5_WAIT_TIMEOUT_SECONDS=120
set MT5_LOGIN_GRACE_SECONDS=20
set BOT_SCRIPT=main.py
set BOT_FLAGS=
set PREVENT_SLEEP=true
set SLEEP_RESTORE_MINUTES=30
set LOCK_SCREEN_AFTER_START=false
set PAUSE_ON_ERROR=true

:: ── Smart double-click guard ──────────────────────────────────────────────────
:: First run:  _SMC_LAUNCHED is not defined → relaunch under cmd /k (keeps window)
:: Second run: _SMC_LAUNCHED=1 is set → skip guard, run normally
:: Task Scheduler: never defines _SMC_LAUNCHED → guard is skipped, exits cleanly
if not defined _SMC_LAUNCHED (
    set _SMC_LAUNCHED=1
    cmd /k ""%~f0" %*"
    exit /b 0
)

:: =============================================================================
:: Script body (runs on second invocation or via Task Scheduler)
:: =============================================================================

title SMC Bot - AUTO-TRADE MODE

echo.
echo ============================================================
echo  MT5 Automated Forex Trading Bot — Autostart
echo ============================================================
echo  %date% %time%
echo ============================================================
echo.

:: ── Resolve project root (directory containing this .bat) ────────────────────
set "PROJECT_ROOT=%~dp0"
cd /d "%PROJECT_ROOT%"

:: ── Ensure logs directory exists ─────────────────────────────────────────────
if not exist "logs" mkdir logs

:: ── Cross-version date stamp (PowerShell primary, wmic fallback) ─────────────
:: Works on Windows 10, 11, and builds where wmic was removed.
set LOG_DATE=
for /f "delims=" %%d in ('powershell -NoProfile -Command "Get-Date -Format 'yyyy-MM-dd'" 2^>nul') do set LOG_DATE=%%d
if "!LOG_DATE!"=="" (
    :: Fallback for old Windows 10 builds
    for /f "skip=1 tokens=1" %%d in ('wmic os get LocalDateTime 2^>nul') do (
        if "!LOG_DATE!"=="" (
            set RAW=%%d
            set LOG_DATE=!RAW:~0,4!-!RAW:~4,2!-!RAW:~6,2!
        )
    )
)
if "!LOG_DATE!"=="" set LOG_DATE=%date:~-4%-%date:~3,2%-%date:~0,2%

set LOG_FILE=logs\autostart_!LOG_DATE!.log
echo [AUTOSTART] %date% %time% — Bot starting >> "!LOG_FILE!"

:: ── Layer 1 sleep prevention: OS power settings ──────────────────────────────
if /i "!PREVENT_SLEEP!"=="true" (
    echo [1/5] Enabling sleep prevention ^(Layer 1 — OS power settings^)...

    :: Save original AC standby timeout from registry before overriding
    set ORIGINAL_SLEEP=!SLEEP_RESTORE_MINUTES!
    for /f "tokens=3" %%v in ('reg query "HKLM\SYSTEM\CurrentControlSet\Control\Power" /v ACSettingIndex 2^>nul ^| findstr ACSettingIndex') do (
        set /a ORIGINAL_SLEEP=%%v / 60 2>nul
    )

    :: Set AC sleep to Never (0)
    powercfg /change standby-timeout-ac 0 >nul 2>&1
    if errorlevel 1 (
        echo        [WARNING] Could not set AC sleep — may need admin rights
        echo [WARNING] powercfg failed >> "!LOG_FILE!"
    ) else (
        echo        OS sleep set to Never ^(original: !ORIGINAL_SLEEP! min^)
    )
) else (
    echo [1/5] Sleep prevention disabled ^(PREVENT_SLEEP=false^)
    set ORIGINAL_SLEEP=0
)

:: ── Check for virtual environment ────────────────────────────────────────────
echo [2/5] Checking environment...

if not exist "venv\Scripts\activate.bat" (
    echo.
    echo [ERROR] Virtual environment not found.
    echo         Please run setup.bat first.
    echo.
    echo [ERROR] venv not found >> "!LOG_FILE!"
    goto :ERROR_EXIT
)

if not exist ".env" (
    echo.
    echo [ERROR] .env not found.
    echo         Please run configure.bat first.
    echo.
    echo [ERROR] .env not found >> "!LOG_FILE!"
    goto :ERROR_EXIT
)

call venv\Scripts\activate.bat
echo        Environment: OK

:: ── MT5 process detection and readiness polling ──────────────────────────────
echo [3/5] Checking MetaTrader 5...

set MT5_RUNNING=0
tasklist 2>nul | find /i "terminal64.exe" >nul 2>&1 && set MT5_RUNNING=1
if !MT5_RUNNING! EQU 0 (
    tasklist 2>nul | find /i "terminal.exe" >nul 2>&1 && set MT5_RUNNING=1
)

if !MT5_RUNNING! EQU 0 (
    :: Try to launch MT5 from configured path
    set MT5_PATH=
    for /f "tokens=2 delims==" %%v in ('findstr /i "MT5_TERMINAL_PATH" .env 2^>nul') do set MT5_PATH=%%v
    set MT5_PATH=!MT5_PATH: =!

    if "!MT5_PATH!"=="" (
        :: Default installation path fallback
        if exist "%ProgramFiles%\MetaTrader 5\terminal64.exe" (
            set MT5_PATH=%ProgramFiles%\MetaTrader 5\terminal64.exe
        ) else if exist "%ProgramFiles(x86)%\MetaTrader 5\terminal64.exe" (
            set MT5_PATH=%ProgramFiles(x86)%\MetaTrader 5\terminal64.exe
        )
    )

    if "!MT5_PATH!"=="" (
        echo        [WARNING] MT5 not running and MT5_TERMINAL_PATH not set.
        echo        Bot will start and wait for MT5 to connect.
    ) else (
        echo        Launching MetaTrader 5...
        start "" "!MT5_PATH!"
        echo [INFO] Launched MT5: !MT5_PATH! >> "!LOG_FILE!"

        :: Poll until MT5 process appears (up to MT5_WAIT_TIMEOUT_SECONDS)
        set ELAPSED=0
        :MT5_WAIT_LOOP
        timeout /t 5 /nobreak >nul
        set /a ELAPSED+=5

        set MT5_FOUND=0
        tasklist 2>nul | find /i "terminal64.exe" >nul 2>&1 && set MT5_FOUND=1
        if !MT5_FOUND! EQU 0 (
            tasklist 2>nul | find /i "terminal.exe" >nul 2>&1 && set MT5_FOUND=1
        )

        if !MT5_FOUND! EQU 1 goto :MT5_READY

        if !ELAPSED! LSS !MT5_WAIT_TIMEOUT_SECONDS! goto :MT5_WAIT_LOOP

        echo.
        echo [WARNING] MT5 did not appear within !MT5_WAIT_TIMEOUT_SECONDS!s.
        echo           Bot will start anyway — it will retry MT5 connection.
        echo [WARNING] MT5 timeout after !MT5_WAIT_TIMEOUT_SECONDS!s >> "!LOG_FILE!"
        goto :START_BOT
    )
) else (
    echo        MT5 already running.
)

:MT5_READY
echo        MT5 detected. Waiting !MT5_LOGIN_GRACE_SECONDS!s for price sync...
timeout /t !MT5_LOGIN_GRACE_SECONDS! /nobreak >nul

:START_BOT

:: ── Layer 2 sleep prevention: kernel-level power request ─────────────────────
if /i "!PREVENT_SLEEP!"=="true" (
    echo [4/5] Enabling sleep prevention ^(Layer 2 — kernel power request^)...
    start /B "" venv\Scripts\python.exe -c "import sys; sys.path.insert(0,'scripts'); from sleep_guard import SleepGuard; g=SleepGuard.acquire_process_lifetime(); import time; [time.sleep(3600) for _ in iter(int, 1)]" >nul 2>&1
    echo        Kernel sleep lock active ^(ES_SYSTEM_REQUIRED + ES_AWAYMODE_REQUIRED^)
) else (
    echo [4/5] Kernel sleep prevention skipped ^(PREVENT_SLEEP=false^)
)

:: ── Start the bot ─────────────────────────────────────────────────────────────
echo [5/5] Starting bot...

if not exist "data" mkdir data
if not exist "logs" mkdir logs

start /B "" venv\Scripts\python.exe !BOT_SCRIPT! !BOT_FLAGS! >> "!LOG_FILE!" 2>&1
timeout /t 2 /nobreak >nul

:: Capture PID of the most-recently launched python.exe
set BOT_PID=
for /f "tokens=2" %%p in ('tasklist /FI "IMAGENAME eq python.exe" /NH 2^>nul ^| findstr /V "^$" ^| findstr /V "sleep_guard"') do set BOT_PID=%%p

if defined BOT_PID (
    echo !BOT_PID!> data\bot.pid
    echo        Bot started — PID !BOT_PID!
    echo [INFO] Bot started PID=!BOT_PID! >> "!LOG_FILE!"
) else (
    echo [WARNING] Could not capture bot PID. Check !LOG_FILE! for errors.
    echo [WARNING] PID capture failed >> "!LOG_FILE!"
)

:: ── Optionally lock screen ────────────────────────────────────────────────────
if /i "!LOCK_SCREEN_AFTER_START!"=="true" (
    timeout /t 5 /nobreak >nul
    rundll32.exe user32.dll,LockWorkStation
)

echo.
echo ============================================================
echo  Bot is running. Window will remain open for monitoring.
echo  Close this window or press Ctrl+C to stop monitoring.
echo  To stop the BOT itself, run: stop_bot.bat
echo ============================================================
echo.

:: Keep window open so log output is visible (Task Scheduler mode exits here)
if defined _SMC_LAUNCHED (
    echo  Log file: !LOG_FILE!
    echo.
    :: Wait for bot process to exit before restoring sleep
    :WAIT_FOR_BOT
    if defined BOT_PID (
        tasklist /FI "PID eq !BOT_PID!" 2>nul | find "!BOT_PID!" >nul 2>&1
        if not errorlevel 1 (
            timeout /t 30 /nobreak >nul
            goto :WAIT_FOR_BOT
        )
    )
)

goto :RESTORE_AND_EXIT

:ERROR_EXIT
if /i "!PAUSE_ON_ERROR!"=="true" (
    echo.
    echo  Press any key to exit...
    pause >nul
)

:RESTORE_AND_EXIT
:: Restore original AC sleep timeout
if /i "!PREVENT_SLEEP!"=="true" (
    if defined ORIGINAL_SLEEP if "!ORIGINAL_SLEEP!" NEQ "0" (
        powercfg /change standby-timeout-ac !ORIGINAL_SLEEP! >nul 2>&1
        echo [AUTOSTART] Sleep restored to !ORIGINAL_SLEEP! min >> "!LOG_FILE!"
    )
)

endlocal
