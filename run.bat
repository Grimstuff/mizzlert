

@echo off
SETLOCAL EnableDelayedExpansion

REM ===== Activate venv =====
if exist .venv\Scripts\activate.bat (
    call .venv\Scripts\activate.bat
    set VENV_STATUS=Using virtual environment at: .venv
) else (
    set VENV_STATUS=WARNING: .venv not found, using system Python!
)

REM ===== HEADER =====
echo ===============================================
echo            Mizzlert Discord Bot
echo ===============================================
echo %VENV_STATUS%
echo Bot script: bot.py
echo Starting the Discord bot...
echo ------------------------------------------------
echo Date/Time: %DATE% %TIME%
echo ------------------------------------------------

REM Check Python installation
python --version > nul 2>&1
if errorlevel 1 (
    echo Python is not installed! Please install Python 3.10 or later from:
    echo https://www.python.org/downloads/
    echo.
    echo Make sure to check "Add Python to PATH" during installation.
    pause
    exit /b 1
)

python -c "import struct; print(struct.calcsize('P') * 8)" > arch.txt
set /p PYTHON_ARCH=<arch.txt
del arch.txt

if %PYTHON_ARCH% NEQ 64 (
    echo Warning: You have 32-bit Python installed. This bot requires 64-bit Python.
    echo Please install 64-bit Python from: https://www.python.org/downloads/
    echo Make sure to select "Windows installer (64-bit)"
    pause
    exit /b 1
)

REM Check for Visual C++ Build Tools
REG QUERY "HKEY_LOCAL_MACHINE\SOFTWARE\Microsoft\VisualStudio\14.0" > nul 2>&1
if errorlevel 1 (
    echo Visual C++ Build Tools are required but not installed.
    echo Opening download page...
    start "" "https://visualstudio.microsoft.com/visual-cpp-build-tools/"
    echo.
    echo Please install the "Desktop development with C++" workload
    echo After installation completes, run this script again.
    pause
    exit /b 1
)


REM Check if discord.py is installed
python -m pip show discord.py > nul 2>&1
if errorlevel 1 (
    echo.
    echo First time setup: Installing Python dependencies...
    python -m pip install --upgrade pip
    pip install discord.py
    pip install playwright
    python -m playwright install chromium
    echo.
    echo Dependencies installed successfully!
    echo.
)

echo Starting the bot...
python bot.py
pause
