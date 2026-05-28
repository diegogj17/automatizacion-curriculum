@echo off
chcp 65001 >nul
echo → Eliminando tarea programada...
schtasks /delete /tn "AutomatizacionCurriculum" /f >nul 2>&1
if errorlevel 1 (
    echo ⚠️  No se encontró la tarea (puede que no estuviera instalada)
) else (
    echo ✅ Tarea eliminada. El programa ya no se ejecutará automáticamente.
)
echo    (arrancar.bat sigue disponible para uso manual)
pause
