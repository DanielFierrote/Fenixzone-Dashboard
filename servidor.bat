@echo off
title FZ-DB servidor
cd /d "%~dp0"
if exist claves.bat call claves.bat
:inicio
py fzdb_server.py
if errorlevel 3 (
  timeout /t 1 >nul
  goto inicio
)
echo.
echo El servidor se detuvo. Si hubo un error, mira el mensaje de arriba.
pause
