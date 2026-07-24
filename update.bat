@echo off
setlocal

:: =============================================================================
:: MT5 Automated Forex Trading Bot — Update Script
:: =============================================================================
:: Safely pulls the latest code and restarts the bot.
::
:: PROCEDURE:
::   1. Stop the bot
::   2. git pull origin main
::   3. pip install -r requirements.txt  (picks up any new packages)
::   4. Run quick self-test
::   5. Start the bot
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

:: ── Step 1: Stop bot ─────────────────────────────────────────────────────────

echo [1/4] Stopping bot before update...
call stop_bot.bat

:: ── Step 2: Pull latest code ─────────────────────────────────────────────────

echo.
echo [2/4] Pulling latest code from GitHub...
git pull origin main
if errorlevel 1 (
    echo.
    echo [ERROR] git pull failed. Check your network connection or repository access.
    echo         The bot has been stopped. Run start_bot.bat when ready.
    pause
    exit /b 1
)
echo        Code updated successfully.

:: ── Step 3: Install new dependencies ────────────────────────────────────────

echo.
echo [3/4] Installing any new dependencies...
call venv\Scripts\activate.bat
venv\Scripts\pip.exe install -r requirements.txt --quiet
if errorlevel 1 (
    echo.
    echo [ERROR] pip install failed. Check requirements.txt and your network.
    echo         The bot has been stopped. Fix the issue and run update.bat again.
    pause
    exit /b 1
)
echo        Dependencies up to date.

:: ── Step 4: Quick self-test ──────────────────────────────────────────────────

echo.
echo [4/4] Running quick self-test after update...
venv\Scripts\pytest.exe tests\ -x -q --tb=short
if errorlevel 1 (
    echo.
    echo [!] Tests failed after update.
    echo     This may indicate a breaking change in the new code.
    echo     Review the test output above before restarting.
    echo.
    set /p CONT="  Restart the bot anyway? [y/n]: "
    if /i not "!CONT!"=="y" (
        echo  Update aborted. Run start_bot.bat manually when ready.
        pause
        exit /b 1
    )
) else (
    echo        All tests passed.
)

:: ── Step 5: Start bot with updated code ─────────────────────────────────────

echo.
echo [*] Starting bot with updated code...
call start_bot.bat

echo.
echo ============================================================
echo  Update complete.
echo ============================================================
echo.

endlocal
