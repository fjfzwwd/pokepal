@echo off
chcp 65001 >nul
cd /d "%~dp0"
if exist "%~dp0.venv\Scripts\pythonw.exe" (
    start "" "%~dp0.venv\Scripts\pythonw.exe" main.py
) else (
    start "" pythonw main.py
)
