@echo off
setlocal EnableDelayedExpansion

:: =============================================================================
:: MT5 Automated Forex Trading Bot — Update Script
:: =============================================================================
:: Safely updates the bot to a newer version.
::
:: PROCEDURE:
::   1. Stop the bot gracefully
::   2. Back up data/ and .env to backups/{timestamp}/
::   3. Pull latest code (git pull origin main)
::   4. Install updated dependencies (pip install -r requirements.txt)
::   5. Run database migrations (scripts/migrate_db.py)
::   6. Run self-test (pytest tests/ -x -q)
::   7a. Tests pass  → print SUCCESS, offer to restart bot
::   7b. Tests fail  → restore backup, print FAILURE, exit without restarting
:: =============================================================================

title MT5 Bot — Update

echo.
echo ============================================================
echo  MT5 Automated Forex Trading Bot — Update
echo ============================================================
echo.

if not exist "venv\Scripts\activate.bat" (
    echo [ERROR] Virtual environment not found. Please run setup.bat first.
    pause
    exit /b 1
)

set PYTHON_EXE=venv\Scripts\python.exe
set BACKUP_DIR=

:: ── Step 1: Stop bot ─────────────────────────────────────────────────────────

echo [1/6] Stopping bot before update...
call stop_bot.bat
echo.

:: ── Step 2: Backup ───────────────────────────────────────────────────────────

echo [2/6] Creating backup of data/ and .env...
for /f "delims=" %%d in ('"%PYTHON_EXE%" scripts\backup.py --create 2^>nul') do set BACKUP_DIR=%%d

if "!BACKUP_DIR!"=="" (
    echo [ERROR] Backup failed. Update aborted — no changes made.
    echo         Check that scripts\backup.py exists and Python is working.
    pause
    exit /b 1
)
echo        Backup created: !BACKUP_DIR!
echo.

:: ── Step 3: Pull latest code ─────────────────────────────────────────────────

echo [3/6] Pulling latest code from GitHub...
git pull origin main
if errorlevel 1 (
    echo.
    echo [ERROR] git pull failed. Restoring backup...
    "%PYTHON_EXE%" scripts\backup.py --restore "!BACKUP_DIR!"
    echo         Check your network connection or repository access.
    pause
    exit /b 1
)
echo        Code updated successfully.
echo.

:: ── Step 4: Install updated dependencies ─────────────────────────────────────

echo [4/6] Installing updated dependencies...
call venv\Scripts\activate.bat
venv\Scripts\pip.exe install -r requirements.txt --quiet
if errorlevel 1 (
    echo.
    echo [ERROR] pip install failed. Restoring backup...
    "%PYTHON_EXE%" scripts\backup.py --restore "!BACKUP_DIR!"
    echo         Fix requirements.txt or network, then run update.bat again.
    pause
    exit /b 1
)
echo        Dependencies up to date.
echo.

:: ── Step 5: Database migrations ──────────────────────────────────────────────

echo [5/6] Running database migrations...
"%PYTHON_EXE%" scripts\migrate_db.py
if errorlevel 1 (
    echo.
    echo [ERROR] Database migration failed. Restoring backup...
    "%PYTHON_EXE%" scripts\backup.py --restore "!BACKUP_DIR!"
    pause
    exit /b 1
)
echo.

:: ── Step 6: Self-test ────────────────────────────────────────────────────────

echo [6/6] Running self-test after update...
venv\Scripts\pytest.exe tests\ -x -q --tb=short
if errorlevel 1 (
    echo.
    echo ============================================================
    echo [!] TESTS FAILED — Update rolled back
    echo ============================================================
    echo.
    echo  Restoring data/ and .env from backup...
    "%PYTHON_EXE%" scripts\backup.py --restore "!BACKUP_DIR!"
    echo.
    echo  The code has been updated but data has been restored.
    echo  Review the test output above, fix the issue, and run
    echo  update.bat again.
    echo.
    echo  Backup location: !BACKUP_DIR!
    echo.
    pause
    exit /b 1
)
echo        All tests passed.
echo.

:: ── Step 7: Offer restart ────────────────────────────────────────────────────

echo ============================================================
echo  UPDATE SUCCESSFUL
echo ============================================================
echo  Backup retained at: !BACKUP_DIR!
echo.

set /p START_NOW="  Start the bot now? [y/n]: "
if /i "!START_NOW!"=="y" (
    echo.
    echo  Starting bot with updated code...
    call start_bot.bat
) else (
    echo.
    echo  Update complete. Run start_bot.bat when ready.
)

echo.
echo ============================================================
echo  Update complete.
echo ============================================================
echo.

endlocal
