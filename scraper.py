"""
scraper.py - Búsqueda de empresas en múltiples fuentes y países
España (Sevilla, Málaga, Madrid) + Irlanda, Reino Unido, Alemania
"""

import requests
import logging
import time
import re
import warnings
from bs4 import BeautifulSoup
from urllib.parse import quote_plus, urljoin, urlparse
from typing import List, Dict, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed

# Silenciar warnings molestos de BeautifulSoup al encontrar XML (sitemaps, feeds…)
try:
    from bs4 import XMLParsedAsHTMLWarning, MarkupResemblesLocatorWarning
    warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)
    warnings.filterwarnings("ignore", category=MarkupResemblesLocatorWarning)
except ImportError:
    pass

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}
EMAIL_REGEX = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")

# Dominios claramente falsos / de plantilla
_DOMINIOS_FALSOS = {
    "example.com", "ejemplo.com", "prueba.com", "test.com", "demo.com",
    "sample.com", "placeholder.com", "tuempresa.com", "miempresa.com",
    "yourcompany.com", "mycompany.com", "empresa.com", "companyname.com",
    "correo.com", "email.com", "dominio.com", "sitio.com", "web.com",
    "domain.com", "mailinator.com", "tempmail.com", "trashmail.com",
    "yourdomain.com", "acme.com", "loremipsum.com",
}

# Partes locales del email claramente de relleno
_LOCALES_FALSOS = {
    "hola", "hello", "ejemplo", "example", "prueba", "test", "demo",
    "sample", "noreply", "no-reply", "donotreply", "do-not-reply",
    "change-this", "your-email", "tuemail", "tucorreo",
}


# ── UTILIDADES ────────────────────────────────────────────────────────────────

def extraer_emails_de_html(html: str) -> List[str]:
    """Extrae emails del HTML incluyendo patrones ofuscados."""
    excluir_ext = {"png", "jpg", "jpeg", "gif", "svg", "woff", "ttf", "css", "js",
                   "webp", "ico", "eot", "otf", "mp4", "mp3", "pdf", "zip"}
    emails = set()

    # 1. Regex estándar
    for e in EMAIL_REGEX.findall(html):
        emails.add(e.lower())

    # 2. mailto: links
    for m in re.findall(r'mailto:([a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,})', html):
        emails.add(m.lower())

    # 3. Ofuscaciones comunes: usuario [at] dominio [dot] com
    for m in re.findall(
        r'([a-zA-Z0-9._%+\-]+)\s*[\[\(]at[\]\)]\s*([a-zA-Z0-9.\-]+)\s*[\[\(]dot[\]\)]\s*([a-zA-Z]{2,})',
        html, re.IGNORECASE
    ):
        emails.add(f"{m[0]}@{m[1]}.{m[2]}".lower())

    # 4. Ofuscación: usuario (at) dominio.com
    for m in re.findall(
        r'([a-zA-Z0-9._%+\-]+)\s*[\[\(]at[\]\)]\s*([a-zA-Z0-9.\-]+\.[a-zA-Z]{2,})',
        html, re.IGNORECASE
    ):
        emails.add(f"{m[0]}@{m[1]}".lower())

    return [e for e in emails if e.split(".")[-1].lower() not in excluir_ext]


def filtrar_emails_validos(emails: List[str]) -> List[str]:
    """
    Descarta emails de plantilla, dominios falsos, locales de relleno
    y direcciones con estructura inválida (TLD roto, hashes de tracking…).
    """
    # TLD válido: solo letras, 2 a 24 caracteres (.es, .com, .technology…)
    tld_valido = re.compile(r"^[a-zA-Z]{2,24}$")
    # Extensiones de archivo que NO son TLDs reales (emails extraídos de rutas de imagen)
    ext_archivo = {"png", "jpg", "jpeg", "gif", "svg", "webp", "ico", "bmp",
                   "css", "js", "json", "xml", "pdf", "zip", "woff", "woff2",
                   "ttf", "eot", "otf", "mp4", "mp3", "avif", "tiff"}
    validos = []
    for email in emails:
        email = email.strip().lower()
        if email.count("@") != 1:
            continue
        local, dominio = email.split("@", 1)

        # Estructura mínima
        if not local or "." not in dominio:
            continue
        tld = dominio.rsplit(".", 1)[-1]
        # TLD debe ser solo letras (descarta "fairhall.es7", "dominio.es7"…)
        if not tld_valido.match(tld):
            continue
        # TLD no puede ser una extensión de archivo (descarta "foto@empresa.png")
        if tld in ext_archivo:
            continue
        # Local no puede empezar/terminar con punto ni tener dobles puntos
        if local.startswith(".") or local.endswith(".") or ".." in local:
            continue

        if dominio in _DOMINIOS_FALSOS:
            continue
        if local in _LOCALES_FALSOS:
            continue
        # Descartar dominios con palabras sospechosas
        if any(p in dominio for p in ("example", "prueba", "test.", "demo.", "sample")):
            continue
        # Descartar hashes de tracking (sentry, wixpress) y locales larguísimos
        if len(local) > 40 or any(p in dominio for p in ("sentry.", "wixpress.", "sentry-next")):
            continue

        validos.append(email)
    return validos


# Rutas a visitar en orden para buscar email de contacto
_RUTAS_CONTACTO = [
    "", "/contacto", "/contact", "/contact-us", "/contactanos",
    "/sobre-nosotros", "/about", "/about-us", "/quienes-somos",
    "/equipo", "/team", "/empresa", "/nosotros",
    "/trabaja-con-nosotros", "/work-with-us", "/careers", "/empleo", "/jobs",
    "/legal", "/privacidad", "/privacy", "/impressum",
]


def obtener_email_de_web(url: str) -> List[str]:
    """Versión rápida (compatibilidad). Llama a la exhaustiva."""
    return obtener_email_de_web_exhaustivo(url)


def obtener_email_de_web_exhaustivo(url: str, max_paginas: int = 8,
                                    timeout: int = 8, pausa: float = 0.0,
                                    tiempo_max: float = 25.0) -> List[str]:
    """
    Búsqueda exhaustiva de emails en la web de la empresa.
    Visita múltiples rutas, extrae mailto:, texto ofuscado y meta tags.

    Args:
        max_paginas: nº máximo de rutas a visitar por web.
        timeout: segundos máx. de espera de LECTURA por petición HTTP.
        pausa: segundos a esperar entre páginas (0 = sin pausa).
        tiempo_max: PRESUPUESTO TOTAL en segundos para toda la web.
                    Si se supera, se devuelve lo encontrado hasta el momento.
                    Esto garantiza que nunca se quede pillado.
    """
    if not url or not url.startswith("http"):
        return []

    inicio = time.monotonic()
    emails_encontrados: List[str] = []
    visitadas = 0
    # timeout de tupla: (connect=3s, read=timeout). Connect corto descarta
    # rápido los dominios muertos que aceptan TCP pero no responden.
    to = (3, timeout)

    for idx, ruta in enumerate(_RUTAS_CONTACTO):
        if visitadas >= max_paginas:
            break
        # Presupuesto de tiempo total agotado → salir ya
        if time.monotonic() - inicio > tiempo_max:
            break
        pagina_url = urljoin(url, ruta) if ruta else url
        try:
            r = requests.get(pagina_url, headers=HEADERS, timeout=to,
                             allow_redirects=True, stream=True)
            if r.status_code != 200:
                r.close()
                continue

            # Leer el contenido con límite de tamaño (1.5 MB) y de tiempo.
            # Evita descargar webs gigantes o que envían datos byte a byte.
            contenido = bytearray()
            for chunk in r.iter_content(chunk_size=16384):
                contenido += chunk
                if len(contenido) > 1_500_000:          # 1.5 MB máx por página
                    break
                if time.monotonic() - inicio > tiempo_max:  # presupuesto agotado
                    break
            r.close()
            visitadas += 1

            html = contenido.decode("utf-8", errors="ignore")

            # Extraer emails del HTML completo
            emails_encontrados += extraer_emails_de_html(html)

            # Parsear con BeautifulSoup para mailto: en atributos href
            soup = BeautifulSoup(html, "html.parser")
            for a in soup.find_all("a", href=True):
                href = a["href"]
                if href.lower().startswith("mailto:"):
                    email_raw = href[7:].split("?")[0].strip()
                    if "@" in email_raw:
                        emails_encontrados.append(email_raw.lower())

            # Meta tags (algunos ponen email ahí)
            for meta in soup.find_all("meta"):
                content = meta.get("content", "")
                emails_encontrados += extraer_emails_de_html(content)

            if emails_encontrados:
                # Si ya tenemos emails de RRHH, podemos parar antes
                buenos = [e for e in emails_encontrados
                          if any(p in e for p in ("hr", "rrhh", "talent", "careers", "jobs", "empleo"))]
                if buenos:
                    break

        except Exception:
            # Si la HOME (primera ruta) no conecta, el dominio está muerto:
            # no malgastar tiempo probando /contacto, /about, etc.
            if idx == 0:
                break
        if pausa > 0:
            time.sleep(pausa)

    return filtrar_emails_validos(list(set(emails_encontrados)))


def get_soup(url: str) -> Optional[BeautifulSoup]:
    try:
        r = requests.get(url, headers=HEADERS, timeout=10)
        r.raise_for_status()
        return BeautifulSoup(r.text, "html.parser")
    except Exception as e:
        logger.warning(f"Error al acceder a {url}: {e}")
        return None


def _empresa(nombre, descripcion, web, email, fuente, ciudad, pais, idioma="es") -> Dict:
    return {
        "nombre": nombre, "descripcion": descripcion, "web": web,
        "email": email, "fuente": fuente, "ciudad": ciudad,
        "pais": pais, "idioma": idioma,
    }


# ── LINKEDIN (funciona sin login, multi-localización) ─────────────────────────

def buscar_linkedin(terminos: List[str], ciudad: str, pais: str,
                    idioma: str = "es", max_paginas: int = 5) -> List[Dict]:
    """25 resultados por página, paginamos hasta max_paginas."""
    resultados = []
    for termino in terminos:
        for pagina in range(max_paginas):
            start = pagina * 25
            url = (
                f"https://www.linkedin.com/jobs/search/"
                f"?keywords={quote_plus(termino)}"
                f"&location={quote_plus(ciudad)}"
                f"&f_TPR=r2592000"
                f"&start={start}"
            )
            soup = get_soup(url)
            if not soup:
                break
            tarjetas = soup.select(".base-card")
            if not tarjetas:
                break
            antes = len(resultados)
            for tarjeta in tarjetas:
                try:
                    empresa = tarjeta.select_one(".base-search-card__subtitle")
                    titulo  = tarjeta.select_one(".base-search-card__title")
                    loc     = tarjeta.select_one(".job-search-card__location")
                    if empresa:
                        resultados.append(_empresa(
                            nombre      = empresa.get_text(strip=True),
                            descripcion = titulo.get_text(strip=True) if titulo else termino,
                            web="", email="", fuente="LinkedIn",
                            ciudad = loc.get_text(strip=True) if loc else ciudad,
                            pais=pais, idioma=idioma,
                        ))
                except Exception:
                    pass
            nuevos = len(resultados) - antes
            logger.info(f"LinkedIn [{termino} / {ciudad}] pág {pagina+1}: +{nuevos} (total {len(resultados)})")
            if nuevos == 0:
                break
            time.sleep(2.5)
    return resultados


# ── TECNOEMPLEO (España) ──────────────────────────────────────────────────────

def buscar_tecnoempleo(terminos: List[str], ciudad: str, max_paginas: int = 5) -> List[Dict]:
    """Pagina con &pagina=N."""
    resultados = []
    for termino in terminos:
        for pagina in range(1, max_paginas + 1):
            url = (
                f"https://www.tecnoempleo.com/busqueda-empleo.php"
                f"?te={quote_plus(termino)}&provincia={quote_plus(ciudad)}&pagina={pagina}"
            )
            soup = get_soup(url)
            if not soup:
                break
            ofertas = soup.select(".row.p-2.border.mb-3")
            if not ofertas:
                break
            antes = len(resultados)
            for oferta in ofertas:
                try:
                    titulo  = oferta.select_one("h3 a")
                    empresa = oferta.select_one(".text-muted")
                    if titulo and empresa:
                        resultados.append(_empresa(
                            nombre      = empresa.get_text(strip=True),
                            descripcion = titulo.get_text(strip=True),
                            web="", email="", fuente="Tecnoempleo",
                            ciudad=ciudad, pais="España", idioma="es",
                        ))
                except Exception:
                    pass
            nuevos = len(resultados) - antes
            logger.info(f"Tecnoempleo [{termino} / {ciudad}] pág {pagina}: +{nuevos} (total {len(resultados)})")
            if nuevos == 0:
                break
            time.sleep(2)
    return resultados


# ── INFOJOBS (España) ─────────────────────────────────────────────────────────

def buscar_infojobs(terminos: List[str], ciudad: str, max_paginas: int = 5) -> List[Dict]:
    """Pagina con &page=N."""
    resultados = []
    for termino in terminos:
        for pagina in range(1, max_paginas + 1):
            url = (
                f"https://www.infojobs.net/jobsearch/search-results/list.xhtml"
                f"?keyword={quote_plus(termino)}&province={quote_plus(ciudad)}&page={pagina}"
            )
            soup = get_soup(url)
            if not soup:
                break
            ofertas = soup.select("li.ij-OfferCardContent")
            if not ofertas:
                break
            antes = len(resultados)
            for oferta in ofertas:
                try:
                    empresa = oferta.select_one(".ij-OfferCardContent-description-title-company")
                    titulo  = oferta.select_one("h2 a")
                    loc     = oferta.select_one(".ij-OfferCardContent-description-list-item")
                    if empresa:
                        resultados.append(_empresa(
                            nombre      = empresa.get_text(strip=True),
                            descripcion = titulo.get_text(strip=True) if titulo else termino,
                            web="", email="", fuente="InfoJobs",
                            ciudad = loc.get_text(strip=True) if loc else ciudad,
                            pais="España", idioma="es",
                        ))
                except Exception:
                    pass
            nuevos = len(resultados) - antes
            logger.info(f"InfoJobs [{termino} / {ciudad}] pág {pagina}: +{nuevos} (total {len(resultados)})")
            if nuevos == 0:
                break
            time.sleep(2)
    return resultados


# ── INDEED (multi-país) ───────────────────────────────────────────────────────

INDEED_DOMINIOS = {
    "España":         "https://es.indeed.com",
    "Ireland":        "https://ie.indeed.com",
    "United Kingdom": "https://uk.indeed.com",
    "Germany":        "https://de.indeed.com",
}

def buscar_indeed(terminos: List[str], ciudad: str, pais: str,
                  idioma: str = "es", max_paginas: int = 5) -> List[Dict]:
    """10 resultados por página, paginamos con &start=N."""
    base = INDEED_DOMINIOS.get(pais, "https://es.indeed.com")
    resultados = []
    for termino in terminos:
        for pagina in range(max_paginas):
            start = pagina * 10
            url = f"{base}/jobs?q={quote_plus(termino)}&l={quote_plus(ciudad)}&start={start}"
            soup = get_soup(url)
            if not soup:
                break
            tarjetas = soup.select(".job_seen_beacon")
            if not tarjetas:
                break
            antes = len(resultados)
            for tarjeta in tarjetas:
                try:
                    empresa = tarjeta.select_one("[data-testid='company-name']")
                    titulo  = tarjeta.select_one("h2.jobTitle")
                    loc     = tarjeta.select_one("[data-testid='text-location']")
                    if empresa:
                        resultados.append(_empresa(
                            nombre      = empresa.get_text(strip=True),
                            descripcion = titulo.get_text(strip=True) if titulo else termino,
                            web="", email="", fuente="Indeed",
                            ciudad = loc.get_text(strip=True) if loc else ciudad,
                            pais=pais, idioma=idioma,
                        ))
                except Exception:
                    pass
            nuevos = len(resultados) - antes
            logger.info(f"Indeed [{termino} / {ciudad}] pág {pagina+1}: +{nuevos} (total {len(resultados)})")
            if nuevos == 0:
                break
            time.sleep(2)
    return resultados


# ── DUCKDUCKGO (reemplaza Google, más tolerante a scrapers) ──────────────────

# ── GOOGLE CUSTOM SEARCH API + DUCKDUCKGO FALLBACK ───────────────────────────

def _dominio(url: str) -> str:
    """Normaliza una URL a su dominio (sin www) para deduplicar."""
    try:
        net = urlparse(url).netloc.lower()
        return net[4:] if net.startswith("www.") else net
    except Exception:
        return (url or "").lower()


def _dedup_empresas(empresas: List[Dict]) -> List[Dict]:
    """Elimina duplicados por dominio web; si no hay web, por nombre."""
    vistos = set()
    unicas = []
    for emp in empresas:
        web = (emp.get("web") or "").strip()
        if web:
            clave = _dominio(web)
        else:
            clave = "n:" + (emp.get("nombre") or "").strip().lower()
        if not clave:
            unicas.append(emp)          # sin clave fiable → conservar
            continue
        if clave in vistos:
            continue
        vistos.add(clave)
        unicas.append(emp)
    return unicas


def _buscar_queries_serper(queries: List[str], serper_key: str,
                           ciudad: str, pais: str, idioma: str,
                           max_paginas: int = 3,
                           max_workers: int = 4) -> List[Dict]:
    """
    Ejecuta varias queries de Serper EN PARALELO y devuelve los resultados
    ya deduplicados por dominio. Es el núcleo eficiente de búsqueda usado
    tanto por buscar_google() como por buscar_eures().
    """
    resultados: List[Dict] = []
    workers = max(1, min(max_workers, len(queries)))
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futuros = {
            executor.submit(_buscar_serper, q, serper_key,
                            ciudad, pais, idioma, max_paginas): q
            for q in queries
        }
        for fut in as_completed(futuros):
            q = futuros[fut]
            try:
                nuevos = fut.result()
                resultados += nuevos
                logger.info(f"Serper [{q[:45]}...] → +{len(nuevos)} "
                            f"(acum {len(resultados)})")
            except Exception as e:
                logger.warning(f"Serper [{q[:40]}]: {e}")
    return _dedup_empresas(resultados)


def _buscar_serper(query: str, serper_key: str,
                   ciudad: str, pais: str, idioma: str,
                   max_paginas: int = 1) -> List[Dict]:
    """
    Búsqueda via Serper.dev — resultados reales de Google, 2500/mes gratis.
    Pagina con el parámetro 'page' (10 resultados por página).
    """
    resultados = []
    for pagina in range(1, max_paginas + 1):
        try:
            r = requests.post(
                "https://google.serper.dev/search",
                headers={"X-API-KEY": serper_key, "Content-Type": "application/json"},
                json={"q": query, "num": 10, "page": pagina,
                      "gl": "es" if idioma == "es" else "us",
                      "hl": "es" if idioma == "es" else "en"},
                timeout=10,
            )
            if r.status_code == 429:
                logger.warning("Serper: cuota agotada (2500/mes)")
                break
            if r.status_code != 200:
                logger.warning(f"Serper: HTTP {r.status_code} — {r.text[:120]}")
                break
            data  = r.json()
            items = data.get("organic", [])
            if not items:
                break
            antes = len(resultados)
            for item in items:
                resultados.append(_empresa(
                    nombre      = item.get("title", ""),
                    descripcion = item.get("snippet", ""),
                    web         = item.get("link", ""),
                    email="", fuente="Google",
                    ciudad=ciudad, pais=pais, idioma=idioma,
                ))
            logger.info(f"Serper [{query[:40]}...] pág {pagina}: +{len(resultados)-antes} (total {len(resultados)})")
            if len(items) < 10:
                break  # última página
            time.sleep(0.5)
        except Exception as e:
            logger.warning(f"Serper [{query[:40]}]: {e}")
            break
    return resultados


def _buscar_google_api(query: str, api_key: str, cx: str,
                       ciudad: str, pais: str, idioma: str) -> List[Dict]:
    """Búsqueda via Google Custom Search JSON API (100/día gratis)."""
    resultados = []
    # La API devuelve max 10 por petición; podemos paginar con &start=
    for start in [1, 11]:   # 2 páginas = hasta 20 resultados por query
        try:
            r = requests.get(
                "https://www.googleapis.com/customsearch/v1",
                params={"key": api_key, "cx": cx, "q": query,
                        "start": start, "num": 10},
                timeout=10,
            )
            if r.status_code == 429:
                logger.warning("Google CSE: cuota diaria agotada (100/día)")
                break
            if r.status_code != 200:
                logger.warning(f"Google CSE: HTTP {r.status_code} — {r.text[:120]}")
                break
            data = r.json()
            items = data.get("items", [])
            if not items:
                break
            for item in items:
                resultados.append(_empresa(
                    nombre      = item.get("title", ""),
                    descripcion = item.get("snippet", ""),
                    web         = item.get("link", ""),
                    email="", fuente="Google",
                    ciudad=ciudad, pais=pais, idioma=idioma,
                ))
            time.sleep(1)
        except Exception as e:
            logger.warning(f"Google CSE [{query[:40]}]: {e}")
            break
    return resultados


def buscar_google(terminos: List[str], ciudad: str, pais: str,
                  idioma: str = "es", api_key: str = "", cx: str = "",
                  serper_key: str = "", max_paginas: int = 3) -> List[Dict]:
    """
    Búsqueda de empresas tech en una ciudad/país.
    Prioridad: 1) Serper.dev (en PARALELO)  2) Google CSE  3) DuckDuckGo.
    Las queries apuntan a webs de empresas (con email de contacto),
    no a portales de empleo, para maximizar emails recopilables.
    """
    if idioma == "en":
        queries = [
            f'software development company "{ciudad}" contact email',
            f'web and app development agency "{ciudad}"',
            f'tech startup "{ciudad}" careers',
            f'IT software house "{ciudad}" "get in touch"',
        ]
    else:
        queries = [
            f'empresa desarrollo software "{ciudad}" contacto',
            f'agencia desarrollo web y apps "{ciudad}"',
            f'startup tecnológica "{ciudad}" "trabaja con nosotros"',
            f'consultora IT software "{ciudad}" empleo',
        ]

    # ── 1. Serper.dev en PARALELO (Google real, 2500/mes gratis, sin tarjeta) ─
    if serper_key:
        return _buscar_queries_serper(queries, serper_key, ciudad, pais,
                                      idioma, max_paginas)

    resultados = []

    # ── 2. Google Custom Search API ───────────────────────────────────────────
    if api_key and cx:
        for query in queries:
            nuevos = _buscar_google_api(query, api_key, cx, ciudad, pais, idioma)
            resultados += nuevos
            logger.info(f"Google CSE [{query[:45]}...] → +{len(nuevos)} (total {len(resultados)})")
            time.sleep(1)
        return _dedup_empresas(resultados)

    # ── 3. DuckDuckGo HTML (fallback sin API key) ─────────────────────────────
    for query in queries:
        intentos = 0
        while intentos < 4:
            try:
                r = requests.post(
                    "https://html.duckduckgo.com/html/",
                    data={"q": query, "kl": "es-es" if idioma == "es" else "en-us"},
                    headers={**HEADERS, "Content-Type": "application/x-www-form-urlencoded"},
                    timeout=15,
                )
                if r.status_code == 202:
                    espera = 8 + intentos * 5
                    logger.info(f"DuckDuckGo [{ciudad}]: HTTP 202, esperando {espera}s...")
                    time.sleep(espera)
                    intentos += 1
                    continue
                if r.status_code != 200:
                    logger.warning(f"DuckDuckGo [{ciudad}]: HTTP {r.status_code}")
                    break
                soup = BeautifulSoup(r.text, "html.parser")
                antes = len(resultados)
                for result in soup.select(".result"):
                    try:
                        titulo  = result.select_one(".result__title")
                        a_tag   = result.select_one("a.result__a")
                        snippet = result.select_one(".result__snippet")
                        if not titulo or not a_tag:
                            continue
                        href = a_tag.get("href", "")
                        if "uddg=" in href:
                            from urllib.parse import unquote, parse_qs
                            qs = parse_qs(urlparse(href).query)
                            href = unquote(qs.get("uddg", [href])[0])
                        if not href.startswith("http"):
                            continue
                        resultados.append(_empresa(
                            nombre      = titulo.get_text(strip=True),
                            descripcion = snippet.get_text(strip=True) if snippet else "",
                            web=href, email="", fuente="DuckDuckGo",
                            ciudad=ciudad, pais=pais, idioma=idioma,
                        ))
                    except Exception:
                        pass
                logger.info(f"DuckDuckGo [{query[:45]}...] → +{len(resultados)-antes} (total {len(resultados)})")
                break
            except Exception as e:
                logger.warning(f"DuckDuckGo [{ciudad}]: {e}")
                break
        time.sleep(4)

    return _dedup_empresas(resultados)


# ── EURES (portal europeo de empleo, pan-europeo) ────────────────────────────

# Países cubiertos por EURES (UE + EEE + Suiza) con el idioma de búsqueda
# preferente. Replicamos la cobertura del portal EURES buscando empleadores
# tecnológicos país por país.
EURES_PAISES = [
    ("Spain", "es"),
    ("Portugal", "en"),
    ("France", "en"),
    ("Germany", "en"),
    ("Netherlands", "en"),
    ("Ireland", "en"),
    ("Belgium", "en"),
    ("Italy", "en"),
    ("Sweden", "en"),
    ("Denmark", "en"),
    ("Austria", "en"),
    ("Poland", "en"),
    ("Switzerland", "en"),
    ("Norway", "en"),
    ("Finland", "en"),
    ("Luxembourg", "en"),
]


def buscar_eures(serper_key: str = "",
                 paises: Optional[List] = None,
                 max_paginas: int = 2,
                 max_workers: int = 4) -> List[Dict]:
    """
    Búsqueda estilo EURES (portal europeo de empleo) a nivel pan-europeo.

    NOTA TÉCNICA: la API oficial de EURES (europa.eu/eures/api/jv-searchengine)
    está protegida con Spring-Security CSRF + CAPTCHA y responde
    'Access Denied' (403) a cualquier petición automatizada, por lo que no es
    accesible sin credenciales de socio ni un navegador headless. Para cubrir
    el MISMO mercado laboral (empresas tech de toda la UE/EEE) buscamos
    empleadores tecnológicos por país con el motor que sí funciona (Serper).
    Las empresas encontradas se etiquetan con fuente="EURES".
    """
    if not serper_key:
        logger.warning("EURES: requiere serper_key (Serper.dev); se omite.")
        return []

    paises = paises or EURES_PAISES
    resultados: List[Dict] = []

    for pais, idioma in paises:
        if idioma == "es":
            queries = [
                f'empresa desarrollo software {pais} empleo contacto',
                f'startup tecnológica {pais} "trabaja con nosotros"',
            ]
        else:
            queries = [
                f'software development company {pais} careers contact',
                f'tech startup IT company {pais} jobs hiring',
            ]
        nuevos = _buscar_queries_serper(queries, serper_key, pais, pais,
                                        idioma, max_paginas, max_workers)
        for emp in nuevos:
            emp["fuente"] = "EURES"
        resultados += nuevos
        logger.info(f"🇪🇺 EURES [{pais}] → +{len(nuevos)} (total {len(resultados)})")

    return _dedup_empresas(resultados)


# ── GITHUB API (organizaciones tech por ubicación y lenguaje) ─────────────────

GITHUB_API = "https://api.github.com"

# Lenguajes que indican empresas tech relevantes para el perfil
GITHUB_LENGUAJES = [
    "dart", "javascript", "typescript", "python",
    "swift", "kotlin", "vue", "astro"
]

def buscar_github(ciudades: List[str], paises: List[str],
                  idioma_email: str = "es",
                  token: str = "") -> List[Dict]:
    """
    Busca organizaciones en GitHub por ubicación y lenguaje.
    Extrae su web/blog para luego buscar email con enriquecer_con_emails().
    Con token: 5000 req/hora. Sin token: 60 req/hora.
    """
    headers = {**HEADERS, "Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    ubicaciones = ciudades + paises
    resultados  = []
    vistos      = set()

    for ubicacion in ubicaciones:
        for lenguaje in GITHUB_LENGUAJES:
            query     = f"type:org location:{ubicacion} language:{lenguaje}"
            pagina    = 1
            max_pags  = 5   # hasta 500 orgs por combinación (100 × 5 páginas)

            while pagina <= max_pags:
                url = (
                    f"{GITHUB_API}/search/users"
                    f"?q={quote_plus(query)}&per_page=100&page={pagina}"
                )
                try:
                    r = requests.get(url, headers=headers, timeout=10)
                    if r.status_code == 403:
                        logger.warning("GitHub: rate limit alcanzado, espera 60s...")
                        time.sleep(60)
                        r = requests.get(url, headers=headers, timeout=10)
                    if r.status_code != 200:
                        logger.warning(f"GitHub {r.status_code} para {ubicacion}/{lenguaje}")
                        break
                    data  = r.json()
                    items = data.get("items", [])
                    total = data.get("total_count", 0)
                    logger.info(
                        f"GitHub [{lenguaje} / {ubicacion}] pág {pagina}: "
                        f"{len(items)} orgs (total: {total})"
                    )
                    if not items:
                        break

                    for org in items:
                        login = org.get("login", "")
                        if login in vistos:
                            continue
                        vistos.add(login)

                        # Obtener perfil completo de la organización
                        time.sleep(0.4)
                        perfil_r = requests.get(
                            f"{GITHUB_API}/orgs/{login}",
                            headers=headers, timeout=10
                        )
                        if perfil_r.status_code != 200:
                            perfil_r = requests.get(
                                f"{GITHUB_API}/users/{login}",
                                headers=headers, timeout=10
                            )
                        if perfil_r.status_code != 200:
                            continue

                        perfil = perfil_r.json()
                        nombre = perfil.get("name") or login
                        web    = perfil.get("blog", "") or ""
                        if web and not web.startswith("http"):
                            web = "https://" + web
                        descripcion = perfil.get("description") or f"Organización tech en {ubicacion} ({lenguaje})"
                        loc_real    = perfil.get("location") or ubicacion

                        resultados.append(_empresa(
                            nombre      = nombre,
                            descripcion = descripcion,
                            web         = web,
                            email       = perfil.get("email", "") or "",
                            fuente      = "GitHub",
                            ciudad      = loc_real,
                            pais        = paises[0] if paises else ubicacion,
                            idioma      = idioma_email,
                        ))

                    # Si ya trajimos todos los resultados disponibles, parar
                    if len(items) < 100 or pagina * 100 >= min(total, 1000):
                        break
                    pagina += 1

                except Exception as e:
                    logger.warning(f"Error GitHub [{ubicacion}/{lenguaje}] pág {pagina}: {e}")
                    break
                time.sleep(1.5)

    logger.info(f"GitHub: {len(resultados)} organizaciones únicas encontradas")
    return resultados


# ── ENRIQUECIMIENTO DE EMAILS ─────────────────────────────────────────────────

_PRIORIDAD_EMAIL = ["rrhh", "hr", "empleo", "talent", "jobs", "careers",
                    "work", "recruit", "info", "contact", "hola"]


def _elegir_mejor_email(emails: List[str]) -> str:
    """De una lista de emails válidos, elige el más relevante para RRHH."""
    for p in _PRIORIDAD_EMAIL:
        match = next((e for e in emails if p in e.lower()), None)
        if match:
            return match
    return emails[0]


def enriquecer_con_emails(empresas: List[Dict]) -> List[Dict]:
    for emp in empresas:
        if emp.get("web") and not emp.get("email"):
            logger.info(f"Buscando email en: {emp['web']}")
            emails = obtener_email_de_web_exhaustivo(emp["web"])
            if emails:
                elegido = _elegir_mejor_email(emails)
                emp["email"] = elegido
                logger.info(f"  → {elegido}")
    return empresas


# ── FUNCIÓN PRINCIPAL ─────────────────────────────────────────────────────────

def buscar_todas_las_fuentes(config: dict) -> List[Dict]:
    fuentes_cfg  = config["fuentes"]
    loc_cfg      = config["localizacion"]
    terms_es     = config["filtros"]["palabras_clave_es"]
    terms_en     = config["filtros"]["palabras_clave_en"]
    max_pags     = config["filtros"].get("max_paginas", 5)
    github_token = config.get("github", {}).get("token", "")
    google_key   = config.get("google_search", {}).get("api_key", "")
    google_cx    = config.get("google_search", {}).get("cx", "")
    serper_key   = config.get("serper", {}).get("api_key", "")
    todas        = []

    # ── ESPAÑA ────────────────────────────────────────────────────────────────
    if loc_cfg["espana"]["activo"]:
        ciudades_es = [c["nombre"] for c in
                       sorted(loc_cfg["espana"]["ciudades"], key=lambda x: x["prioridad"])]
        for ciudad in ciudades_es:
            logger.info(f"\n--- España / {ciudad} ---")
            if fuentes_cfg.get("linkedin"):
                todas += buscar_linkedin(terms_es, ciudad, "España", "es", max_pags)
            if fuentes_cfg.get("tecnoempleo"):
                todas += buscar_tecnoempleo(terms_es, ciudad, max_pags)
            if fuentes_cfg.get("infojobs"):
                todas += buscar_infojobs(terms_es, ciudad, max_pags)
            if fuentes_cfg.get("stackoverflow_jobs"):
                todas += buscar_indeed(terms_es, ciudad, "España", "es", max_pags)
            if fuentes_cfg.get("busqueda_google"):
                todas += buscar_google(terms_es, ciudad, "España", "es",
                                       api_key=google_key, cx=google_cx,
                                       serper_key=serper_key, max_paginas=max_pags)

        # GitHub para España (una sola llamada con todas las ciudades)
        if fuentes_cfg.get("github"):
            logger.info(f"\n--- GitHub / España ---")
            todas += buscar_github(
                ciudades    = ciudades_es,
                paises      = ["Spain", "España"],
                idioma_email = "es",
                token       = github_token,
            )

    # ── INTERNACIONAL ─────────────────────────────────────────────────────────
    if loc_cfg["internacional"]["activo"]:
        for pais_cfg in loc_cfg["internacional"]["paises"]:
            pais   = pais_cfg["nombre"]
            idioma = pais_cfg["idioma"]
            for ciudad in pais_cfg["ciudades"]:
                logger.info(f"\n--- {pais} / {ciudad} ---")
                if fuentes_cfg.get("linkedin"):
                    todas += buscar_linkedin(terms_en, ciudad, pais, idioma, max_pags)
                if fuentes_cfg.get("stackoverflow_jobs"):
                    todas += buscar_indeed(terms_en, ciudad, pais, idioma, max_pags)
                if fuentes_cfg.get("busqueda_google"):
                    todas += buscar_google(terms_en, ciudad, pais, idioma,
                                           api_key=google_key, cx=google_cx,
                                           serper_key=serper_key, max_paginas=max_pags)

            # GitHub para este país (una sola llamada con todas sus ciudades)
            if fuentes_cfg.get("github"):
                logger.info(f"\n--- GitHub / {pais} ---")
                todas += buscar_github(
                    ciudades    = pais_cfg["ciudades"],
                    paises      = [pais],
                    idioma_email = idioma,
                    token       = github_token,
                )

    todas = enriquecer_con_emails(todas)
    logger.info(f"\nTotal empresas encontradas: {len(todas)}")
    return todas
