@echo off
setlocal EnableDelayedExpansion

:: =============================================================================
:: MT5 Automated Forex Trading Bot — Setup Script
:: =============================================================================
:: Performs complete one-click installation on Windows 10/11.
:: Safe to run multiple times (idempotent).
::
:: USAGE:
::   Double-click setup.bat  — or run from a Command Prompt
::
:: REQUIREMENTS:
::   Python 3.11 or later must already be installed and on your PATH.
::   Download from: https://www.python.org/downloads/
:: =============================================================================

title MT5 Bot Setup

echo.
echo ============================================================
echo  MT5 Automated Forex Trading Bot — Setup
echo ============================================================
echo.

:: Collect results for the final summary
set PYTHON_OK=0
set VENV_OK=0
set DEPS_OK=0
set DIRS_OK=0
set DB_OK=0
set ENV_OK=0
set MT5_OK=0
set MT5_FOUND=0
set HEALTH_OK=0
set PREFLIGHT_OK=0

:: -------------------------------------------------------
:: STEP 1: Check Python version >= 3.11
:: -------------------------------------------------------
echo [1/8] Checking Python version...

python --version >nul 2>&1
if errorlevel 1 (
    echo.
    echo [ERROR] Python not found on your PATH.
    echo.
    echo  Please install Python 3.11 or later from:
    echo    https://www.python.org/downloads/
    echo.
    echo  During installation, tick "Add Python to PATH".
    echo.
    goto :SUMMARY
)

:: Extract major.minor and verify >= 3.11
for /f "tokens=2 delims= " %%v in ('python --version 2^>^&1') do set PYVER=%%v
for /f "tokens=1,2 delims=." %%a in ("!PYVER!") do (
    set PY_MAJOR=%%a
    set PY_MINOR=%%b
)

if !PY_MAJOR! LSS 3 (
    echo [ERROR] Python !PYVER! detected — version 3.11 or later is required.
    goto :SUMMARY
)
if !PY_MAJOR! EQU 3 if !PY_MINOR! LSS 11 (
    echo [ERROR] Python !PYVER! detected — version 3.11 or later is required.
    goto :SUMMARY
)

echo        Python !PYVER! detected — OK
set PYTHON_OK=1

:: -------------------------------------------------------
:: STEP 2: Create virtual environment if it doesn't exist
:: -------------------------------------------------------
echo [2/8] Setting up virtual environment...

if exist "venv\Scripts\activate.bat" (
    echo        Virtual environment already exists — skipping creation
) else (
    python -m venv venv
    if errorlevel 1 (
        echo [ERROR] Failed to create virtual environment.
        goto :SUMMARY
    )
    echo        Virtual environment created
)
set VENV_OK=1

:: -------------------------------------------------------
:: STEP 3: Activate venv
:: -------------------------------------------------------
call venv\Scripts\activate.bat
if errorlevel 1 (
    echo [ERROR] Failed to activate virtual environment.
    goto :SUMMARY
)

:: -------------------------------------------------------
:: STEP 4: Upgrade pip
:: -------------------------------------------------------
echo [3/8] Upgrading pip...
python -m pip install --upgrade pip --quiet
if errorlevel 1 (
    echo [WARNING] pip upgrade failed — continuing with current version
)

:: -------------------------------------------------------
:: STEP 5: Install requirements.txt
:: -------------------------------------------------------
echo [4/8] Installing dependencies from requirements.txt...

if not exist "requirements.txt" (
    echo [ERROR] requirements.txt not found in this directory.
    goto :SUMMARY
)

python -m pip install -r requirements.txt --quiet
if errorlevel 1 (
    echo [ERROR] Dependency installation failed.
    echo.
    echo  Try running manually to see errors:
    echo    venv\Scripts\activate
    echo    pip install -r requirements.txt
    echo.
) else (
    echo        Dependencies installed
    set DEPS_OK=1
)

:: -------------------------------------------------------
:: STEP 6: Create required directories
:: -------------------------------------------------------
echo [5/8] Creating required directories...

set DIRS=data logs data\historical data\screenshots data\reports backups

for %%d in (%DIRS%) do (
    if not exist "%%d" (
        mkdir "%%d"
    )
)

:: Create .gitkeep files so empty directories are tracked in git
for %%d in (data\historical data\screenshots data\reports logs backups) do (
    if not exist "%%d\.gitkeep" (
        type nul > "%%d\.gitkeep"
    )
)

echo        Directories ready
set DIRS_OK=1

:: -------------------------------------------------------
:: STEP 7: Initialise SQLite database
:: -------------------------------------------------------
echo [6/8] Initialising database...

python scripts\init_db.py
if errorlevel 1 (
    echo [WARNING] Database initialisation failed — check scripts\init_db.py
) else (
    echo        Database initialised
    set DB_OK=1
)

:: -------------------------------------------------------
:: STEP 8: Copy .env.example to .env if not present
:: -------------------------------------------------------
echo [7/8] Checking environment configuration...

if exist ".env" (
    echo        .env already exists — not overwriting
) else (
    if exist ".env.example" (
        copy ".env.example" ".env" >nul
        echo        .env created from .env.example — please edit it with your credentials
    ) else (
        echo [WARNING] .env.example not found — .env not created
    )
)
set ENV_OK=1

:: -------------------------------------------------------
:: STEP 9: Check MT5 Python package
:: -------------------------------------------------------
echo.
echo --- MetaTrader 5 Checks ---
echo [*] Checking MT5 Python package...

python -c "import MetaTrader5; print('MT5 package OK')" >nul 2>&1
if errorlevel 1 (
    echo [!] MT5 Python package not installed
    echo     This is expected if you have not yet run:  pip install MetaTrader5
    echo     The package is Windows-only and will be installed with requirements.txt
    echo     on your broker-connected Windows PC.
) else (
    echo     MT5 Python package found
    set MT5_OK=1
)

:: -------------------------------------------------------
:: STEP 10: Check MT5 terminal executable
:: -------------------------------------------------------
echo [*] Checking for MT5 terminal...

set MT5_FOUND=0
if exist "C:\Program Files\MetaTrader 5\terminal64.exe" (
    echo     MT5 terminal found: C:\Program Files\MetaTrader 5\terminal64.exe
    set MT5_FOUND=1
)
if exist "C:\Program Files (x86)\MetaTrader 5\terminal64.exe" (
    echo     MT5 terminal found: C:\Program Files (x86^)\MetaTrader 5\terminal64.exe
    set MT5_FOUND=1
)
if !MT5_FOUND! EQU 0 (
    echo [!] MT5 terminal not found in default locations
    echo     Download and install from: https://www.metatrader5.com/en/download
    echo     Then set MT5_TERMINAL_PATH in your .env file.
)

:: -------------------------------------------------------
:: STEP 11: Run pre-flight safety check
:: -------------------------------------------------------
echo [7/8] Running pre-flight safety check...

python scripts\preflight_check.py
if errorlevel 1 (
    echo [WARNING] Pre-flight check reported issues — review output above
    echo          Run 'python scripts\preflight_check.py' for details.
) else (
    set PREFLIGHT_OK=1
)

:: -------------------------------------------------------
:: STEP 12: Run health check
:: -------------------------------------------------------
echo [8/8] Running health check...

python scripts\health_check.py
if errorlevel 1 (
    echo [WARNING] Health check reported issues — review output above
) else (
    set HEALTH_OK=1
)

:: -------------------------------------------------------
:: SUMMARY
:: -------------------------------------------------------
:SUMMARY
echo.
echo ============================================================
echo  SETUP COMPLETE
echo ============================================================
echo.

if !PYTHON_OK! EQU 1 (
    echo  [OK] Python !PYVER! detected
) else (
    echo  [!!] Python 3.11+ not found — install from python.org
)

if !VENV_OK! EQU 1 (
    echo  [OK] Virtual environment ready ^(venv\^)
) else (
    echo  [!!] Virtual environment not created
)

if !DEPS_OK! EQU 1 (
    echo  [OK] Dependencies installed
) else (
    echo  [!!] Dependency installation failed — run: pip install -r requirements.txt
)

if !DIRS_OK! EQU 1 (
    echo  [OK] Required directories created
) else (
    echo  [!!] Directory creation failed
)

if !DB_OK! EQU 1 (
    echo  [OK] Database initialised
) else (
    echo  [!!] Database not initialised — run: python scripts\init_db.py
)

if !ENV_OK! EQU 1 (
    if exist ".env" (
        echo  [OK] .env file ready
    ) else (
        echo  [!!] .env file missing — copy .env.example to .env and configure it
    )
) else (
    echo  [!!] .env setup failed
)

if !MT5_OK! EQU 1 (
    echo  [OK] MT5 Python package installed
) else (
    echo  [!] MT5 Python package not found ^(install MetaTrader5 on Windows^)
)

if !MT5_FOUND! EQU 1 (
    echo  [OK] MT5 terminal found
) else (
    echo  [!] MT5 terminal not found — install from https://www.metatrader5.com
)

if !PREFLIGHT_OK! EQU 1 (
    echo  [OK] Pre-flight safety check passed
) else (
    echo  [!] Pre-flight check reported warnings — run: python scripts\preflight_check.py
)

if !HEALTH_OK! EQU 1 (
    echo  [OK] Health check passed
) else (
    echo  [!] Health check reported warnings
)

echo.
echo  NEXT STEPS:
echo    1. Edit .env with your MT5 credentials and settings
echo    2. Run: configure.bat
echo    3. Run: start_bot.bat
echo.
echo ============================================================
echo.
pause
endlocal
