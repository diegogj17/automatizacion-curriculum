#!/bin/zsh
# Desinstalador - elimina la ejecución automática diaria

PLIST_NAME="com.diego.automatizacion-curriculum.plist"
LAUNCH_AGENTS="$HOME/Library/LaunchAgents"

echo "→ Desinstalando ejecución automática..."
launchctl unload "$LAUNCH_AGENTS/$PLIST_NAME" 2>/dev/null
rm -f "$LAUNCH_AGENTS/$PLIST_NAME"
echo "✅ Desinstalado. El programa ya no se ejecutará automáticamente."
echo "   (El archivo arrancar.command sigue disponible para uso manual)"
read "?Pulsa Enter para cerrar..."
