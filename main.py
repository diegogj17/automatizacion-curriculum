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
from concurrent.futures import ThreadPoolExecutor, as_completed

# Asegurar que los paquetes --user son accesibles
sys.path.insert(0, os.path.expanduser("~/Library/Python/3.9/lib/python/site-packages"))

from database     import Database
from scraper      import (buscar_linkedin, buscar_tecnoempleo, buscar_infojobs,
                          buscar_indeed, buscar_google, buscar_github,
                          buscar_eures, enriquecer_con_emails,
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

def _barra_progreso(actual: int, total: int, encontrados: int, ancho: int = 38):
    """Dibuja una barra de progreso que se sobreescribe en la misma línea."""
    pct   = actual / total if total else 1
    lleno = int(ancho * pct)
    barra = "█" * lleno + "░" * (ancho - lleno)
    sys.stdout.write(
        f"\r  [{barra}] {actual}/{total} ({pct*100:3.0f}%)  ·  📧 {encontrados} emails"
    )
    sys.stdout.flush()


def _procesar_email_empresa(emp: dict, tiempo_max: float = 25.0) -> tuple:
    """
    Worker concurrente: busca el email de una empresa (solo I/O de red).
    No toca la BD — devuelve el resultado para que lo guarde el hilo principal.
    Devuelve (emp, email_elegido_o_None, lista_completa).

    tiempo_max: presupuesto total de segundos para esta empresa. La función
    de scraping lo respeta internamente y nunca tarda más de ese tiempo.
    """
    try:
        emails = obtener_email_de_web_exhaustivo(
            emp["web"], max_paginas=6, timeout=6, pausa=0.0, tiempo_max=tiempo_max
        )
        if emails:
            return (emp, _elegir_mejor_email(emails), emails)
        return (emp, None, [])
    except Exception:
        return (emp, None, [])


def buscar_emails_bd(config: dict, workers: int = 8, tam_lote: int = 40):
    """
    Recorre las empresas de la BD que tienen web pero no email y busca su email
    de forma CONCURRENTE y por LOTES.

    - workers:          webs procesadas en paralelo.
    - tam_lote:         empresas por tramo antes de mostrar resumen.
    - timeout_empresa:  segundos máx. por empresa antes de saltarla.
    - Se puede cancelar con Ctrl+C sin perder lo ya guardado.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError as FutureTimeout

    logger = logging.getLogger(__name__)
    db = Database(config["database"]["path"])

    em_cfg          = config.get("emails_busqueda", {})
    workers         = em_cfg.get("workers",          workers)
    tam_lote        = em_cfg.get("tam_lote",          tam_lote)
    timeout_empresa = em_cfg.get("timeout_empresa",   45)   # seg. máx. por empresa

    empresas = db.obtener_empresas_sin_email()
    total = len(empresas)

    print("\n" + "=" * 60)
    print("📧  BÚSQUEDA DE EMAILS (concurrente por lotes)")
    print("=" * 60)
    print(f"  Empresas con web pero sin email: {total}")
    print(f"  Procesando {workers} webs en paralelo, en lotes de {tam_lote}")
    print("=" * 60)

    if not empresas:
        print("✅ Todas las empresas ya tienen email registrado.\n")
        return

    # Silenciar el ruido del scraper durante la barra de progreso
    nivel_previo = logging.getLogger("scraper").level
    logging.getLogger("scraper").setLevel(logging.ERROR)

    total_emails = 0
    total_sin    = 0
    procesadas   = 0
    encontrados_detalle = []   # para mostrar al final de cada lote

    try:
        # Dividir en lotes
        for inicio in range(0, total, tam_lote):
            lote = empresas[inicio:inicio + tam_lote]
            num_lote = inicio // tam_lote + 1
            total_lotes = (total + tam_lote - 1) // tam_lote

            print(f"\n🔄 Lote {num_lote}/{total_lotes}  "
                  f"(empresas {inicio+1}–{min(inicio+tam_lote, total)})")

            emails_lote   = []
            procesados_id = set()   # ids de empresas resueltas en este lote

            # Tiempo máximo para el lote entero: en el peor caso el lote se
            # procesa en (tam_lote / workers) tandas, cada una de timeout_empresa.
            tandas         = (len(lote) + workers - 1) // workers
            tiempo_max_lote = tandas * timeout_empresa + 10   # +10s de margen

            executor = ThreadPoolExecutor(max_workers=workers)
            futuros  = {executor.submit(_procesar_email_empresa, emp, timeout_empresa): emp
                        for emp in lote}
            hechos = 0
            try:
                # as_completed CON timeout global del lote: si algún worker se
                # cuelga más allá de tiempo_max_lote, saltamos el resto del lote.
                for futuro in as_completed(futuros, timeout=tiempo_max_lote):
                    emp = futuros[futuro]
                    hechos     += 1
                    procesadas += 1
                    procesados_id.add(emp["id"])

                    try:
                        _, elegido, todos = futuro.result(timeout=1)
                    except Exception:
                        elegido, todos = None, []

                    if elegido and todos:
                        nuevos = db.agregar_emails_empresa(emp["id"], todos, principal=elegido)
                        if nuevos > 0:
                            total_emails += nuevos
                            emails_lote.append((emp["nombre"], todos))
                        else:
                            total_sin += 1
                    else:
                        total_sin += 1

                    db.marcar_empresa_buscada(emp["id"])
                    _barra_progreso(hechos, len(lote), total_emails)

            except FutureTimeout:
                # Uno o más workers colgados. No los esperamos.
                print()  # salto de línea tras la barra
                colgadas = len(lote) - len(procesados_id)
                logger.warning(f"⏱️  {colgadas} web(s) colgadas en el lote {num_lote}, saltando…")

            # Marcar como buscadas las que no se llegaron a procesar (colgadas)
            for emp in lote:
                if emp["id"] not in procesados_id:
                    db.marcar_empresa_buscada(emp["id"])
                    procesadas += 1
                    total_sin  += 1

            # Cerrar el executor SIN esperar a los threads colgados.
            # cancel_futures cancela los que aún no habían empezado (Python 3.9+).
            try:
                executor.shutdown(wait=False, cancel_futures=True)
            except TypeError:
                executor.shutdown(wait=False)   # compat. <3.9

            # Resumen del lote
            print()  # salto tras la barra
            if emails_lote:
                print(f"  ✅ {len(emails_lote)} empresas con email en este lote:")
                for nombre, mails in emails_lote[:10]:
                    muestra = ", ".join(mails[:3])
                    extra   = f" (+{len(mails)-3})" if len(mails) > 3 else ""
                    print(f"     • {nombre[:32]:32s} → {muestra}{extra}")
                if len(emails_lote) > 10:
                    print(f"     … y {len(emails_lote)-10} empresas más")
            else:
                print("  ❌ Sin emails nuevos en este lote")
            print(f"  Progreso global: {procesadas}/{total}  ·  "
                  f"📧 {total_emails} emails  ·  ⏭️  {total_sin} sin email")

    except KeyboardInterrupt:
        print("\n\n⚠️  Cancelado por el usuario. Lo encontrado ya está guardado en BD.")
    finally:
        logging.getLogger("scraper").setLevel(nivel_previo)

    print(f"""
{'='*60}
📊  RESULTADO FINAL
{'='*60}
  Empresas procesadas:    {procesadas}/{total}
  ✅ Emails encontrados:   {total_emails}
  ⏭️  Sin email:           {total_sin}
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

    # ── FASE 1: BÚSQUEDA EN PARALELO (guarda al completar cada tarea) ────────
    if not solo_enviar:
        logger.info("=" * 60)
        logger.info("FASE 1: Buscando empresas EN PARALELO (guardado incremental)...")
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
            """Guarda directamente en BD sin buscar emails (eso es la opción 4)."""
            nonlocal total_guardadas
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
        tareas = []   # cada tarea = (funcion, args, etiqueta) → se ejecuta en paralelo

        # ── ESPAÑA: una tarea por (fuente × ciudad) ────────────────────────────
        if loc_cfg["espana"]["activo"]:
            ciudades_es = [c["nombre"] for c in
                           sorted(loc_cfg["espana"]["ciudades"], key=lambda x: x["prioridad"])]
            for ciudad in ciudades_es:
                if fuentes_cfg.get("linkedin"):
                    tareas.append((buscar_linkedin, (terms_es, ciudad, "España", "es", max_pags),
                                   f"LinkedIn España/{ciudad}"))
                if fuentes_cfg.get("tecnoempleo"):
                    tareas.append((buscar_tecnoempleo, (terms_es, ciudad, max_pags),
                                   f"Tecnoempleo España/{ciudad}"))
                if fuentes_cfg.get("infojobs"):
                    tareas.append((buscar_infojobs, (terms_es, ciudad, max_pags),
                                   f"InfoJobs España/{ciudad}"))
                if fuentes_cfg.get("stackoverflow_jobs"):
                    tareas.append((buscar_indeed, (terms_es, ciudad, "España", "es", max_pags),
                                   f"Indeed España/{ciudad}"))
                if fuentes_cfg.get("busqueda_google"):
                    tareas.append((buscar_google,
                                   (terms_es, ciudad, "España", "es",
                                    google_key, google_cx, serper_key, max_pags),
                                   f"Google España/{ciudad}"))
            if fuentes_cfg.get("github"):
                tareas.append((buscar_github, (ciudades_es, ["Spain", "España"], "es", github_token),
                               "GitHub/España"))

        # ── INTERNACIONAL: una tarea por (fuente × ciudad) ─────────────────────
        if loc_cfg["internacional"]["activo"]:
            for pais_cfg in loc_cfg["internacional"]["paises"]:
                pais   = pais_cfg["nombre"]
                idioma = pais_cfg["idioma"]
                for ciudad in pais_cfg["ciudades"]:
                    if fuentes_cfg.get("linkedin"):
                        tareas.append((buscar_linkedin, (terms_en, ciudad, pais, idioma, max_pags),
                                       f"LinkedIn {pais}/{ciudad}"))
                    if fuentes_cfg.get("stackoverflow_jobs"):
                        tareas.append((buscar_indeed, (terms_en, ciudad, pais, idioma, max_pags),
                                       f"Indeed {pais}/{ciudad}"))
                    if fuentes_cfg.get("busqueda_google"):
                        tareas.append((buscar_google,
                                       (terms_en, ciudad, pais, idioma,
                                        google_key, google_cx, serper_key, max_pags),
                                       f"Google {pais}/{ciudad}"))
                if fuentes_cfg.get("github"):
                    tareas.append((buscar_github, (pais_cfg["ciudades"], [pais], idioma, github_token),
                                   f"GitHub/{pais}"))

        # ── EJECUCIÓN EN PARALELO (guardado en el hilo principal = SQLite OK) ──
        workers = config["filtros"].get("busqueda_workers", 6)
        logger.info(f"🚀 Lanzando {len(tareas)} búsquedas EN PARALELO "
                    f"(workers={workers})...")
        completadas = 0
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futuros = {ex.submit(fn, *args): etiqueta for fn, args, etiqueta in tareas}
            for fut in as_completed(futuros):
                etiqueta = futuros[fut]
                try:
                    lote = fut.result()
                except Exception as e:
                    logger.warning(f"⚠️  [{etiqueta}] error: {e}")
                    lote = []
                completadas += 1
                lote = _guardar_lote(lote, f"{etiqueta} [{completadas}/{len(tareas)}]")
                todas_crudas += lote

        # ── EURES (pan-europeo; ya paraleliza internamente → se ejecuta aparte) ─
        if fuentes_cfg.get("eures"):
            logger.info(f"\n{'─'*50}\n🇪🇺 EURES / Europa (UE + EEE + Suiza)\n{'─'*50}")
            if serper_key:
                eures_pags = config["filtros"].get("eures_paginas", 2)
                lote = buscar_eures(serper_key=serper_key, max_paginas=eures_pags)
                lote = _guardar_lote(lote, "EURES/Europa")
                todas_crudas += lote
            else:
                logger.warning("EURES omitido: falta serper.api_key en config.yaml")

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

    pendientes = db.obtener_destinos_pendientes()
    logger.info(f"Emails pendientes de contactar: {len(pendientes)} "
                f"(se envía a todos los correos de cada empresa)")

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
  Emails recopilados:    {resumen['total_emails']}  (en {resumen['empresas_con_email']} empresas)
  Emails pendientes:     {resumen['emails_pendientes']}
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
        r = db.resumen()
        print(f"""
{'='*60}
📊  ESTADÍSTICAS DE LA BASE DE DATOS
{'='*60}
  🏢 Empresas en BD:              {r['total_empresas']:,}
  📧 Emails recopilados:          {r['total_emails']:,}
     └─ en empresas distintas:    {r['empresas_con_email']:,}
  🔍 Webs pendientes de buscar:   {r['webs_por_buscar']:,}  ← opción 4
  ✉️  Emails enviados (total):     {r['total_enviados']:,}
     └─ hoy:                      {r['enviados_hoy']:,}
  ⏳ Emails pendientes de enviar: {r['emails_pendientes']:,}
  ❌ Errores de envío:            {r['errores']:,}
{'='*60}
""")
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
