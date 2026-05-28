@echo off
chcp 65001 >nul
:: ─────────────────────────────────────────────────────────────
::  Instalador Windows - ejecuta esto UNA sola vez
::  Instala dependencias y configura la tarea programada diaria
:: ─────────────────────────────────────────────────────────────

:: Ir a la raíz del proyecto
cd /d "%~dp0..\.."
set PROJECT_DIR=%CD%

echo ╔══════════════════════════════════════════════════╗
echo ║   Instalador - Automatización de Curriculum      ║
echo ╚══════════════════════════════════════════════════╝
echo.

:: 1. Comprobar Python
python --version >nul 2>&1
if errorlevel 1 (
    echo ❌ Python no encontrado.
    echo    Descárgalo desde: https://python.org/downloads
    echo    Marca "Add Python to PATH" durante la instalación.
    pause
    exit /b 1
)
echo ✅ Python encontrado

:: 2. Instalar dependencias
echo.
echo → Instalando dependencias Python...
python -m pip install --upgrade pip >nul 2>&1
python -m pip install PyYAML requests beautifulsoup4 lxml yagmail
if errorlevel 1 (
    echo ❌ Error instalando dependencias.
    pause
    exit /b 1
)
echo ✅ Dependencias instaladas

:: 3. Crear carpetas necesarias
echo.
echo → Creando carpetas...
if not exist "data" mkdir data
if not exist "logs" mkdir logs
echo ✅ Carpetas listas

:: 4. Registrar tarea programada diaria (9:30h lunes-viernes)
echo.
echo → Registrando tarea programada (9:30h lunes-viernes)...
schtasks /delete /tn "AutomatizacionCurriculum" /f >nul 2>&1
schtasks /create /tn "AutomatizacionCurriculum" ^
    /tr "python \"%PROJECT_DIR%\main.py\"" ^
    /sc weekly ^
    /d MON,TUE,WED,THU,FRI ^
    /st 09:30 ^
    /sd %date% ^
    /ru "%USERNAME%" ^
    /f >nul 2>&1

if errorlevel 1 (
    echo ⚠️  No se pudo registrar la tarea automática (puede requerir permisos de administrador)
    echo    Puedes usar arrancar.bat manualmente sin problema.
) else (
    echo ✅ Tarea programada instalada: se ejecutará cada día a las 9:30h
)

echo.
echo ╔══════════════════════════════════════════════════╗
echo ║  ✅ Instalación completada                       ║
echo ╠══════════════════════════════════════════════════╣
echo ║                                                  ║
echo ║  Doble clic en arrancar.bat → lanzar manual     ║
echo ║  Automático: cada día a las 9:30h               ║
echo ║  Logs en: logs\                                  ║
echo ║                                                  ║
echo ║  Para desinstalar la tarea automática:           ║
echo ║    desinstalar.bat                               ║
echo ╚══════════════════════════════════════════════════╝
echo.
pause
