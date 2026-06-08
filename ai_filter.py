"""
ai_filter.py - Filtrado y personalización de emails con Ollama (Mistral)
Analiza empresas y genera emails personalizados para cada una
"""

import requests
import logging
import json
from typing import List, Dict

logger = logging.getLogger(__name__)

OLLAMA_URL = "http://localhost:11434/api/generate"


def _llamar_ollama(prompt: str, model: str = "mistral:latest",
                   temperatura: float = 0.7) -> str:
    """Llama a la API local de Ollama y devuelve el texto generado."""
    payload = {
        "model":  model,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": temperatura}
    }
    try:
        r = requests.post(OLLAMA_URL, json=payload, timeout=120)
        r.raise_for_status()
        return r.json().get("response", "").strip()
    except Exception as e:
        logger.error(f"Error al llamar a Ollama: {e}")
        return ""


def _tech_coincidentes(empresa_tecnologias, skills: dict) -> list:
    """
    Calcula qué tecnologías de la EMPRESA coinciden con las que domina el
    CANDIDATO. Devuelve la lista de coincidencias (nombres tal y como los
    tiene el candidato), p.ej. ["React", "Firebase"].

    'empresa_tecnologias' puede ser una lista o un string CSV ("React, Firebase").
    """
    if not empresa_tecnologias:
        return []
    if isinstance(empresa_tecnologias, str):
        empresa_tech = [t.strip() for t in empresa_tecnologias.split(",") if t.strip()]
    else:
        empresa_tech = list(empresa_tecnologias)

    # Expandir tecnologías implícitas (Next.js → React, Flutter → Dart, …) para
    # que el matching sea robusto aunque se guardaran sin expandir. Fuente única
    # de verdad: scraper._TECH_IMPLICA.
    try:
        from scraper import _TECH_IMPLICA
        expandida = list(empresa_tech)
        for tech in empresa_tech:
            expandida += _TECH_IMPLICA.get(tech, [])
        empresa_tech = expandida
    except Exception:
        pass

    # Skills del candidato (principales + secundarias), normalizadas
    skills_candidato = list(skills.get("principales", [])) + list(skills.get("secundarias", []))

    # Expandir "HTML/CSS" en sus componentes para casar mejor
    expandidas = {}
    for s in skills_candidato:
        clave = s.lower().strip()
        expandidas[clave] = s
        if "/" in clave:                       # "html/css" → "html", "css"
            for parte in clave.split("/"):
                expandidas[parte.strip()] = s

    coincidencias = []
    vistos = set()
    for tech in empresa_tech:
        clave = tech.lower().strip()
        if clave in expandidas:
            nombre = expandidas[clave]
            if nombre not in vistos:
                coincidencias.append(nombre)
                vistos.add(nombre)
    return coincidencias


def analizar_relevancia(empresa: dict, skills: dict, model: str) -> int:
    """
    Pide a Ollama que puntúe del 0-10 si la empresa es relevante
    para el perfil del candidato. Devuelve la puntuación (int).
    """
    prompt = f"""Eres un asistente de búsqueda de empleo. Tu misión es determinar si esta empresa
podría estar interesada en contratar a un desarrollador de software junior.

El candidato tiene experiencia en: {', '.join(skills['principales'])} y también: {', '.join(skills['secundarias'])}.

Empresa: {empresa['nombre']}
Descripción: {empresa['descripcion']}
Fuente: {empresa['fuente']}

CRITERIO IMPORTANTE: No importa que la empresa no tenga una oferta activa.
Basta con que sea una empresa tecnológica, agencia digital, consultora de software,
startup, empresa con app móvil, o cualquier negocio que use o desarrolle software.
Si la empresa tiene relación con tecnología, desarrollo web, apps o software, puntúala alto.

Responde ÚNICAMENTE con un número del 0 al 10.
0 = empresa sin ninguna relación con tecnología (restaurante, tienda física, etc.)
5 = empresa tech genérica, podría necesitar desarrolladores
10 = empresa de desarrollo de software, apps móviles, web o tecnología digital
Solo el número, sin texto adicional."""

    respuesta = _llamar_ollama(prompt, model)
    try:
        puntuacion = int(respuesta.strip().split()[0])
        return max(0, min(10, puntuacion))
    except Exception:
        logger.warning(f"No se pudo parsear puntuación para {empresa['nombre']}: '{respuesta}'")
        return 5


def generar_email_personalizado(empresa: dict, personal: dict, skills: dict,
                                 model: str) -> dict:
    """
    Genera un email de candidatura personalizado usando Ollama.
    Devuelve dict con 'asunto', 'cuerpo' y 'cv_path'.
    """
    idioma = empresa.get('idioma', 'es')

    # ── Tecnologías de la empresa que coinciden con las del candidato ──────────
    empresa_tech = empresa.get('tecnologias', '')
    coincidencias = _tech_coincidentes(empresa_tech, skills)
    bloque_tech_es = ""
    bloque_tech_en = ""
    if coincidencias:
        lista = ", ".join(coincidencias)
        bloque_tech_es = (
            f"\n\nTECNOLOGÍAS DETECTADAS EN LA WEB DE LA EMPRESA QUE EL CANDIDATO "
            f"TAMBIÉN DOMINA: {lista}.\n"
            f"IMPORTANTE: menciona de forma NATURAL y específica que has visto que "
            f"trabajan con {lista} y que el candidato tiene experiencia con esas mismas "
            f"tecnologías. Esto demuestra que has investigado la empresa. No lo fuerces "
            f"ni lo pongas como una lista; intégralo en una frase fluida."
        )
        bloque_tech_en = (
            f"\n\nTECHNOLOGIES DETECTED ON THE COMPANY'S WEBSITE THAT THE CANDIDATE "
            f"ALSO MASTERS: {lista}.\n"
            f"IMPORTANT: naturally and specifically mention that you noticed they work "
            f"with {lista} and that the candidate has hands-on experience with those same "
            f"technologies. This shows you researched the company. Don't force it or make "
            f"it a list; weave it into a fluent sentence."
        )

    # Extraer proyectos destacados si existen
    proyectos = skills.get('proyectos_destacados', [])
    proyecto_str_en = ""
    proyecto_str_es = ""
    if proyectos:
        p = proyectos[0]
        proyecto_str_en = (
            f"\n- Featured project: {p['nombre']} — {p['descripcion']} "
            f"Built with {p['tecnologias']}."
        )
        proyecto_str_es = (
            f"\n- Proyecto destacado: {p['nombre']} — {p['descripcion']} "
            f"Desarrollado con {p['tecnologias']}."
        )

    if idioma == 'en':
        cv_path = personal.get('cv_en', personal.get('cv_path', ''))
        prompt = f"""You are an expert HR professional and business writer in English.

Write a PERSONALIZED, professional and concise speculative job application email (max 200 words).

CANDIDATE DETAILS:
- Name: {personal['nombre']}
- Speciality: {skills['nivel']} Developer in {', '.join(skills['principales'])}
- Secondary technologies: {', '.join(skills['secundarias'])}{proyecto_str_en}
- Phone: {personal['telefono']}

TARGET COMPANY:
- Name: {empresa['nombre']}
- Description/Position found: {empresa['descripcion']}
- City: {empresa.get('ciudad', 'Ireland')}
- Country: {empresa.get('pais', '')}
- Source: {empresa['fuente']}{bloque_tech_en}

INSTRUCTIONS:
1. Start with a professional greeting to the HR/Hiring team
2. Mention something specific about the company or the role you found
3. Briefly introduce the candidate and their most relevant skills
4. Naturally mention the Flitly project as proof of real published work (available on App Store and Google Play), without including any URLs or links
5. Mention the attached CV
6. Close with availability for interview and contact details
7. Tone: professional yet approachable, NOT generic

Respond in JSON format with exactly these keys:
{{"asunto": "...", "cuerpo": "..."}}"""
    else:
        cv_path = personal.get('cv_path', '')
        prompt = f"""Eres un experto en recursos humanos y redacción profesional en español.

Escribe un email de candidatura espontánea PERSONALIZADO, profesional y conciso (máx 200 palabras).

DATOS DEL CANDIDATO:
- Nombre: {personal['nombre']}
- Especialidad: Desarrollador {skills['nivel']} en {', '.join(skills['principales'])}
- Tecnologías secundarias: {', '.join(skills['secundarias'])}{proyecto_str_es}
- Teléfono: {personal['telefono']}

EMPRESA DESTINATARIA:
- Nombre: {empresa['nombre']}
- Descripción/Puesto visto: {empresa['descripcion']}
- Ciudad: {empresa.get('ciudad', 'España')}
- Fuente donde se encontró: {empresa['fuente']}{bloque_tech_es}

INSTRUCCIONES:
1. Empieza con un saludo profesional al departamento de RRHH
2. Menciona algo específico de la empresa o del puesto que encontraste
3. Presenta brevemente al candidato y sus habilidades más relevantes
4. Menciona de forma natural el proyecto Flitly como prueba de trabajo real publicado (disponible en App Store y Google Play), sin incluir ningún enlace ni URL
5. Indica que adjuntas el CV
6. Cierra con disponibilidad para entrevista y datos de contacto
7. Tono: profesional pero cercano, NO genérico

Responde en formato JSON con exactamente estas claves:
{{"asunto": "...", "cuerpo": "..."}}"""

    respuesta = _llamar_ollama(prompt, model, temperatura=0.8)

    # Intentar parsear JSON
    try:
        # Extraer JSON aunque haya texto alrededor
        inicio = respuesta.find("{")
        fin    = respuesta.rfind("}") + 1
        if inicio != -1 and fin > inicio:
            data = json.loads(respuesta[inicio:fin])
            return {
                "asunto": data.get("asunto", f"Candidatura espontánea - {skills['nivel']}"),
                "cuerpo": data.get("cuerpo", ""),
                "cv_path": cv_path
            }
    except Exception:
        pass

    # Fallback: usar la respuesta completa como cuerpo
    logger.warning(f"No se pudo parsear JSON para {empresa['nombre']}, usando fallback")
    asunto = f"Candidatura espontánea – Desarrollador {skills['nivel']} | {personal['nombre']}"
    return {"asunto": asunto, "cuerpo": respuesta, "cv_path": cv_path}


def filtrar_y_personalizar(empresas: List[Dict], config: dict) -> List[Dict]:
    """
    Para cada empresa:
    1. Analiza relevancia con IA
    2. Si relevancia >= 4 (empresa tech), genera email personalizado
    Devuelve lista enriquecida con 'relevancia', 'asunto' y 'cuerpo_email'.
    """
    model    = config["ollama"]["model"]
    personal = config["personal"]
    skills   = config["skills"]
    resultados = []

    for i, empresa in enumerate(empresas):
        logger.info(f"[{i+1}/{len(empresas)}] Analizando: {empresa['nombre']}")

        relevancia = analizar_relevancia(empresa, skills, model)
        empresa["relevancia"] = relevancia
        logger.info(f"  Relevancia: {relevancia}/10")

        if relevancia >= 4 and empresa.get("email"):
            logger.info(f"  Generando email personalizado...")
            email_data = generar_email_personalizado(empresa, personal, skills, model)
            empresa["asunto"]      = email_data["asunto"]
            empresa["cuerpo_email"] = email_data["cuerpo"]
            empresa["cv_path"]     = email_data.get("cv_path", personal.get("cv_path", ""))
            resultados.append(empresa)
        elif relevancia >= 4:
            logger.info(f"  Relevante pero sin email, se registra para revisión manual.")
            empresa["asunto"]      = ""
            empresa["cuerpo_email"] = ""
            resultados.append(empresa)
        else:
            logger.info(f"  Descartada (no relacionada con tecnología).")

    logger.info(f"Empresas válidas tras filtro IA: {len(resultados)}")
    return resultados
