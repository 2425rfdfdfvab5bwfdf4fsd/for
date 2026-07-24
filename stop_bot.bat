@echo off
setlocal EnableDelayedExpansion

:: =============================================================================
:: MT5 Automated Forex Trading Bot — Stop Script
:: =============================================================================
:: Gracefully stops the bot and watchdog processes.
:: Reads PIDs from data/bot.pid and data/watchdog.pid.
:: Called by restart_bot.bat and update.bat.
:: =============================================================================

title MT5 Bot — Stopping

echo.
echo ============================================================
echo  MT5 Automated Forex Trading Bot — Stop
echo ============================================================
echo.

set BOT_STOPPED=0
set WD_STOPPED=0

:: ── Stop main bot ────────────────────────────────────────────────────────────

if exist "data\bot.pid" (
    set /p BOT_PID=<data\bot.pid
    echo [1/2] Stopping bot process ^(PID !BOT_PID!^)...

    tasklist /FI "PID eq !BOT_PID!" 2>nul | find "!BOT_PID!" >nul 2>&1
    if errorlevel 1 (
        echo        Process not found — already stopped.
        del "data\bot.pid" >nul 2>&1
        set BOT_STOPPED=1
    ) else (
        :: Send graceful CTRL+C equivalent via taskkill
        taskkill /PID !BOT_PID! 2>nul
        set WAIT=0
:BOT_WAIT_LOOP
        timeout /t 1 /nobreak >nul
        tasklist /FI "PID eq !BOT_PID!" 2>nul | find "!BOT_PID!" >nul 2>&1
        if errorlevel 1 (
            echo        Bot stopped cleanly.
            del "data\bot.pid" >nul 2>&1
            set BOT_STOPPED=1
            goto :BOT_DONE
        )
        set /a WAIT+=1
        if !WAIT! LSS 30 goto :BOT_WAIT_LOOP

        echo [!] Bot did not stop within 30 seconds — forcing kill...
        taskkill /F /PID !BOT_PID! >nul 2>&1
        del "data\bot.pid" >nul 2>&1
        set BOT_STOPPED=1
    )
) else (
    echo [1/2] No bot PID file found — bot may not be running.
    set BOT_STOPPED=1
)

:BOT_DONE

:: ── Stop watchdog ────────────────────────────────────────────────────────────

if exist "data\watchdog.pid" (
    set /p WD_PID=<data\watchdog.pid
    echo [2/2] Stopping watchdog process ^(PID !WD_PID!^)...

    tasklist /FI "PID eq !WD_PID!" 2>nul | find "!WD_PID!" >nul 2>&1
    if errorlevel 1 (
        echo        Watchdog not found — already stopped.
        del "data\watchdog.pid" >nul 2>&1
        set WD_STOPPED=1
    ) else (
        taskkill /F /PID !WD_PID! >nul 2>&1
        del "data\watchdog.pid" >nul 2>&1
        echo        Watchdog stopped.
        set WD_STOPPED=1
    )
) else (
    echo [2/2] No watchdog PID file found.
    set WD_STOPPED=1
)

:: ── Summary ──────────────────────────────────────────────────────────────────

echo.
if !BOT_STOPPED! EQU 1 if !WD_STOPPED! EQU 1 (
    echo ============================================================
    echo  Bot and watchdog stopped successfully.
    echo ============================================================
) else (
    echo ============================================================
    echo [!] One or more processes may not have stopped cleanly.
    echo     Check Task Manager for remaining python.exe processes.
    echo ============================================================
)
echo.

endlocal
