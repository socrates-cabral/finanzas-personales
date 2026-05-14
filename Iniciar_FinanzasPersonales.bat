@echo off
chcp 65001 > nul
title Finanzas Personales — Puerto 8503
echo.
echo ========================================
echo   FINANZAS PERSONALES — Iniciando...
echo   Puerto: 8503
echo   URL: http://localhost:8503
echo ========================================
echo.

cd /d "%~dp0app"

:: Abrir browser después de 3 segundos
start "" timeout /t 3 /nobreak > nul && start "" "http://localhost:8503"

:: Iniciar Streamlit
py -m streamlit run main.py --server.port 8503 --server.headless false --browser.gatherUsageStats false

pause
