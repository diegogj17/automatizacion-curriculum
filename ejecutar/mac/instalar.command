#!/bin/zsh
# ─────────────────────────────────────────────────────────────
#  Instalador - ejecuta esto UNA sola vez
#  Registra el programa para que corra solo cada día a las 9:30
# ─────────────────────────────────────────────────────────────

# Detectar la raíz del proyecto (dos niveles arriba de ejecutar/mac/)
PROJECT_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
PLIST_NAME="com.diego.automatizacion-curriculum.plist"
LAUNCH_AGENTS="$HOME/Library/LaunchAgents"

echo "╔══════════════════════════════════════════════════╗"
echo "║     Instalador - Automatización de Curriculum    ║"
echo "╚══════════════════════════════════════════════════╝"
echo ""

# 1. Permisos de ejecución al lanzador
echo "→ Dando permisos de ejecución al lanzador..."
chmod +x "$PROJECT_DIR/arrancar.command"
echo "  ✅ arrancar.command listo para doble clic"

# 2. Instalar Launch Agent (ejecución automática diaria)
echo ""
echo "→ Instalando ejecución automática diaria (9:30h lunes-viernes)..."
mkdir -p "$LAUNCH_AGENTS"

# Generar el plist con la ruta real del proyecto en este ordenador
cat > "$LAUNCH_AGENTS/$PLIST_NAME" << EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.diego.automatizacion-curriculum</string>
    <key>ProgramArguments</key>
    <array>
        <string>/usr/bin/python3</string>
        <string>$PROJECT_DIR/main.py</string>
    </array>
    <key>WorkingDirectory</key>
    <string>$PROJECT_DIR</string>
    <key>StartCalendarInterval</key>
    <dict>
        <key>Hour</key>
        <integer>9</integer>
        <key>Minute</key>
        <integer>30</integer>
    </dict>
    <key>StandardOutPath</key>
    <string>$PROJECT_DIR/logs/launchd_out.log</string>
    <key>StandardErrorPath</key>
    <string>$PROJECT_DIR/logs/launchd_err.log</string>
    <key>RunAtLoad</key>
    <false/>
</dict>
</plist>
EOF
launchctl unload "$LAUNCH_AGENTS/$PLIST_NAME" 2>/dev/null
launchctl load "$LAUNCH_AGENTS/$PLIST_NAME"

if launchctl list | grep -q "com.diego.automatizacion-curriculum"; then
    echo "  ✅ Launch Agent instalado correctamente"
else
    echo "  ⚠️  No se pudo verificar el Launch Agent (puede ser normal en macOS recientes)"
fi

# 3. Crear carpeta de logs si no existe
mkdir -p "$PROJECT_DIR/logs"

echo ""
echo "╔══════════════════════════════════════════════════╗"
echo "║  ✅ Instalación completada                       ║"
echo "╠══════════════════════════════════════════════════╣"
echo "║                                                  ║"
echo "║  Doble clic en arrancar.command → lanzar manual ║"
echo "║  Automático: cada día a las 9:30h               ║"
echo "║  Logs en: logs/                                  ║"
echo "║                                                  ║"
echo "║  Para desinstalar la ejecución automática:       ║"
echo "║    sh desinstalar.command                        ║"
echo "╚══════════════════════════════════════════════════╝"
echo ""
read "?Pulsa Enter para cerrar..."
