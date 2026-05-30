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
        """Devuelve empresas que tienen web pero no tienen email registrado."""
        with self._conectar() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("""
                SELECT * FROM empresas
                WHERE web IS NOT NULL AND web != ''
                  AND (email IS NULL OR email = '')
                ORDER BY fecha_add ASC
            """).fetchall()
            return [dict(r) for r in rows]

    def actualizar_email_empresa(self, empresa_id: int, email: str):
        """Actualiza el email de una empresa ya guardada en BD."""
        with self._conectar() as conn:
            conn.execute(
                "UPDATE empresas SET email = ? WHERE id = ?",
                (email, empresa_id)
            )
        logger.info(f"Email actualizado en empresa id={empresa_id}: {email}")

    def obtener_empresas_pendientes(self) -> List[Dict]:
        """Devuelve empresas con email que aún no han sido contactadas."""
        with self._conectar() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("""
                SELECT e.* FROM empresas e
                WHERE e.email IS NOT NULL AND e.email != ''
                  AND e.email NOT IN (SELECT email_destino FROM emails_enviados)
                ORDER BY e.relevancia DESC, e.fecha_add ASC
            """).fetchall()
            return [dict(r) for r in rows]

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
            total_enviados = conn.execute("SELECT COUNT(*) FROM emails_enviados").fetchone()[0]
            enviados_hoy   = conn.execute(
                "SELECT COUNT(*) FROM emails_enviados WHERE DATE(fecha_envio) = DATE('now')"
            ).fetchone()[0]
            errores        = conn.execute(
                "SELECT COUNT(*) FROM emails_enviados WHERE estado = 'error'"
            ).fetchone()[0]
            return {
                "total_empresas":  total_empresas,
                "total_enviados":  total_enviados,
                "enviados_hoy":    enviados_hoy,
                "errores":         errores,
            }
