@echo off
TITLE Adaptive Preference - Auto Installer
COLOR 0A

echo ==================================================
echo      ADAPTIVE PREFERENCE - SILENT LAUNCHER
echo ==================================================
echo.

:: ----------------------------------------------------
:: STEP 1: CHECK PYTHON
:: ----------------------------------------------------
echo [1/4] Checking Python...
python --version >nul 2>&1
IF %ERRORLEVEL% EQU 0 GOTO FOUND_PYTHON

echo       Checking 'py' launcher...
py --version >nul 2>&1
IF %ERRORLEVEL% EQU 0 GOTO FOUND_PYTHON

echo       [MISSING] Python not found. Installing...
winget install -e --id Python.Python.3.11 --accept-source-agreements --accept-package-agreements
GOTO CHECK_NODE

:FOUND_PYTHON
echo       [OK] Python is ready.

:: ----------------------------------------------------
:: STEP 2: CHECK NODE.JS
:: ----------------------------------------------------
:CHECK_NODE
echo.
echo [2/4] Checking Node.js...
node -v >nul 2>&1
IF %ERRORLEVEL% EQU 0 GOTO FOUND_NODE

echo       [MISSING] Node.js not found. Installing...
winget install -e --id OpenJS.NodeJS --accept-source-agreements --accept-package-agreements
set "PATH=%PATH%;C:\Program Files\nodejs\"
GOTO CHECK_LIBRARIES

:FOUND_NODE
echo       [OK] Node.js is ready.

:: ----------------------------------------------------
:: STEP 3: INSTALL LIBRARIES
:: ----------------------------------------------------
:CHECK_LIBRARIES
echo.
echo [3/4] Checking Libraries...

IF EXIST "node_modules\" GOTO CHECK_VENV
echo       - Installing JavaScript packages...
call npm install
IF %ERRORLEVEL% NEQ 0 (
    COLOR 0C
    echo [ERROR] npm install failed.
    pause
    exit /b
)

:CHECK_VENV
IF EXIST "venv\" GOTO START_APP
echo       - Creating Python Virtual Environment...
python -m venv venv >nul 2>&1
IF %ERRORLEVEL% NEQ 0 py -m venv venv

echo       - Activating Environment...
call venv\Scripts\activate

echo       - Installing Python requirements...
pip install -r requirements.txt
IF %ERRORLEVEL% NEQ 0 (
    COLOR 0C
    echo [ERROR] Python install failed.
    pause
    exit /b
)

:: ----------------------------------------------------
:: STEP 4: SILENT LAUNCH
:: ----------------------------------------------------
:START_APP
echo.
echo [4/4] Launching App Silently...
echo ==================================================

:: 1. Activate venv
if exist "venv\Scripts\activate" call venv\Scripts\activate

:: 2. Create a temporary invisible launcher script
echo Set WshShell = CreateObject("WScript.Shell") > launch_invisible.vbs
echo WshShell.Run "cmd /c npm start", 0 >> launch_invisible.vbs
echo Set WshShell = Nothing >> launch_invisible.vbs

:: 3. Run the invisible launcher
wscript launch_invisible.vbs

:: 4. Clean up and close this window immediately
timeout /t 1 >nul
del launch_invisible.vbs
exit