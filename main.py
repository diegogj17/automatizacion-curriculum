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
from scraper      import (buscar_linkedin, buscar_tecnoempleo, buscar_infojobs,
                          buscar_indeed, buscar_google, buscar_github,
                          enriquecer_con_emails,
                          obtener_email_de_web_exhaustivo, _elegir_mejor_email)
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

def buscar_emails_bd(config: dict):
    """
    Recorre TODAS las empresas de la BD que tienen web pero no tienen email
    y realiza una búsqueda exhaustiva en su página web.
    Ideal para ejecutar después de haber buscado empresas con --solo-buscar.
    """
    import time
    logger = logging.getLogger(__name__)
    db = Database(config["database"]["path"])

    empresas = db.obtener_empresas_sin_email()
    logger.info(f"\n{'='*60}")
    logger.info(f"BÚSQUEDA EXHAUSTIVA DE EMAILS EN BD")
    logger.info(f"{'='*60}")
    logger.info(f"Empresas con web pero sin email: {len(empresas)}")

    if not empresas:
        logger.info("✅ Todas las empresas ya tienen email registrado.")
        return

    actualizadas = 0
    sin_email    = 0

    for i, emp in enumerate(empresas, 1):
        logger.info(f"\n[{i}/{len(empresas)}] {emp['nombre']} → {emp['web']}")
        try:
            emails = obtener_email_de_web_exhaustivo(emp["web"])
            if emails:
                elegido = _elegir_mejor_email(emails)
                db.actualizar_email_empresa(emp["id"], elegido)
                logger.info(f"  ✅ Email encontrado: {elegido}")
                if len(emails) > 1:
                    logger.info(f"     (otros: {', '.join(emails[1:4])})")
                actualizadas += 1
            else:
                logger.info(f"  ❌ No se encontró email")
                sin_email += 1
        except Exception as e:
            logger.warning(f"  ⚠️  Error: {e}")
            sin_email += 1
        time.sleep(2)

    logger.info(f"""
{'='*60}
📊 RESULTADO BÚSQUEDA DE EMAILS
{'='*60}
  Empresas procesadas:    {len(empresas)}
  Emails encontrados:     {actualizadas}
  Sin email:              {sin_email}
{'='*60}
""")


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

    # ── FASE 1: BÚSQUEDA INCREMENTAL (guarda por ciudad) ─────────────────────
    if not solo_enviar:
        logger.info("=" * 60)
        logger.info("FASE 1: Buscando empresas (guardado incremental por ciudad)...")
        logger.info("=" * 60)

        fuentes_cfg  = config["fuentes"]
        loc_cfg      = config["localizacion"]
        terms_es     = config["filtros"]["palabras_clave_es"]
        terms_en     = config["filtros"]["palabras_clave_en"]
        max_pags     = config["filtros"].get("max_paginas", 5)
        github_token = config.get("github", {}).get("token", "")
        google_key   = config.get("google_search", {}).get("api_key", "")
        google_cx    = config.get("google_search", {}).get("cx", "")
        serper_key   = config.get("serper", {}).get("api_key", "")

        total_guardadas = 0

        def _guardar_lote(empresas: list, etiqueta: str):
            """Enriquece emails y guarda inmediatamente en BD."""
            nonlocal total_guardadas
            empresas = enriquecer_con_emails(empresas)
            nuevas = 0
            for emp in empresas:
                id_emp = db.insertar_empresa(
                    nombre      = emp["nombre"],
                    email       = emp.get("email", ""),
                    web         = emp.get("web", ""),
                    descripcion = emp.get("descripcion", ""),
                    fuente      = emp.get("fuente", ""),
                    ciudad      = emp.get("ciudad", ""),
                    pais        = emp.get("pais", ""),
                    idioma      = emp.get("idioma", "es"),
                    relevancia  = 0,
                )
                if id_emp:
                    emp["_db_id"] = id_emp
                    nuevas += 1
            total_guardadas += nuevas
            logger.info(f"💾 [{etiqueta}] +{nuevas} guardadas (total acum: {total_guardadas})")
            return empresas

        todas_crudas = []

        # ── ESPAÑA ────────────────────────────────────────────────────────────
        if loc_cfg["espana"]["activo"]:
            ciudades_es = [c["nombre"] for c in
                           sorted(loc_cfg["espana"]["ciudades"], key=lambda x: x["prioridad"])]
            for ciudad in ciudades_es:
                logger.info(f"\n{'─'*50}\n🏙️  España / {ciudad}\n{'─'*50}")
                lote = []
                if fuentes_cfg.get("linkedin"):
                    lote += buscar_linkedin(terms_es, ciudad, "España", "es", max_pags)
                if fuentes_cfg.get("tecnoempleo"):
                    lote += buscar_tecnoempleo(terms_es, ciudad, max_pags)
                if fuentes_cfg.get("infojobs"):
                    lote += buscar_infojobs(terms_es, ciudad, max_pags)
                if fuentes_cfg.get("stackoverflow_jobs"):
                    lote += buscar_indeed(terms_es, ciudad, "España", "es", max_pags)
                if fuentes_cfg.get("busqueda_google"):
                    lote += buscar_google(terms_es, ciudad, "España", "es",
                                          api_key=google_key, cx=google_cx,
                                          serper_key=serper_key, max_paginas=max_pags)
                lote = _guardar_lote(lote, f"España/{ciudad}")
                todas_crudas += lote

            # GitHub para España
            if fuentes_cfg.get("github"):
                logger.info(f"\n{'─'*50}\n🐙 GitHub / España\n{'─'*50}")
                lote = buscar_github(ciudades=ciudades_es, paises=["Spain", "España"],
                                     idioma_email="es", token=github_token)
                lote = _guardar_lote(lote, "GitHub/España")
                todas_crudas += lote

        # ── INTERNACIONAL ─────────────────────────────────────────────────────
        if loc_cfg["internacional"]["activo"]:
            for pais_cfg in loc_cfg["internacional"]["paises"]:
                pais   = pais_cfg["nombre"]
                idioma = pais_cfg["idioma"]
                for ciudad in pais_cfg["ciudades"]:
                    logger.info(f"\n{'─'*50}\n🌍 {pais} / {ciudad}\n{'─'*50}")
                    lote = []
                    if fuentes_cfg.get("linkedin"):
                        lote += buscar_linkedin(terms_en, ciudad, pais, idioma, max_pags)
                    if fuentes_cfg.get("stackoverflow_jobs"):
                        lote += buscar_indeed(terms_en, ciudad, pais, idioma, max_pags)
                    if fuentes_cfg.get("busqueda_google"):
                        lote += buscar_google(terms_en, ciudad, pais, idioma,
                                              api_key=google_key, cx=google_cx,
                                              serper_key=serper_key, max_paginas=max_pags)
                    lote = _guardar_lote(lote, f"{pais}/{ciudad}")
                    todas_crudas += lote

                # GitHub para este país
                if fuentes_cfg.get("github"):
                    logger.info(f"\n{'─'*50}\n🐙 GitHub / {pais}\n{'─'*50}")
                    lote = buscar_github(ciudades=pais_cfg["ciudades"], paises=[pais],
                                         idioma_email=idioma, token=github_token)
                    lote = _guardar_lote(lote, f"GitHub/{pais}")
                    todas_crudas += lote

        logger.info(f"\n✅ Búsqueda completada. Total guardadas en BD: {total_guardadas}")
        empresas_crudas = todas_crudas

        # ── FASE 2: FILTRADO CON IA ────────────────────────────────────────────
        logger.info("\n" + "=" * 60)
        logger.info("FASE 2: Filtrando y personalizando con Ollama...")
        logger.info("=" * 60)

        empresas_filtradas = filtrar_y_personalizar(empresas_crudas, config)

        # Actualizar relevancia en BD para las empresas filtradas
        actualizadas_ia = 0
        for emp in empresas_filtradas:
            if emp.get("_db_id"):
                with db._conectar() as conn:
                    conn.execute(
                        "UPDATE empresas SET relevancia=? WHERE id=?",
                        (emp.get("relevancia", 5), emp["_db_id"])
                    )
                actualizadas_ia += 1

        logger.info(f"\n✅ {actualizadas_ia} empresas actualizadas con puntuación IA.")

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
    parser.add_argument("--buscar-emails", action="store_true",   help="Busca emails exhaustivamente en empresas de la BD sin email")
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

    if args.buscar_emails:
        buscar_emails_bd(config)
        sys.exit(0)

    ejecutar_pipeline(
        config,
        solo_buscar = args.solo_buscar,
        solo_enviar = args.solo_enviar,
        test_smtp   = args.test_smtp,
    )
