@echo off
setlocal EnableDelayedExpansion

:: =============================================================================
:: MT5 Automated Forex Trading Bot — Self-Improver
:: =============================================================================
::
:: Runs the analytics + recommendation engine to analyze journal performance
:: and produce human-readable improvement suggestions.
::
:: The bot NEVER adjusts its own parameters automatically.
:: All output is advisory — human review and action required.
::
:: USAGE:
::   run_self_improver.bat              Run (respects cooldown interval)
::   run_self_improver.bat force        Force run now (ignore interval)
::   run_self_improver.bat snapshots    List all config snapshots
::   run_self_improver.bat changes      Show parameter change history
::   run_self_improver.bat restore <f>  Restore a config snapshot
::   run_self_improver.bat help         Show this menu
:: =============================================================================

title MT5 Bot — Self-Improver

echo.
echo ============================================================
echo  MT5 Automated Forex Trading Bot — Self-Improver
echo ============================================================
echo.

if not exist "venv\Scripts\activate.bat" (
    echo [ERROR] Virtual environment not found. Please run setup.bat first.
    echo.
    pause
    exit /b 1
)

if not exist ".env" (
    echo [ERROR] .env not found. Please run configure.bat first.
    echo.
    pause
    exit /b 1
)

call venv\Scripts\activate.bat

:: ── Parse sub-command ────────────────────────────────────────────────────────
set CMD=%~1
set ARG2=%~2

if /i "!CMD!"=="help"      goto :SHOW_HELP
if /i "!CMD!"=="force"     goto :RUN_FORCE
if /i "!CMD!"=="snapshots" goto :LIST_SNAPSHOTS
if /i "!CMD!"=="changes"   goto :SHOW_CHANGES
if /i "!CMD!"=="restore"   goto :RESTORE_SNAPSHOT
if "!CMD!"==""             goto :RUN_NORMAL

echo [ERROR] Unknown command: !CMD!
goto :SHOW_HELP

:: ── Normal run (respect cooldown) ────────────────────────────────────────────
:RUN_NORMAL
echo  Mode: Normal run (respects cooldown interval)
echo.
python -m app.analytics.performance_analytics
if errorlevel 1 (
    echo.
    echo [!] Analytics run failed. Check logs for details.
) else (
    echo.
    echo  Analysis complete. Review the output above.
    echo  Run with 'snapshots' to see saved config snapshots.
)
goto :DONE

:: ── Force run ────────────────────────────────────────────────────────────────
:RUN_FORCE
echo  Mode: Force run (ignoring cooldown interval)
echo.
python -m app.analytics.performance_analytics --force
if errorlevel 1 (
    echo.
    echo [!] Analytics run failed. Check logs for details.
) else (
    echo.
    echo  Force analysis complete. Review the output above.
)
goto :DONE

:: ── List snapshots ───────────────────────────────────────────────────────────
:LIST_SNAPSHOTS
echo  Listing config snapshots...
echo.
if exist "data\snapshots\" (
    dir /b /o-d "data\snapshots\*.json" 2>nul
    if errorlevel 1 echo   No snapshots found.
) else (
    echo   No snapshots directory found — run the self-improver first.
)
goto :DONE

:: ── Show change history ──────────────────────────────────────────────────────
:SHOW_CHANGES
echo  Parameter change history:
echo.
if exist "data\self_improver_changes.log" (
    type "data\self_improver_changes.log"
) else (
    echo   No change history found — no config changes have been suggested yet.
)
goto :DONE

:: ── Restore snapshot ────────────────────────────────────────────────────────
:RESTORE_SNAPSHOT
if "!ARG2!"=="" (
    echo [ERROR] Please provide the snapshot filename to restore.
    echo.
    echo  Usage: run_self_improver.bat restore data\snapshots\config_2026-07-25.json
    echo.
    echo  Available snapshots:
    if exist "data\snapshots\" (
        dir /b /o-d "data\snapshots\*.json" 2>nul
    )
    goto :DONE
)

if not exist "!ARG2!" (
    echo [ERROR] Snapshot file not found: !ARG2!
    goto :DONE
)

echo  Restoring snapshot: !ARG2!
echo.
set /p CONFIRM="  This will overwrite current .env settings. Continue? [y/n]: "
if /i "!CONFIRM!"=="y" (
    python -c "
import sys, json, pathlib
snap = json.loads(pathlib.Path(r'!ARG2!').read_text())
env_file = pathlib.Path('.env')
if env_file.exists():
    lines = env_file.read_text(encoding='utf-8').splitlines()
else:
    lines = []
for key, value in snap.items():
    updated = False
    for i, line in enumerate(lines):
        if line.startswith(key + '=') or line.startswith(key + ' ='):
            lines[i] = f'{key}={value}'
            updated = True
            break
    if not updated:
        lines.append(f'{key}={value}')
env_file.write_text('\n'.join(lines) + '\n', encoding='utf-8')
print(f'  Restored {len(snap)} settings from snapshot.')
"
    if errorlevel 1 (
        echo [ERROR] Restore failed.
    ) else (
        echo.
        echo  [OK] Snapshot restored. Restart the bot for changes to take effect.
        echo  Run: restart_bot.bat
    )
) else (
    echo  Cancelled — no changes made.
)
goto :DONE

:: ── Help ─────────────────────────────────────────────────────────────────────
:SHOW_HELP
echo  Usage:
echo    run_self_improver.bat              Run analytics (respects cooldown)
echo    run_self_improver.bat force        Force run now (ignore cooldown)
echo    run_self_improver.bat snapshots    List all config snapshots
echo    run_self_improver.bat changes      Show parameter change history log
echo    run_self_improver.bat restore ^<f^>  Restore a config snapshot file
echo    run_self_improver.bat help         Show this help menu
echo.
echo  Notes:
echo    - The self-improver NEVER automatically changes the bot's settings.
echo    - All suggestions are advisory only — human review required.
echo    - Snapshots are saved in data\snapshots\ before any restore.
echo.

:DONE
echo.
pause
endlocal
