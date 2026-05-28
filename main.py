"""
main.py - Orquestador principal de la automatización
Ejecuta: búsqueda → filtrado IA → envío de emails → registro en BD
"""

import yaml
import logging
import argparse
import sys
import os
from pathlib import Path
from datetime import datetime

# Asegurar que los paquetes --user son accesibles
sys.path.insert(0, os.path.expanduser("~/Library/Python/3.9/lib/python/site-packages"))

from database     import Database
from scraper      import buscar_todas_las_fuentes
from ai_filter    import filtrar_y_personalizar
from email_sender import EmailSender

# ── LOGGING ───────────────────────────────────────────────────────────────────

def configurar_logging(log_dir: str = "logs"):
    Path(log_dir).mkdir(exist_ok=True)
    nombre_log = f"{log_dir}/automatizacion_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(message)s",
        datefmt="%H:%M:%S",
        handlers=[
            logging.FileHandler(nombre_log, encoding="utf-8"),
            logging.StreamHandler(sys.stdout)       # También en consola
        ]
    )
    return nombre_log


# ── CARGA DE CONFIGURACIÓN ────────────────────────────────────────────────────

def cargar_config(ruta: str = "config.yaml") -> dict:
    with open(ruta, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


# ── PIPELINE PRINCIPAL ────────────────────────────────────────────────────────

def ejecutar_pipeline(config: dict, solo_buscar: bool = False,
                      solo_enviar: bool = False, test_smtp: bool = False):
    logger = logging.getLogger(__name__)
    db     = Database(config["database"]["path"])
    sender = EmailSender(config)

    # ── TEST SMTP ──────────────────────────────────────────────────────────────
    if test_smtp:
        logger.info("=== TEST DE CONEXIÓN SMTP ===")
        sender.test_conexion()
        return

    # ── FASE 1: BÚSQUEDA ──────────────────────────────────────────────────────
    if not solo_enviar:
        logger.info("=" * 60)
        logger.info("FASE 1: Buscando empresas en todas las fuentes...")
        logger.info("=" * 60)

        empresas_crudas = buscar_todas_las_fuentes(config)

        logger.info(f"\nEjemplos de empresas encontradas:")
        for e in empresas_crudas[:5]:
            logger.info(f"  • {e['nombre']} ({e['fuente']}) - Email: {e.get('email') or 'no encontrado'}")

        # ── FASE 2: FILTRADO CON IA ────────────────────────────────────────────
        logger.info("\n" + "=" * 60)
        logger.info("FASE 2: Filtrando y personalizando con Mistral (Ollama)...")
        logger.info("=" * 60)

        empresas_filtradas = filtrar_y_personalizar(empresas_crudas, config)

        # Guardar en BD
        nuevas = 0
        for emp in empresas_filtradas:
            id_emp = db.insertar_empresa(
                nombre      = emp["nombre"],
                email       = emp.get("email", ""),
                web         = emp.get("web", ""),
                descripcion = emp.get("descripcion", ""),
                fuente      = emp.get("fuente", ""),
                ciudad      = emp.get("ciudad", ""),
                pais        = emp.get("pais", ""),
                idioma      = emp.get("idioma", "es"),
                relevancia  = emp.get("relevancia", 0),
            )
            if id_emp:
                nuevas += 1

        logger.info(f"\n✅ {nuevas} empresas nuevas guardadas en la base de datos.")

        if solo_buscar:
            resumen = db.resumen()
            logger.info(f"\n📊 RESUMEN:\n{resumen}")
            return

    # ── FASE 3: ENVÍO DE EMAILS ───────────────────────────────────────────────
    logger.info("\n" + "=" * 60)
    logger.info("FASE 3: Enviando emails a empresas pendientes...")
    logger.info("=" * 60)

    max_hoy    = config["email"]["max_emails_por_dia"]
    enviados_h = db.emails_enviados_hoy()

    if enviados_h >= max_hoy:
        logger.warning(f"⚠️  Límite diario alcanzado ({max_hoy} emails). Vuelve mañana.")
        return

    pendientes = db.obtener_empresas_pendientes()
    logger.info(f"Empresas pendientes de contactar: {len(pendientes)}")

    enviados = 0
    errores  = 0

    for emp in pendientes:
        if enviados_h + enviados >= max_hoy:
            logger.warning(f"⚠️  Límite diario alcanzado ({max_hoy}). Parando.")
            break

        if not emp.get("email"):
            continue

        asunto = emp.get("asunto") or (
            f"Candidatura espontánea – Desarrollador {config['skills']['nivel']} "
            f"| {config['personal']['nombre']}"
        )
        cuerpo = emp.get("cuerpo_email") or _email_generico(config)

        # Mostrar preview
        logger.info(f"\n{'─'*50}")
        logger.info(f"📧 ENVIANDO A: {emp['nombre']} <{emp['email']}>")
        logger.info(f"   Asunto: {asunto}")
        logger.info(f"   Preview: {cuerpo[:120]}...")

        ok = sender.enviar_con_pausa(emp["email"], asunto, cuerpo,
                                     cv_path=emp.get("cv_path"))
        estado = "enviado" if ok else "error"

        db.registrar_envio(
            empresa_id    = emp["id"],
            email_destino = emp["email"],
            asunto        = asunto,
            cuerpo        = cuerpo,
            estado        = estado,
        )

        if ok:
            enviados += 1
        else:
            errores += 1

    # ── RESUMEN FINAL ──────────────────────────────────────────────────────────
    resumen = db.resumen()
    logger.info(f"""
{'='*60}
📊 RESUMEN FINAL
{'='*60}
  Empresas en BD:        {resumen['total_empresas']}
  Emails enviados hoy:   {enviados}
  Errores hoy:           {errores}
  Total enviados:        {resumen['total_enviados']}
  Total errores acum.:   {resumen['errores']}
{'='*60}
""")


def _email_generico(config: dict) -> str:
    """Email de candidatura genérico como fallback."""
    p = config["personal"]
    s = config["skills"]
    return (
        f"Estimado equipo de RRHH,\n\n"
        f"Me pongo en contacto para presentar mi candidatura espontánea. "
        f"Soy {p['nombre']}, desarrollador {s['nivel']} especializado en "
        f"{', '.join(s['principales'])}.\n\n"
        f"Estoy muy interesado en formar parte de vuestro equipo y creo que mis "
        f"conocimientos pueden aportar valor a vuestros proyectos.\n\n"
        f"Adjunto mi CV para vuestra consideración. Quedo a vuestra disposición "
        f"para cualquier consulta o entrevista.\n\n"
        f"Un saludo,\n"
        f"{p['nombre']}\n"
        f"📞 {p['telefono']}\n"
        f"🔗 {p['linkedin']}\n"
    )


# ── ENTRY POINT ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Automatización de envío de curriculum a empresas tech"
    )
    parser.add_argument("--config",        default="config.yaml", help="Ruta al config.yaml")
    parser.add_argument("--solo-buscar",   action="store_true",   help="Solo busca y guarda empresas, no envía emails")
    parser.add_argument("--solo-enviar",   action="store_true",   help="Solo envía emails (usa empresas ya en BD)")
    parser.add_argument("--test-smtp",     action="store_true",   help="Prueba la conexión de correo")
    parser.add_argument("--estadisticas",  action="store_true",   help="Muestra estadísticas de la BD")
    args = parser.parse_args()

    log_file = configurar_logging()
    logger   = logging.getLogger(__name__)
    logger.info(f"Log guardado en: {log_file}")

    config = cargar_config(args.config)

    if args.estadisticas:
        db = Database(config["database"]["path"])
        resumen = db.resumen()
        print(f"\n📊 ESTADÍSTICAS:\n{resumen}\n")
        sys.exit(0)

    ejecutar_pipeline(
        config,
        solo_buscar = args.solo_buscar,
        solo_enviar = args.solo_enviar,
        test_smtp   = args.test_smtp,
    )
