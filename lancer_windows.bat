@echo off
cd /d "%~dp0"
where py >nul 2>nul
if errorlevel 1 (
 echo Python 3.11 ou superieur est requis. Installez Python puis relancez ce fichier.
 pause
 exit /b 1
)
if not exist .venv\Scripts\python.exe py -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 (
 pause
 exit /b 1
)
.venv\Scripts\python.exe -m streamlit run app.py --server.address=localhost
pause
