@echo off
setlocal

:: =============================================================================
:: MT5 Automated Forex Trading Bot — Restart Script
:: =============================================================================
:: Stops the bot and watchdog, waits 5 seconds, then starts them again.
:: =============================================================================

title MT5 Bot — Restarting

echo.
echo ============================================================
echo  MT5 Automated Forex Trading Bot — Restart
echo ============================================================
echo.

echo  Stopping bot...
call stop_bot.bat

echo.
echo  Waiting 5 seconds before restart...
timeout /t 5 /nobreak >nul

echo.
echo  Starting bot...
call start_bot.bat

endlocal
