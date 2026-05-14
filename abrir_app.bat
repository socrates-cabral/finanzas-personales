@echo off
title Finanzas Personales — Iniciando...
cd /d "C:\ClaudeWork\finanzas_personales\app"

:: Verificar si ya está corriendo en puerto 8503
netstat -an 2>nul | findstr ":8503" >nul
if %errorlevel%==0 (
    echo La app ya esta corriendo. Abriendo navegador...
    start "" "http://localhost:8503"
    exit /b 0
)

:: Iniciar Streamlit en segundo plano
start /min "" py -m streamlit run main.py --server.port 8503 --server.headless true --browser.gatherUsageStats false

:: Esperar a que arranque (5 segundos)
timeout /t 5 /nobreak >nul

:: Abrir navegador
start "" "http://localhost:8503"
