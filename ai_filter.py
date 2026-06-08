"""
ai_filter.py - Filtrado y personalización de emails con Ollama (Mistral)
Analiza empresas y genera emails personalizados para cada una
"""

import requests
import logging
import json
import re
from typing import List, Dict, Optional

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


def _parsear_json_ollama(respuesta: str) -> Optional[dict]:
    """
    Extrae {"asunto": ..., "cuerpo": ...} de la respuesta de Ollama de forma
    robusta. Maneja los tres problemas más comunes:
      1. Texto extra antes/después del JSON ("Aquí te presento...")
      2. Bloque de código Markdown  (```json ... ```)
      3. Saltos de línea LITERALES dentro de los valores del JSON
         (JSON inválido que genera json.loads más común de Ollama)
    Devuelve el dict o None si no se puede extraer nada útil.
    """
    if not respuesta:
        return None

    # 1. Quitar marcadores de bloque de código Markdown
    texto = re.sub(r"```(?:json)?\s*", "", respuesta, flags=re.IGNORECASE).strip()

    # 2. Encontrar el bloque JSON (primer { … último })
    inicio = texto.find("{")
    fin    = texto.rfind("}") + 1
    if inicio == -1 or fin <= inicio:
        return None
    fragmento = texto[inicio:fin]

    # 3. Primer intento: json.loads directo (funciona si el JSON es válido)
    try:
        return json.loads(fragmento)
    except Exception:
        pass

    # 4. Segundo intento: escapar los saltos de línea LITERALES dentro de strings.
    #    Recorremos carácter a carácter para saber si estamos dentro de un string
    #    y solo entonces reemplazamos \n/\r/\t por sus equivalentes escapados.
    try:
        en_string = False
        resultado = []
        i = 0
        while i < len(fragmento):
            c = fragmento[i]
            # Detectar inicio/fin de string (ignorando \" escapadas)
            if c == '"' and (i == 0 or fragmento[i - 1] != "\\"):
                en_string = not en_string
                resultado.append(c)
            elif en_string and c == "\n":
                resultado.append("\\n")
            elif en_string and c == "\r":
                resultado.append("\\r")
            elif en_string and c == "\t":
                resultado.append("\\t")
            else:
                resultado.append(c)
            i += 1
        return json.loads("".join(resultado))
    except Exception:
        pass

    return None


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
        prompt = f"""You are an expert business writer. Write a professional speculative job application email (max 180 words).

CANDIDATE:
- Name: {personal['nombre']}
- Level: {skills['nivel']} Developer
- Main stack: {', '.join(skills['principales'])}
- Also knows: {', '.join(skills['secundarias'])}{proyecto_str_en}
- Phone: {personal['telefono']}

COMPANY:
- Name: {empresa['nombre']}
- Info: {empresa['descripcion']}
- Location: {empresa.get('ciudad', '')}, {empresa.get('pais', '')}{bloque_tech_en}

RULES:
1. Open with a professional greeting to the hiring team.
2. Reference something specific about the company.
3. Introduce the candidate and their key skills naturally.
4. Mention Flitly (published on App Store and Google Play) as proof of real work — no URLs.
5. Say the CV is attached.
6. End with availability and phone number.
7. Tone: professional but human. NOT generic.
8. RESPOND ONLY WITH A JSON OBJECT. No explanation, no preamble, no code block.

Output format (ONLY this, nothing else before or after):
{{"asunto": "subject line here", "cuerpo": "full email body here"}}"""
    else:
        cv_path = personal.get('cv_path', '')
        prompt = f"""Eres un experto en redacción profesional. Escribe un email de candidatura espontánea (máx 180 palabras).

CANDIDATO:
- Nombre: {personal['nombre']}
- Nivel: Desarrollador {skills['nivel']}
- Stack principal: {', '.join(skills['principales'])}
- También domina: {', '.join(skills['secundarias'])}{proyecto_str_es}
- Teléfono: {personal['telefono']}

EMPRESA:
- Nombre: {empresa['nombre']}
- Info: {empresa['descripcion']}
- Ciudad: {empresa.get('ciudad', 'España')}{bloque_tech_es}

REGLAS:
1. Saludo profesional al equipo de RRHH.
2. Menciona algo concreto de la empresa.
3. Preséntate y destaca tus skills más relevantes de forma natural.
4. Menciona Flitly (publicada en App Store y Google Play) como prueba de trabajo real — sin URLs.
5. Indica que adjuntas el CV.
6. Cierra con disponibilidad y teléfono.
7. Tono: profesional pero cercano. NADA genérico.
8. RESPONDE ÚNICAMENTE CON EL OBJETO JSON. Sin explicación, sin preámbulo, sin bloque de código.

Formato de salida (SOLO esto, nada antes ni después):
{{"asunto": "línea de asunto aquí", "cuerpo": "cuerpo del email aquí"}}"""

    respuesta = _llamar_ollama(prompt, model, temperatura=0.7)

    # ── Parseo robusto de la respuesta ────────────────────────────────────────
    data = _parsear_json_ollama(respuesta)
    if data:
        asunto = (data.get("asunto") or "").strip()
        cuerpo = (data.get("cuerpo") or "").strip()
        if cuerpo:
            if not asunto:
                asunto = (f"Candidatura espontánea – Desarrollador {skills['nivel']} "
                          f"| {personal['nombre']}")
            return {"asunto": asunto, "cuerpo": cuerpo, "cv_path": cv_path}

    # ── Fallback: pedir de nuevo con temperatura 0 y formato más simple ───────
    logger.warning(f"JSON inválido para '{empresa['nombre']}', reintentando con T=0...")
    prompt_simple = prompt + "\n\nIMPORTANT: your previous response could not be parsed. Return ONLY the raw JSON object, starting with { and ending with }, with NO other characters outside it."
    respuesta2 = _llamar_ollama(prompt_simple, model, temperatura=0)
    data2 = _parsear_json_ollama(respuesta2)
    if data2:
        asunto = (data2.get("asunto") or "").strip()
        cuerpo = (data2.get("cuerpo") or "").strip()
        if cuerpo:
            if not asunto:
                asunto = (f"Candidatura espontánea – Desarrollador {skills['nivel']} "
                          f"| {personal['nombre']}")
            return {"asunto": asunto, "cuerpo": cuerpo, "cv_path": cv_path}

    # ── Último recurso: email limpio genérico (NUNCA enviar JSON crudo) ───────
    logger.warning(f"Usando email genérico para '{empresa['nombre']}' (Ollama no devolvió JSON válido)")
    nombre_emp = empresa.get("nombre", "")
    if idioma == "en":
        asunto_gen = f"Speculative Application – {skills['nivel']} Developer | {personal['nombre']}"
        cuerpo_gen = (
            f"Dear Hiring Team,\n\n"
            f"I am writing to express my interest in joining {nombre_emp}. "
            f"My name is {personal['nombre']}, a {skills['nivel']} developer "
            f"specialised in {', '.join(skills['principales'])}.\n\n"
            f"I have developed Flitly, a real app published on the App Store and Google Play, "
            f"which demonstrates my ability to deliver production-ready work.\n\n"
            f"Please find my CV attached. I would welcome the opportunity to discuss "
            f"how I can contribute to your team.\n\n"
            f"Best regards,\n{personal['nombre']}\n{personal['telefono']}"
        )
    else:
        asunto_gen = (f"Candidatura espontánea – Desarrollador {skills['nivel']} "
                      f"| {personal['nombre']}")
        cuerpo_gen = (
            f"Estimado equipo de RRHH,\n\n"
            f"Me pongo en contacto para presentar mi candidatura en {nombre_emp}. "
            f"Soy {personal['nombre']}, desarrollador {skills['nivel']} "
            f"especializado en {', '.join(skills['principales'])}.\n\n"
            f"Entre mis proyectos destaca Flitly, una app publicada en App Store y "
            f"Google Play, que demuestra mi capacidad para llevar proyectos reales a producción.\n\n"
            f"Adjunto mi CV. Quedo disponible para cualquier entrevista.\n\n"
            f"Un saludo,\n{personal['nombre']}\n{personal['telefono']}"
        )
    return {"asunto": asunto_gen, "cuerpo": cuerpo_gen, "cv_path": cv_path}


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
