@echo off
title FZ-DB
cd /d "%~dp0"
if exist claves.bat (call claves.bat) else (echo  AVISO: no encontre claves.bat, el asistente IA no va a andar. Copia claves.ejemplo.bat como claves.bat.)
start "FZ-DB servidor" cmd /k py fzdb_server.py
timeout /t 3 >nul
echo.
echo Busca abajo el link https://....trycloudflare.com y pasaselo a tus amigos.
echo (Cierra esta ventana para dejar de compartir.)
echo.
cloudflared tunnel --url http://127.0.0.1:8765
pause
