@echo off
setlocal EnableDelayedExpansion

:: =============================================================================
:: MT5 Automated Forex Trading Bot — Configuration Wizard
:: =============================================================================
:: Guides the user through interactive configuration of all bot settings.
:: Reads existing .env values as defaults; writes validated settings to .env.
::
:: USAGE:
::   Run configure.bat after setup.bat has completed successfully.
:: =============================================================================

title MT5 Bot Configuration

echo.
echo ============================================================
echo  MT5 Automated Forex Trading Bot — Configuration Wizard
echo ============================================================
echo.

:: Check that setup has been run (venv must exist)
if not exist "venv\Scripts\activate.bat" (
    echo [ERROR] Virtual environment not found.
    echo         Please run setup.bat first.
    echo.
    pause
    exit /b 1
)

:: Activate virtual environment
call venv\Scripts\activate.bat
if errorlevel 1 (
    echo [ERROR] Failed to activate virtual environment.
    pause
    exit /b 1
)

:: Ensure .env exists (copy from example if needed)
if not exist ".env" (
    if exist ".env.example" (
        copy ".env.example" ".env" >nul
        echo [INFO] Created .env from .env.example
    ) else (
        echo [ERROR] .env.example not found. Please re-run setup.bat.
        pause
        exit /b 1
    )
)

echo  Starting interactive configuration wizard...
echo  (Press Enter to accept the default value shown in [brackets])
echo.

python scripts\setup_wizard.py
set WIZARD_EXIT=%ERRORLEVEL%

if %WIZARD_EXIT% EQU 0 (
    echo.
    echo ============================================================
    echo  Configuration saved successfully.
    echo.
    echo  NEXT STEPS:
    echo    Run: start_bot.bat
    echo ============================================================
) else if %WIZARD_EXIT% EQU 2 (
    echo.
    echo  Configuration cancelled — no changes were saved.
) else (
    echo.
    echo [ERROR] Configuration wizard failed ^(exit code: %WIZARD_EXIT%^).
    echo         Check that Python and all dependencies are installed.
)

echo.
pause
endlocal
