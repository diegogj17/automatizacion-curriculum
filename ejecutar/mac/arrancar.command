#!/bin/zsh
# ─────────────────────────────────────────────────────────────
#  Automatización de Curriculum - Lanzador manual
#  Doble clic en este archivo para ejecutar el programa
# ─────────────────────────────────────────────────────────────

# Detectar la raíz del proyecto (dos niveles arriba de ejecutar/mac/)
PROJECT_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
PYTHON="/usr/bin/python3"
LOG_DIR="$PROJECT_DIR/logs"

# Ir a la carpeta del proyecto
cd "$PROJECT_DIR"

echo "╔══════════════════════════════════════════════════╗"
echo "║       Automatización de Curriculum               ║"
echo "╚══════════════════════════════════════════════════╝"
echo ""

# Comprobar que Ollama está corriendo
if ! curl -s http://localhost:11434/api/tags > /dev/null 2>&1; then
    echo "⚠️  Ollama no está corriendo. Iniciándolo..."
    open -a Ollama
    echo "   Esperando 5 segundos..."
    sleep 5
fi

echo "✅ Ollama activo"
echo ""
echo "¿Qué quieres hacer?"
echo "  1) Pipeline completo (buscar + filtrar + enviar)"
echo "  2) Solo buscar empresas (sin enviar emails)"
echo "  3) Solo enviar emails (empresas ya en BD)"
echo "  4) Buscar emails en empresas de la BD (búsqueda exhaustiva)"
echo "  5) Ver estadísticas"
echo "  6) Probar conexión de email"
echo ""
read "opcion?Elige una opción (1-6): "

case $opcion in
    1)
        echo ""
        echo "🚀 Iniciando pipeline completo..."
        $PYTHON main.py
        ;;
    2)
        echo ""
        echo "🔍 Buscando empresas (sin enviar emails)..."
        $PYTHON main.py --solo-buscar
        ;;
    3)
        echo ""
        echo "📬 Enviando emails a empresas pendientes..."
        $PYTHON main.py --solo-enviar
        ;;
    4)
        echo ""
        echo "📧 Buscando emails exhaustivamente en empresas de la BD..."
        echo "   (Visita la web de cada empresa para encontrar su email de contacto)"
        $PYTHON main.py --buscar-emails
        ;;
    5)
        echo ""
        $PYTHON main.py --estadisticas
        ;;
    6)
        echo ""
        $PYTHON main.py --test-smtp
        ;;
    *)
        echo "Opción no válida."
        ;;
esac

echo ""
echo "✅ Hecho. Puedes cerrar esta ventana."
read "?Pulsa Enter para cerrar..."
