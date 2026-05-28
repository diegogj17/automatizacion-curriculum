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


# ── UTILIDADES ────────────────────────────────────────────────────────────────

def extraer_emails_de_html(html: str) -> List[str]:
    excluir = {"png", "jpg", "jpeg", "gif", "svg", "woff", "ttf", "css", "js"}
    emails = EMAIL_REGEX.findall(html)
    return list({e.lower() for e in emails if e.split(".")[-1].lower() not in excluir})


def obtener_email_de_web(url: str) -> List[str]:
    emails = []
    paginas = [url, urljoin(url, "/contacto"), urljoin(url, "/contact"),
               urljoin(url, "/sobre-nosotros"), urljoin(url, "/about")]
    for pagina in paginas:
        try:
            r = requests.get(pagina, headers=HEADERS, timeout=8)
            if r.status_code == 200:
                emails += extraer_emails_de_html(r.text)
        except Exception:
            pass
        time.sleep(1)
    return list(set(emails))


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


# ── GOOGLE (multi-país) ───────────────────────────────────────────────────────

def buscar_google(terminos: List[str], ciudad: str, pais: str,
                  idioma: str = "es") -> List[Dict]:
    resultados = []
    queries = [f'empresa programacion contratar "{t}" "{ciudad}" email contacto'
               for t in terminos[:2]]
    for query in queries:
        url = f"https://www.google.com/search?q={quote_plus(query)}&num=8"
        soup = get_soup(url)
        if not soup:
            continue
        for result in soup.select("div.g")[:6]:
            try:
                titulo  = result.select_one("h3")
                link    = result.select_one("a")
                snippet = result.select_one(".VwiC3b")
                if titulo and link:
                    href = link.get("href", "")
                    if href.startswith("http"):
                        resultados.append(_empresa(
                            nombre      = titulo.get_text(strip=True),
                            descripcion = snippet.get_text(strip=True) if snippet else "",
                            web=href, email="", fuente="Google",
                            ciudad=ciudad, pais=pais, idioma=idioma,
                        ))
            except Exception:
                pass
        logger.info(f"Google [{ciudad}]: {len(resultados)} resultados acum.")
        time.sleep(3)
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

def enriquecer_con_emails(empresas: List[Dict]) -> List[Dict]:
    prioridad = ["rrhh", "hr", "empleo", "talent", "jobs", "careers",
                 "work", "recruit", "info", "contact", "hola"]
    for emp in empresas:
        if emp.get("web") and not emp.get("email"):
            logger.info(f"Buscando email en: {emp['web']}")
            emails = obtener_email_de_web(emp["web"])
            if emails:
                elegido = emails[0]
                for p in prioridad:
                    match = next((e for e in emails if p in e.lower()), None)
                    if match:
                        elegido = match
                        break
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
