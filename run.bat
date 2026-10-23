@echo off
title ORBITAL - Launching Mission Telemetry System
cd /d "%~dp0"

echo ===================================================
echo   ORBITAL: Autonomous Mission Telemetry System
echo ===================================================

:: Check if .venv python exists and works on this machine
if exist .venv\Scripts\python.exe (
    .venv\Scripts\python.exe -c "import sys" >nul 2>&1
    if %errorlevel% equ 0 goto RUN_APP
)

echo [!] Virtual environment not found or created on another computer.
echo [*] Setting up local .venv for this machine...
python -m venv .venv
if %errorlevel% neq 0 (
    echo [ERROR] Python is not installed or not added to your system PATH.
    echo Please install Python 3.10+ from python.org and try again.
    pause
    exit /b 1
)

echo [*] Installing dependencies from requirements.txt...
.\.venv\Scripts\pip.exe install -r requirements.txt
if %errorlevel% neq 0 (
    echo [ERROR] Failed to install dependencies.
    pause
    exit /b 1
)

:RUN_APP
echo [*] Launching ORBITAL...
.\.venv\Scripts\python.exe main.py
if %errorlevel% neq 0 (
    echo.
    echo [!] Application exited with an error.
    echo Please ensure PostgreSQL is running and the password in .env matches.
    pause
)
