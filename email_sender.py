"""
email_sender.py - Envío de emails con CV adjunto
  - Gmail via yagmail  (metodo: "gmail")   → contraseña de aplicación
  - Outlook Graph API  (metodo: "outlook") → OAuth2 con Azure
"""

import requests
import logging
import time
import base64
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.expanduser("~/Library/Python/3.9/lib/python/site-packages"))
import yagmail

logger = logging.getLogger(__name__)
GRAPH_SEND_URL = "https://graph.microsoft.com/v1.0/me/sendMail"


class EmailSender:
    def __init__(self, config: dict):
        self.metodo    = config["email"].get("metodo", "gmail")
        self.remitente = config["personal"]["email_remitente"]
        self.password  = config["personal"].get("email_password", "").replace(" ", "")
        self.client_id = config["personal"].get("outlook_client_id", "")
        self.cv_path   = config["personal"]["cv_path"]
        self.espera    = config["email"]["espera_entre_emails"]
        self._token    = None

    # ── GMAIL ─────────────────────────────────────────────────────────────────

    def _enviar_gmail(self, destinatario: str, asunto: str, cuerpo: str,
                      cv_path: str = None) -> bool:
        try:
            cv = Path(cv_path or self.cv_path)
            adjuntos = [str(cv)] if cv.exists() else []
            with yagmail.SMTP(self.remitente, self.password) as yag:
                yag.send(to=destinatario, subject=asunto,
                         contents=cuerpo, attachments=adjuntos)
            logger.info(f"Email enviado (Gmail) a {destinatario}")
            return True
        except Exception as e:
            logger.error(f"Error Gmail enviando a {destinatario}: {e}")
            return False

    # ── OUTLOOK ───────────────────────────────────────────────────────────────

    def _get_token(self) -> str:
        if not self.client_id:
            raise RuntimeError("Falta 'outlook_client_id' en config.yaml.")
        if not self._token:
            from auth_outlook import obtener_token
            self._token = obtener_token(self.client_id)
        return self._token

    def _enviar_outlook(self, destinatario: str, asunto: str, cuerpo: str,
                        cv_path: str = None) -> bool:
        try:
            token = self._get_token()
            mensaje = {
                "subject": asunto,
                "body": {"contentType": "Text", "content": cuerpo},
                "toRecipients": [{"emailAddress": {"address": destinatario}}]
            }
            cv = Path(cv_path or self.cv_path)
            if cv.exists():
                with open(cv, "rb") as f:
                    b64 = base64.b64encode(f.read()).decode("utf-8")
                mensaje["attachments"] = [{
                    "@odata.type": "#microsoft.graph.fileAttachment",
                    "name": cv.name, "contentType": "application/pdf",
                    "contentBytes": b64
                }]
            headers = {"Authorization": f"Bearer {token}",
                       "Content-Type": "application/json"}
            r = requests.post(GRAPH_SEND_URL,
                              json={"message": mensaje, "saveToSentItems": True},
                              headers=headers, timeout=30)
            if r.status_code == 202:
                logger.info(f"Email enviado (Outlook) a {destinatario}")
                return True
            logger.error(f"Error Graph API {r.status_code}: {r.text[:300]}")
            return False
        except Exception as e:
            logger.error(f"Error Outlook enviando a {destinatario}: {e}")
            return False

    # ── INTERFAZ PÚBLICA ──────────────────────────────────────────────────────

    def enviar(self, destinatario: str, asunto: str, cuerpo: str,
               cv_path: str = None) -> bool:
        if self.metodo == "gmail":
            return self._enviar_gmail(destinatario, asunto, cuerpo, cv_path)
        elif self.metodo == "outlook":
            return self._enviar_outlook(destinatario, asunto, cuerpo, cv_path)
        else:
            logger.error(f"Metodo desconocido: {self.metodo}. Usa 'gmail' o 'outlook'.")
            return False

    def enviar_con_pausa(self, destinatario: str, asunto: str, cuerpo: str,
                         cv_path: str = None) -> bool:
        resultado = self.enviar(destinatario, asunto, cuerpo, cv_path)
        if resultado:
            logger.info(f"Esperando {self.espera}s antes del siguiente email...")
            time.sleep(self.espera)
        return resultado

    def test_conexion(self) -> bool:
        if self.metodo == "gmail":
            try:
                with yagmail.SMTP(self.remitente, self.password) as yag:
                    pass
                logger.info(f"Conexion Gmail OK - {self.remitente}")
                return True
            except Exception as e:
                logger.error(f"Fallo conexion Gmail: {e}")
                return False
        elif self.metodo == "outlook":
            try:
                token = self._get_token()
                r = requests.get("https://graph.microsoft.com/v1.0/me",
                                 headers={"Authorization": f"Bearer {token}"},
                                 timeout=10)
                if r.status_code == 200:
                    info = r.json()
                    logger.info(f"Conexion Outlook OK - {info.get('displayName')}")
                    return True
                logger.error(f"Error verificando cuenta Outlook: {r.status_code}")
                return False
            except Exception as e:
                logger.error(f"Fallo conexion Outlook: {e}")
                return False
