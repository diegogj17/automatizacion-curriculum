@echo off
chcp 65001 >nul
:: ─────────────────────────────────────────────────────────────
::  Automatización de Curriculum - Lanzador manual (Windows)
::  Doble clic en este archivo para ejecutar el programa
:: ─────────────────────────────────────────────────────────────

:: Ir a la raíz del proyecto (dos niveles arriba de ejecutar\windows\)
cd /d "%~dp0..\.."

echo ╔══════════════════════════════════════════════════╗
echo ║       Automatización de Curriculum               ║
echo ╚══════════════════════════════════════════════════╝
echo.

:: Comprobar que Python está instalado
python --version >nul 2>&1
if errorlevel 1 (
    echo ❌ Python no encontrado. Instálalo desde https://python.org
    pause
    exit /b 1
)

:: Comprobar que Ollama está corriendo
curl -s http://localhost:11434/api/tags >nul 2>&1
if errorlevel 1 (
    echo ⚠️  Ollama no está corriendo. Ábrelo antes de continuar.
    echo    Descárgalo en: https://ollama.com
    pause
    exit /b 1
)

echo ✅ Ollama activo
echo.
echo ¿Qué quieres hacer?
echo   1) Pipeline completo (buscar + filtrar + enviar)
echo   2) Solo buscar empresas (sin enviar emails)
echo   3) Solo enviar emails (empresas ya en BD)
echo   4) Buscar emails en empresas de la BD (búsqueda exhaustiva)
echo   5) Ver estadísticas
echo   6) Probar conexión de email
echo.
set /p opcion="Elige una opción (1-6): "

if "%opcion%"=="1" (
    echo.
    echo 🚀 Iniciando pipeline completo...
    python main.py
) else if "%opcion%"=="2" (
    echo.
    echo 🔍 Buscando empresas (sin enviar emails)...
    python main.py --solo-buscar
) else if "%opcion%"=="3" (
    echo.
    echo 📬 Enviando emails a empresas pendientes...
    python main.py --solo-enviar
) else if "%opcion%"=="4" (
    echo.
    echo 📧 Buscando emails exhaustivamente en empresas de la BD...
    python main.py --buscar-emails
) else if "%opcion%"=="5" (
    echo.
    python main.py --estadisticas
) else if "%opcion%"=="6" (
    echo.
    python main.py --test-smtp
) else (
    echo Opción no válida.
)

echo.
echo ✅ Hecho.
pause
