@echo off
chcp 65001 >nul
title Instalador — App Finanzas Personales

echo.
echo ══════════════════════════════════════════════════════
echo    INSTALADOR — App Finanzas Personales
echo    Socrates Cabral — 2026
echo ══════════════════════════════════════════════════════
echo.

:: ── 1. Verificar Python ───────────────────────────────────────────────────────
echo [1/7] Verificando Python...
py --version >nul 2>&1
if %errorlevel% neq 0 (
    echo     ERROR: Python no encontrado.
    echo     Descarga Python desde https://python.org ^(marcar "Add to PATH"^)
    pause
    exit /b 1
)
py --version
echo     OK

:: ── 2. Verificar / clonar repositorio ────────────────────────────────────────
echo.
echo [2/7] Verificando repositorio en C:\ClaudeWork...
if exist "C:\ClaudeWork\.git" (
    echo     Repositorio ya existe. Actualizando...
    cd /d "C:\ClaudeWork"
    git pull origin main
) else (
    echo     Clonando repositorio privado...
    git clone https://github.com/socrates-cabral/ClaudeWork- "C:\ClaudeWork"
    if %errorlevel% neq 0 (
        echo     ERROR: No se pudo clonar. Verifica acceso a GitHub.
        pause
        exit /b 1
    )
)
echo     OK

:: ── 3. Instalar dependencias Python ──────────────────────────────────────────
echo.
echo [3/7] Instalando dependencias Python...
cd /d "C:\ClaudeWork"
py -m pip install --upgrade pip --quiet
py -m pip install -r finanzas_personales\app\requirements.txt --quiet
if %errorlevel% neq 0 (
    echo     ERROR: Fallo al instalar dependencias.
    pause
    exit /b 1
)
echo     OK

:: ── 4. Instalar Playwright y Chromium ────────────────────────────────────────
echo.
echo [4/7] Instalando Playwright + Chromium ^(puede tardar unos minutos^)...
py -m pip install playwright --quiet
py -m playwright install chromium
echo     OK

:: ── 5. Verificar archivos privados ───────────────────────────────────────────
echo.
echo [5/7] Verificando archivos privados...
set MISSING=0

if not exist "C:\ClaudeWork\.env" (
    echo     FALTA: C:\ClaudeWork\.env
    echo     → Copia el archivo .env desde el PC de Egakat via USB
    set MISSING=1
)

if not exist "C:\ClaudeWork\Plantilla-para-controlar-gastos.xlsm" (
    echo     FALTA: Plantilla-para-controlar-gastos.xlsm
    echo     → Copia el Excel desde el PC de Egakat via USB
    set MISSING=1
)

if %MISSING%==0 (
    echo     Todos los archivos privados presentes. OK
) else (
    echo.
    echo     IMPORTANTE: Copia los archivos faltantes y vuelve a ejecutar este script.
    echo     Sin esos archivos la app no funcionara correctamente.
)

:: ── 6. Crear icono personalizado ─────────────────────────────────────────────
echo.
echo [6/7] Creando icono de la app...
py -c "
from PIL import Image, ImageDraw, ImageFont
import os

sizes = [256, 128, 64, 48, 32, 16]
images = []
for size in sizes:
    img = Image.new('RGBA', (size, size), (0,0,0,0))
    draw = ImageDraw.Draw(img)
    margin = int(size * 0.04)
    draw.ellipse([margin, margin, size-margin, size-margin], fill='#0F172A')
    border = int(size * 0.05)
    draw.ellipse([margin, margin, size-margin, size-margin], outline='#14B8A6', width=border)
    font_size = int(size * 0.55)
    try:
        font = ImageFont.truetype(r'C:\Windows\Fonts\arialbd.ttf', font_size)
    except:
        font = ImageFont.load_default()
    text = '$'
    bbox = draw.textbbox((0,0), text, font=font)
    tw, th = bbox[2]-bbox[0], bbox[3]-bbox[1]
    x = (size - tw) / 2 - bbox[0]
    y = (size - th) / 2 - bbox[1] - size*0.04
    draw.text((x, y), text, fill='#14B8A6', font=font)
    images.append(img)
ico_path = r'C:\ClaudeWork\finanzas_personales\finanzas.ico'
images[0].save(ico_path, format='ICO', sizes=[(s,s) for s in sizes], append_images=images[1:])
print('Icono creado.')
"

:: ── 7. Crear acceso directo en escritorio ────────────────────────────────────
echo.
echo [7/7] Creando acceso directo en el Escritorio...
py -c "
from win32com.client import Dispatch
import winreg, os
try:
    key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r'Software\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders')
    desktop = winreg.QueryValueEx(key, 'Desktop')[0]
except:
    desktop = os.path.join(os.path.expanduser('~'), 'Desktop')
shell = Dispatch('WScript.Shell')
shortcut = shell.CreateShortCut(os.path.join(desktop, 'Finanzas Personales.lnk'))
shortcut.Targetpath = r'C:\ClaudeWork\finanzas_personales\abrir_app_silencioso.vbs'
shortcut.WorkingDirectory = r'C:\ClaudeWork\finanzas_personales'
shortcut.Description = 'Abrir app Finanzas Personales'
shortcut.IconLocation = r'C:\ClaudeWork\finanzas_personales\finanzas.ico,0'
shortcut.save()
print('Acceso directo creado en:', desktop)
"

:: ── Resumen final ────────────────────────────────────────────────────────────
echo.
echo ══════════════════════════════════════════════════════
echo    INSTALACION COMPLETADA
echo ══════════════════════════════════════════════════════
echo.
echo    Para abrir la app: doble clic en "Finanzas Personales" del Escritorio
echo    O ejecutar manualmente:
echo    py -m streamlit run C:\ClaudeWork\finanzas_personales\app\main.py --server.port 8503
echo.
if %MISSING%==1 (
    echo    PENDIENTE: Copiar .env y Excel via USB desde PC Egakat
    echo.
)
pause
