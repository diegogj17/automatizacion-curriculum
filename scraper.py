"""
scraper.py - Búsqueda de empresas en múltiples fuentes y países
España (Sevilla, Málaga, Madrid) + Irlanda, Reino Unido, Alemania
"""

import requests
import logging
import time
import re
from bs4 import BeautifulSoup
from urllib.parse import quote_plus, urljoin
from typing import List, Dict, Optional

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
    """Descarta emails de plantilla, dominios falsos y locales de relleno."""
    validos = []
    for email in emails:
        if "@" not in email:
            continue
        local, dominio = email.lower().split("@", 1)
        if dominio in _DOMINIOS_FALSOS:
            continue
        if local in _LOCALES_FALSOS:
            continue
        # Descartar dominios con palabras sospechosas
        if any(p in dominio for p in ("example", "prueba", "test.", "demo.", "sample")):
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


def obtener_email_de_web_exhaustivo(url: str, max_paginas: int = 8) -> List[str]:
    """
    Búsqueda exhaustiva de emails en la web de la empresa.
    Visita múltiples rutas, extrae mailto:, texto ofuscado y meta tags.
    """
    if not url or not url.startswith("http"):
        return []

    emails_encontrados: List[str] = []
    visitadas = 0

    for ruta in _RUTAS_CONTACTO:
        if visitadas >= max_paginas:
            break
        pagina_url = urljoin(url, ruta) if ruta else url
        try:
            r = requests.get(pagina_url, headers=HEADERS, timeout=10,
                             allow_redirects=True)
            if r.status_code != 200:
                continue
            visitadas += 1

            # Extraer emails del HTML completo
            emails_encontrados += extraer_emails_de_html(r.text)

            # También parsear con BeautifulSoup para mailto: en atributos href
            soup = BeautifulSoup(r.text, "html.parser")
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
            pass
        time.sleep(1)

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

def buscar_google(terminos: List[str], ciudad: str, pais: str,
                  idioma: str = "es") -> List[Dict]:
    """
    Búsqueda de empresas via DuckDuckGo HTML.
    Más fiable que Google para scraping (no CAPTCHA, no JS obligatorio).
    Incluye reintentos automáticos si DuckDuckGo devuelve 202 (rate limit suave).
    """
    resultados = []
    queries = [
        f'empresa software tecnologia "{ciudad}" contacto',
        f'startup app desarrollo web "{ciudad}"',
        f'agencia digital programacion "{ciudad}"',
    ]
    if idioma == "en":
        queries = [
            f'tech company software "{ciudad}" contact',
            f'startup app development "{ciudad}"',
        ]

    for query in queries:
        intentos = 0
        max_intentos = 4
        while intentos < max_intentos:
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
                            from urllib.parse import unquote, urlparse, parse_qs
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

                nuevos = len(resultados) - antes
                logger.info(f"DuckDuckGo [{query[:45]}...] → +{nuevos} (total {len(resultados)})")
                break  # éxito, salir del while

            except Exception as e:
                logger.warning(f"DuckDuckGo [{ciudad}]: {e}")
                break

        time.sleep(4)  # pausa entre queries para no saturar

    return resultados


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
                todas += buscar_google(terms_es, ciudad, "España", "es")

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
                    todas += buscar_google(terms_en, ciudad, pais, idioma)

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
