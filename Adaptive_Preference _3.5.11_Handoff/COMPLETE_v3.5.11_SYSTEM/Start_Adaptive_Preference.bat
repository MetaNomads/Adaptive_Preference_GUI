@echo off
echo Initializing Adaptive Preference Testing System...

:: 1. Navigate to the project directory
cd /d "%~dp0"

:: 2. Activate the local virtual environment
:: This uses the private 'toolbox' created during installation
call .venv\Scripts\activate

:: 3. Start the Backend in the background
:: This runs the modified api.py which now uses SQLite
start /b python backend/api.py

:: 4. Wait for the server to initialize
timeout /t 3 /nobreak > nul

:: 5. Launch the interface in the default browser
start "" "http://127.0.0.1:5000/frontend/experimenter_dashboard_improved.html"

echo System is running. 
echo --------------------------------------------------
echo DO NOT CLOSE THIS WINDOW while using the app.
echo --------------------------------------------------
pause