@echo off
setlocal

:: =============================================================================
:: MT5 Automated Forex Trading Bot — Test Runner
:: =============================================================================
:: Runs the full pytest test suite.
:: All tests use mocked MT5 — no live connection required.
:: =============================================================================

title MT5 Bot — Tests

echo.
echo ============================================================
echo  MT5 Automated Forex Trading Bot — Test Suite
echo ============================================================
echo.

if not exist "venv\Scripts\activate.bat" (
    echo [ERROR] Virtual environment not found. Please run setup.bat first.
    pause
    exit /b 1
)

call venv\Scripts\activate.bat

echo  Running full test suite...
echo  (All MT5 calls are mocked — no live connection needed)
echo.

venv\Scripts\pytest.exe tests\ -v --tb=short 2>&1

if errorlevel 1 (
    echo.
    echo [!] Some tests failed. Review output above.
) else (
    echo.
    echo  All tests passed.
)

echo.
pause
endlocal
