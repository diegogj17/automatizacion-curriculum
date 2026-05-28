"""
auth_outlook.py - Autenticación OAuth2 con Microsoft Graph API
Usa MSAL con Device Code Flow (no requiere navegador gráfico)
El token se guarda en disco para no pedir login en cada ejecución
"""

import os
import json
import logging
import msal
from pathlib import Path

logger = logging.getLogger(__name__)

TOKEN_CACHE_PATH = "data/token_cache.json"

# Scopes necesarios para enviar email con Graph API
SCOPES = ["https://graph.microsoft.com/Mail.Send"]


def _cargar_cache() -> msal.SerializableTokenCache:
    cache = msal.SerializableTokenCache()
    if Path(TOKEN_CACHE_PATH).exists():
        cache.deserialize(Path(TOKEN_CACHE_PATH).read_text())
    return cache


def _guardar_cache(cache: msal.SerializableTokenCache):
    Path(TOKEN_CACHE_PATH).parent.mkdir(exist_ok=True)
    if cache.has_state_changed:
        Path(TOKEN_CACHE_PATH).write_text(cache.serialize())


def obtener_token(client_id: str) -> str:
    """
    Obtiene un access token válido para Microsoft Graph.
    - Si ya hay un token guardado (y no expiró) lo reutiliza.
    - Si no, lanza el Device Code Flow: muestra un código en consola
      y abre https://microsoft.com/devicelogin para que lo pegues.
    Solo necesitas hacer el login la PRIMERA vez.
    """
    cache = _cargar_cache()

    app = msal.PublicClientApplication(
        client_id=client_id,
        authority="https://login.microsoftonline.com/consumers",
        token_cache=cache,
    )

    # Intentar token silencioso (desde caché)
    cuentas = app.get_accounts()
    if cuentas:
        resultado = app.acquire_token_silent(SCOPES, account=cuentas[0])
        if resultado and "access_token" in resultado:
            _guardar_cache(cache)
            logger.info("Token OAuth2 obtenido desde caché.")
            return resultado["access_token"]

    # Device Code Flow (primera vez o token expirado)
    logger.info("Iniciando autenticación con Microsoft...")
    flow = app.initiate_device_flow(scopes=SCOPES)
    if "user_code" not in flow:
        raise RuntimeError(f"Error iniciando device flow: {flow.get('error_description')}")

    # Mostrar instrucciones al usuario
    print("\n" + "="*60)
    print("  AUTENTICACIÓN DE MICROSOFT REQUERIDA")
    print("="*60)
    print(f"\n  1. Abre en tu navegador: https://microsoft.com/devicelogin")
    print(f"  2. Introduce el código:  {flow['user_code']}")
    print(f"\n  Esperando que completes el login...")
    print("="*60 + "\n")

    resultado = app.acquire_token_by_device_flow(flow)

    if "access_token" not in resultado:
        error = resultado.get("error_description", resultado.get("error", "Error desconocido"))
        raise RuntimeError(f"Autenticación fallida: {error}")

    _guardar_cache(cache)
    logger.info("Autenticación completada y token guardado.")
    return resultado["access_token"]
