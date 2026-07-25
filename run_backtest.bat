@echo off
setlocal EnableDelayedExpansion

:: =============================================================================
:: MT5 Automated Forex Trading Bot — Backtest Runner
:: =============================================================================
:: Prompts for backtest parameters and runs run_backtest.py.
:: Results are saved to data/reports/.
::
:: DISCLAIMER: Past performance does not guarantee future results.
:: =============================================================================

title MT5 Bot — Backtest

echo.
echo ============================================================
echo  MT5 Automated Forex Trading Bot — Backtest
echo ============================================================
echo  DISCLAIMER: Past performance does not guarantee future results.
echo ============================================================
echo.

if not exist "venv\Scripts\activate.bat" (
    echo [ERROR] Virtual environment not found. Please run setup.bat first.
    pause
    exit /b 1
)

call venv\Scripts\activate.bat

:: ── Prompt for parameters ────────────────────────────────────────────────────

set /p BT_SYMBOL="  Symbol(s) to backtest [EURUSDm GBPUSDm USDJPYm]: "
if "!BT_SYMBOL!"=="" set BT_SYMBOL=EURUSDm GBPUSDm USDJPYm

set /p BT_FROM="  Start date [YYYY-MM-DD, default 2026-01-01]: "
if "!BT_FROM!"=="" set BT_FROM=2026-01-01

set /p BT_TO="  End date   [YYYY-MM-DD, default 2026-07-25]: "
if "!BT_TO!"=="" set BT_TO=2026-07-25

set /p BT_CAPITAL="  Starting capital in USD [default 10000]: "
if "!BT_CAPITAL!"=="" set BT_CAPITAL=10000

:: ── Ask whether to force a fresh download from MT5 ───────────────────────────
echo.
echo  Download fresh data from MT5?
echo    Y = Always re-download from MT5 (use when changing the date range)
echo    N = Use cached data if it covers the requested window (faster)
echo.
set /p BT_FORCE="  Force fresh download? [Y/N, default N]: "
set BT_FORCE_FLAG=
if /i "!BT_FORCE!"=="Y" set BT_FORCE_FLAG=--force-download

set OUTPUT_DIR=data\reports
echo.
echo  Running backtest:
echo    Symbols:  !BT_SYMBOL!
echo    From:     !BT_FROM!
echo    To:       !BT_TO!
echo    Capital:  $!BT_CAPITAL!
echo    Output:   !OUTPUT_DIR!
if "!BT_FORCE_FLAG!"=="--force-download" echo    Mode:     FORCE RE-DOWNLOAD (cache bypassed)
echo.

python run_backtest.py --symbol !BT_SYMBOL! --from !BT_FROM! --to !BT_TO! --capital !BT_CAPITAL! --output !OUTPUT_DIR! !BT_FORCE_FLAG!

if errorlevel 1 (
    echo.
    echo [ERROR] Backtest failed. Check logs\app.log for details.
) else (
    echo.
    echo  Backtest complete. Reports saved to: !OUTPUT_DIR!
)

echo.
pause
endlocal
