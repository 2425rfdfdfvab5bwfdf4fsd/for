@echo off
setlocal EnableDelayedExpansion

:: =============================================================================
:: MT5 Automated Forex Trading Bot — Stop Script
:: =============================================================================
:: Gracefully stops the bot and watchdog processes using a three-method
:: fallback chain that handles every edge case on Windows 10 and 11.
::
:: Method 1 — PID File (Primary):
::   Reads the exact PID from data\bot.pid — instant, precise kill.
::
:: Method 2 — Window Title (Fallback):
::   Kills by the console window title set in autostart.bat / start_bot.bat.
::   Covers cases where the PID file was lost (crash, manual deletion).
::
:: Method 3 — Script-Name Filter (Last Resort):
::   Uses taskkill /FI filters instead of deprecated WMIC — works on all
::   Windows versions including Windows 11 builds where WMIC was removed.
::
:: Note on Task Scheduler:
::   stop_bot.bat kills the process, but if Task Scheduler "Restart on Failure"
::   is enabled it will relaunch up to 3 times.  To prevent restart after
::   stopping, also run: scripts\uninstall_autostart.ps1
:: =============================================================================

title MT5 Bot — Stopping

echo.
echo ============================================================
echo  MT5 Automated Forex Trading Bot — Stop
echo ============================================================
echo.

set BOT_STOPPED=0
set WD_STOPPED=0

:: ============================================================================
:: STOP MAIN BOT
:: ============================================================================

echo [1/2] Stopping bot...

:: ── Method 1: PID File ───────────────────────────────────────────────────────
set BOT_PID_FOUND=0
if exist "data\bot.pid" (
    set /p BOT_PID=<data\bot.pid
    if defined BOT_PID (
        tasklist /FI "PID eq !BOT_PID!" 2>nul | find "!BOT_PID!" >nul 2>&1
        if not errorlevel 1 (
            set BOT_PID_FOUND=1
            echo        Method 1: PID file — killing PID !BOT_PID!...
            taskkill /PID !BOT_PID! 2>nul

            :: Wait up to 10 seconds for graceful exit
            set WAIT=0
            :BOT_GRACEFUL_WAIT
            timeout /t 1 /nobreak >nul
            tasklist /FI "PID eq !BOT_PID!" 2>nul | find "!BOT_PID!" >nul 2>&1
            if errorlevel 1 (
                echo        Bot stopped cleanly ^(PID !BOT_PID!^).
                del "data\bot.pid" >nul 2>&1
                set BOT_STOPPED=1
                goto :BOT_DONE
            )
            set /a WAIT+=1
            if !WAIT! LSS 10 goto :BOT_GRACEFUL_WAIT

            :: Force kill if graceful exit timed out
            echo        Graceful stop timed out — force killing...
            taskkill /F /PID !BOT_PID! >nul 2>&1
            del "data\bot.pid" >nul 2>&1
            set BOT_STOPPED=1
            goto :BOT_DONE
        ) else (
            echo        PID !BOT_PID! not running — stale PID file removed.
            del "data\bot.pid" >nul 2>&1
            set BOT_STOPPED=1
            goto :BOT_DONE
        )
    )
)

:: ── Method 2: Window Title ───────────────────────────────────────────────────
if !BOT_PID_FOUND! EQU 0 (
    echo        Method 2: Window title search...
    set M2_FOUND=0
    for %%T in (
        "SMC Bot - AUTO-TRADE MODE"
        "MT5 Bot - Auto"
        "MT5 Bot — Starting"
        "MT5 Bot — Backtesting"
        "MT5 Bot — Setup"
    ) do (
        taskkill /F /FI "WINDOWTITLE eq %%~T" >nul 2>&1
        if not errorlevel 1 set M2_FOUND=1
    )
    if !M2_FOUND! EQU 1 (
        echo        Stopped by window title.
        del "data\bot.pid" >nul 2>&1
        set BOT_STOPPED=1
        goto :BOT_DONE
    )
)

:: ── Method 3: Script-Name Filter ────────────────────────────────────────────
:: Uses taskkill /FI — works on Windows 10 + 11 (no WMIC dependency)
echo        Method 3: Script-name filter...
set M3_FOUND=0
taskkill /F /FI "IMAGENAME eq python.exe" /FI "COMMANDLINE eq *main.py*" >nul 2>&1
if not errorlevel 1 set M3_FOUND=1
taskkill /F /FI "IMAGENAME eq python.exe" /FI "COMMANDLINE eq *main_manual.py*" >nul 2>&1
if not errorlevel 1 set M3_FOUND=1

if !M3_FOUND! EQU 1 (
    echo        Stopped by script-name filter.
    del "data\bot.pid" >nul 2>&1
    set BOT_STOPPED=1
) else (
    echo        No running bot process found — bot may already be stopped.
    del "data\bot.pid" >nul 2>&1
    set BOT_STOPPED=1
)

:BOT_DONE

:: ============================================================================
:: STOP WATCHDOG
:: ============================================================================

echo [2/2] Stopping watchdog...

if exist "data\watchdog.pid" (
    set /p WD_PID=<data\watchdog.pid
    if defined WD_PID (
        tasklist /FI "PID eq !WD_PID!" 2>nul | find "!WD_PID!" >nul 2>&1
        if not errorlevel 1 (
            echo        Killing watchdog PID !WD_PID!...
            taskkill /F /PID !WD_PID! >nul 2>&1
            echo        Watchdog stopped.
        ) else (
            echo        Watchdog PID !WD_PID! not running — stale file removed.
        )
    )
    del "data\watchdog.pid" >nul 2>&1
    set WD_STOPPED=1
) else (
    :: Fallback: kill any watchdog.py process by script name
    taskkill /F /FI "IMAGENAME eq python.exe" /FI "COMMANDLINE eq *watchdog.py*" >nul 2>&1
    echo        No watchdog PID file found — checked by script name.
    set WD_STOPPED=1
)

:: ============================================================================
:: SUMMARY
:: ============================================================================

echo.
if !BOT_STOPPED! EQU 1 if !WD_STOPPED! EQU 1 (
    echo ============================================================
    echo  Bot stopped successfully.
    echo ============================================================
    echo.
    echo  Note: If Task Scheduler auto-restart is enabled, the bot
    echo  may relaunch on next logon.  To disable autostart, run:
    echo    powershell -ExecutionPolicy Bypass -File scripts\uninstall_autostart.ps1
) else (
    echo ============================================================
    echo [!] One or more processes may not have stopped cleanly.
    echo     Check Task Manager for remaining python.exe processes.
    echo ============================================================
)
echo.

endlocal
