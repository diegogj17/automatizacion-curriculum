"""
database.py - Gestión de la base de datos SQLite
Registra empresas, emails enviados y respuestas recibidas
"""

import sqlite3
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict

logger = logging.getLogger(__name__)


class Database:
    def __init__(self, db_path: str = "data/empresas.db"):
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.db_path = db_path
        self._crear_tablas()

    def _conectar(self):
        return sqlite3.connect(self.db_path)

    def _crear_tablas(self):
        with self._conectar() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS empresas (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    nombre      TEXT NOT NULL,
                    web         TEXT,
                    email       TEXT,
                    descripcion TEXT,
                    fuente      TEXT,
                    ciudad      TEXT,
                    pais        TEXT,
                    idioma      TEXT DEFAULT 'es',
                    relevancia  INTEGER DEFAULT 0,
                    fecha_add   TEXT DEFAULT (datetime('now'))
                );

                -- Índice único SOLO para emails reales (no nulos ni vacíos)
                CREATE UNIQUE INDEX IF NOT EXISTS idx_empresas_email
                    ON empresas(email) WHERE email IS NOT NULL AND email != '';

                -- Índice único para evitar duplicados por web cuando no hay email
                CREATE UNIQUE INDEX IF NOT EXISTS idx_empresas_web
                    ON empresas(web) WHERE web IS NOT NULL AND web != '';

                CREATE TABLE IF NOT EXISTS emails_enviados (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    empresa_id      INTEGER REFERENCES empresas(id),
                    email_destino   TEXT NOT NULL,
                    asunto          TEXT,
                    cuerpo          TEXT,
                    fecha_envio     TEXT DEFAULT (datetime('now')),
                    estado          TEXT DEFAULT 'enviado',
                    respuesta       TEXT
                );

                -- Todos los emails de cada empresa (relación uno-a-muchos).
                -- email UNIQUE global → evita contactar el mismo buzón dos veces
                -- aunque aparezca en varias empresas.
                CREATE TABLE IF NOT EXISTS emails_empresa (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    empresa_id  INTEGER REFERENCES empresas(id),
                    email       TEXT NOT NULL UNIQUE,
                    principal   INTEGER DEFAULT 0,   -- 1 = email preferido (rrhh/empleo…)
                    enviado     INTEGER DEFAULT 0,   -- 1 = ya se le envió el CV
                    fecha_envio TEXT,                -- fecha/hora del envío (NULL si no enviado)
                    fecha_add   TEXT DEFAULT (datetime('now'))
                );

                CREATE TABLE IF NOT EXISTS log_busquedas (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    fuente      TEXT,
                    termino     TEXT,
                    resultados  INTEGER,
                    fecha       TEXT DEFAULT (datetime('now'))
                );
            """)
        # Migraciones para bases de datos antiguas
        with self._conectar() as conn:
            cols = {row[1] for row in conn.execute("PRAGMA table_info(empresas)")}
            if "pais" not in cols:
                conn.execute("ALTER TABLE empresas ADD COLUMN pais TEXT DEFAULT ''")
            if "idioma" not in cols:
                conn.execute("ALTER TABLE empresas ADD COLUMN idioma TEXT DEFAULT 'es'")
            # Migrar: quitar la restricción UNIQUE(email) antigua que bloquea vacíos.
            # SQLite no permite DROP CONSTRAINT, así que recreamos la tabla si tiene
            # la columna email con UNIQUE en la definición original.
            schema = conn.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name='empresas'"
            ).fetchone()
            if schema and "UNIQUE(email)" in schema[0]:
                logger.info("Migrando BD: eliminando UNIQUE(email) antiguo...")
                conn.executescript("""
                    ALTER TABLE empresas RENAME TO empresas_old;
                    CREATE TABLE empresas (
                        id          INTEGER PRIMARY KEY AUTOINCREMENT,
                        nombre      TEXT NOT NULL,
                        web         TEXT,
                        email       TEXT,
                        descripcion TEXT,
                        fuente      TEXT,
                        ciudad      TEXT,
                        pais        TEXT,
                        idioma      TEXT DEFAULT 'es',
                        relevancia  INTEGER DEFAULT 0,
                        fecha_add   TEXT DEFAULT (datetime('now'))
                    );
                    INSERT OR IGNORE INTO empresas
                        SELECT id,nombre,web,email,descripcion,fuente,ciudad,pais,idioma,relevancia,fecha_add
                        FROM empresas_old;
                    DROP TABLE empresas_old;
                    CREATE UNIQUE INDEX IF NOT EXISTS idx_empresas_email
                        ON empresas(email) WHERE email IS NOT NULL AND email != '';
                    CREATE UNIQUE INDEX IF NOT EXISTS idx_empresas_web
                        ON empresas(web) WHERE web IS NOT NULL AND web != '';
                """)
                logger.info("Migración completada.")

        # Migración: columnas 'enviado' y 'fecha_envio' en emails_empresa (BD antiguas)
        with self._conectar() as conn:
            cols_em = {row[1] for row in conn.execute("PRAGMA table_info(emails_empresa)")}
            if "enviado" not in cols_em:
                conn.execute("ALTER TABLE emails_empresa ADD COLUMN enviado INTEGER DEFAULT 0")
            if "fecha_envio" not in cols_em:
                conn.execute("ALTER TABLE emails_empresa ADD COLUMN fecha_envio TEXT")
            # Marcar como enviados los emails que ya estén en emails_enviados
            conn.execute("""
                UPDATE emails_empresa
                SET enviado = 1,
                    fecha_envio = (
                        SELECT MAX(ev.fecha_envio) FROM emails_enviados ev
                        WHERE ev.email_destino = emails_empresa.email
                          AND ev.estado = 'enviado'
                    )
                WHERE email IN (
                    SELECT email_destino FROM emails_enviados WHERE estado = 'enviado'
                )
            """)

        # Migración: columnas 'email_buscado' y 'fecha_busqueda_email' en empresas (BD antiguas)
        # email_buscado = 1 → ya se intentó buscar su email (aunque no se encontrase)
        # Así la opción 4 no vuelve a perder tiempo en webs que ya no dan email.
        with self._conectar() as conn:
            cols_emp = {row[1] for row in conn.execute("PRAGMA table_info(empresas)")}
            if "email_buscado" not in cols_emp:
                conn.execute("ALTER TABLE empresas ADD COLUMN email_buscado INTEGER DEFAULT 0")
            if "fecha_busqueda_email" not in cols_emp:
                conn.execute("ALTER TABLE empresas ADD COLUMN fecha_busqueda_email TEXT")
            # tecnologias: stack detectado en la web (CSV) para personalizar emails
            if "tecnologias" not in cols_emp:
                conn.execute("ALTER TABLE empresas ADD COLUMN tecnologias TEXT")
            # Las que ya tienen email en emails_empresa → marcarlas como buscadas
            conn.execute("""
                UPDATE empresas SET email_buscado = 1
                WHERE id IN (SELECT DISTINCT empresa_id FROM emails_empresa)
                  AND email_buscado = 0
            """)

        # Migración: volcar emails que estaban en empresas.email a emails_empresa
        with self._conectar() as conn:
            conn.execute("""
                INSERT OR IGNORE INTO emails_empresa (empresa_id, email, principal)
                SELECT id, email, 1 FROM empresas
                WHERE email IS NOT NULL AND email != ''
            """)
        logger.info("Base de datos inicializada correctamente.")

    # ── EMPRESAS ──────────────────────────────────────────────────────────────

    def insertar_empresa(self, nombre: str, email: str, web: str = "",
                         descripcion: str = "", fuente: str = "", ciudad: str = "",
                         pais: str = "", idioma: str = "es",
                         relevancia: int = 0) -> Optional[int]:
        """
        Inserta una empresa. Devuelve el ID o None si ya existía.
        - Emails/webs vacíos se almacenan como NULL para no violar el índice único.
        - El índice único solo aplica a emails/webs reales (no nulos).
        """
        email_db = email.strip() if email and email.strip() else None
        web_db   = web.strip()   if web   and web.strip()   else None
        try:
            with self._conectar() as conn:
                cur = conn.execute(
                    """INSERT INTO empresas
                       (nombre, email, web, descripcion, fuente, ciudad, pais, idioma, relevancia)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (nombre, email_db, web_db, descripcion, fuente, ciudad, pais, idioma, relevancia)
                )
                logger.info(f"Empresa guardada: {nombre} <{email_db or 'sin email'}>")
                return cur.lastrowid
        except sqlite3.IntegrityError:
            logger.debug(f"Empresa ya existente (duplicada): {nombre} | {email_db or web_db}")
            return None

    def email_ya_contactado(self, email: str) -> bool:
        with self._conectar() as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM emails_enviados WHERE email_destino = ?", (email,)
            ).fetchone()
            return row[0] > 0

    def obtener_empresas_sin_email(self) -> List[Dict]:
        """
        Empresas que tienen web, NO tienen emails registrados
        Y todavía NO se han buscado (email_buscado = 0).
        Las que ya se intentaron y no dieron resultado no vuelven a procesarse.
        """
        with self._conectar() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("""
                SELECT e.* FROM empresas e
                WHERE e.web IS NOT NULL AND e.web != ''
                  AND e.email_buscado = 0
                  AND NOT EXISTS (
                      SELECT 1 FROM emails_empresa em WHERE em.empresa_id = e.id
                  )
                ORDER BY e.fecha_add ASC
            """).fetchall()
            return [dict(r) for r in rows]

    def marcar_empresa_buscada(self, empresa_id: int):
        """Marca que ya se intentó buscar el email de esta empresa (con o sin resultado)."""
        with self._conectar() as conn:
            conn.execute(
                "UPDATE empresas SET email_buscado = 1, fecha_busqueda_email = datetime('now') WHERE id = ?",
                (empresa_id,)
            )

    def guardar_tecnologias(self, empresa_id: int, tecnologias: List[str]):
        """Guarda el stack tecnológico detectado en la web (lista → CSV)."""
        valor = ", ".join(tecnologias) if tecnologias else ""
        with self._conectar() as conn:
            conn.execute(
                "UPDATE empresas SET tecnologias = ? WHERE id = ?",
                (valor, empresa_id)
            )

    def agregar_emails_empresa(self, empresa_id: int, emails: List[str],
                               principal: Optional[str] = None) -> int:
        """
        Guarda TODOS los emails de una empresa en la tabla emails_empresa.
        - Usa INSERT OR IGNORE: si un email ya existe (en cualquier empresa),
          se omite, evitando contactar dos veces el mismo buzón.
        - 'principal' marca el email preferido (rrhh/empleo/contacto…).
        - También rellena empresas.email con el principal si estaba vacío.
        Devuelve el nº de emails NUEVOS insertados.
        """
        if not emails:
            return 0
        if principal is None:
            principal = emails[0]

        nuevos = 0
        with self._conectar() as conn:
            for email in emails:
                email = email.strip().lower()
                if not email or "@" not in email:
                    continue
                cur = conn.execute(
                    """INSERT OR IGNORE INTO emails_empresa (empresa_id, email, principal)
                       VALUES (?, ?, ?)""",
                    (empresa_id, email, 1 if email == principal.strip().lower() else 0)
                )
                if cur.rowcount > 0:
                    nuevos += 1
            # Rellenar empresas.email (principal) si está vacío, ignorando duplicados
            try:
                conn.execute(
                    "UPDATE empresas SET email = ? WHERE id = ? AND (email IS NULL OR email = '')",
                    (principal.strip().lower(), empresa_id)
                )
            except sqlite3.IntegrityError:
                pass
        if nuevos:
            logger.info(f"empresa id={empresa_id}: +{nuevos} emails guardados")
        return nuevos

    def actualizar_email_empresa(self, empresa_id: int, email: str) -> bool:
        """Compatibilidad: guarda un único email como principal."""
        return self.agregar_emails_empresa(empresa_id, [email], principal=email) > 0

    def obtener_destinos_pendientes(self) -> List[Dict]:
        """
        Devuelve TODOS los emails pendientes de contactar (uno por fila),
        con los datos de su empresa. Un email es pendiente si enviado = 0.
        Ordenados por relevancia de la empresa y email principal primero.
        Cada dict incluye: id (empresa), nombre, web, idioma, relevancia,
        ciudad, pais, descripcion y 'email' (el destino concreto).
        """
        with self._conectar() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("""
                SELECT e.id, e.nombre, e.web, e.descripcion, e.ciudad,
                       e.pais, e.idioma, e.relevancia, e.tecnologias, e.fuente,
                       em.email AS email
                FROM emails_empresa em
                JOIN empresas e ON e.id = em.empresa_id
                WHERE em.enviado = 0
                ORDER BY e.relevancia DESC, em.principal DESC, e.fecha_add ASC
            """).fetchall()
            return [dict(r) for r in rows]

    def obtener_empresas_pendientes(self) -> List[Dict]:
        """Compatibilidad: alias de obtener_destinos_pendientes()."""
        return self.obtener_destinos_pendientes()

    def total_empresas(self) -> int:
        with self._conectar() as conn:
            return conn.execute("SELECT COUNT(*) FROM empresas").fetchone()[0]

    # ── EMAILS ────────────────────────────────────────────────────────────────

    def registrar_envio(self, empresa_id: int, email_destino: str,
                        asunto: str, cuerpo: str, estado: str = "enviado"):
        with self._conectar() as conn:
            conn.execute(
                """INSERT INTO emails_enviados (empresa_id, email_destino, asunto, cuerpo, estado)
                   VALUES (?, ?, ?, ?, ?)""",
                (empresa_id, email_destino, asunto, cuerpo, estado)
            )
            # Marcar el email como enviado en emails_empresa (solo si fue OK)
            if estado == "enviado":
                conn.execute(
                    """UPDATE emails_empresa
                       SET enviado = 1, fecha_envio = datetime('now')
                       WHERE email = ?""",
                    (email_destino,)
                )
        logger.info(f"Envío registrado → {email_destino} [{estado}]")

    def emails_enviados_hoy(self) -> int:
        with self._conectar() as conn:
            return conn.execute(
                "SELECT COUNT(*) FROM emails_enviados WHERE DATE(fecha_envio) = DATE('now')"
            ).fetchone()[0]

    # ── ESTADÍSTICAS ──────────────────────────────────────────────────────────

    def resumen(self) -> dict:
        with self._conectar() as conn:
            total_empresas = conn.execute("SELECT COUNT(*) FROM empresas").fetchone()[0]
            total_emails   = conn.execute("SELECT COUNT(*) FROM emails_empresa").fetchone()[0]
            empresas_con_email = conn.execute(
                "SELECT COUNT(DISTINCT empresa_id) FROM emails_empresa"
            ).fetchone()[0]
            por_buscar = conn.execute("""
                SELECT COUNT(*) FROM empresas
                WHERE web IS NOT NULL AND web != ''
                  AND email_buscado = 0
                  AND NOT EXISTS (SELECT 1 FROM emails_empresa em WHERE em.empresa_id = empresas.id)
            """).fetchone()[0]
            total_enviados = conn.execute("SELECT COUNT(*) FROM emails_enviados").fetchone()[0]
            enviados_hoy   = conn.execute(
                "SELECT COUNT(*) FROM emails_enviados WHERE DATE(fecha_envio) = DATE('now')"
            ).fetchone()[0]
            errores        = conn.execute(
                "SELECT COUNT(*) FROM emails_enviados WHERE estado = 'error'"
            ).fetchone()[0]
            pendientes = conn.execute(
                "SELECT COUNT(*) FROM emails_empresa WHERE enviado = 0"
            ).fetchone()[0]
            return {
                "total_empresas":       total_empresas,
                "total_emails":         total_emails,
                "empresas_con_email":   empresas_con_email,
                "webs_por_buscar":      por_buscar,
                "emails_pendientes":    pendientes,
                "total_enviados":       total_enviados,
                "enviados_hoy":         enviados_hoy,
                "errores":              errores,
            }
