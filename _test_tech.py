"""Test de detección de tecnologías + matching con skills del candidato."""
import sys, os
sys.path.insert(0, os.path.expanduser("~/Library/Python/3.9/lib/python/site-packages"))
import logging
logging.basicConfig(level=logging.ERROR)

import scraper
from ai_filter import _tech_coincidentes

skills = {
    "principales": ["Flutter", "Dart", "Astro"],
    "secundarias": ["React", "JavaScript", "TypeScript", "Python",
                    "HTML/CSS", "Firebase", "Supabase"],
}

print("=" * 60)
print("TEST 1: detección de tecnologías en webs reales")
print("=" * 60)
webs = [
    "https://react.dev",          # React (Next.js docs)
    "https://astro.build",        # Astro
    "https://vuejs.org",          # Vue
    "https://firebase.google.com",  # Firebase
    "https://wordpress.org",      # WordPress
]
for w in webs:
    try:
        techs = scraper.detectar_tecnologias(w, timeout=8)
        match = _tech_coincidentes(techs, skills)
        print(f"\n  {w}")
        print(f"    detectadas: {techs}")
        print(f"    coinciden con candidato: {match or '—'}")
    except Exception as e:
        print(f"  {w} -> ERROR {e}")

print("\n" + "=" * 60)
print("TEST 2: lógica de matching (sin red)")
print("=" * 60)
casos = [
    ("React, Firebase, Tailwind CSS", ["React", "Firebase"]),
    ("Next.js, JavaScript", ["React", "JavaScript"]),  # Next.js implica React
    ("WordPress, PHP", []),                              # nada que comparta
    ("Astro, Supabase", ["Astro", "Supabase"]),
    ("Flutter", ["Flutter", "Dart"]),                   # Flutter implica Dart
    ("", []),
]
ok = 0
for entrada, esperado in casos:
    res = _tech_coincidentes(entrada, skills)
    bien = sorted(res) == sorted(esperado)
    ok += bien
    print(f"  {'✅' if bien else '❌'} '{entrada}' -> {res}  (esperado {esperado})")
print(f"\n  {ok}/{len(casos)} casos correctos")

print("\n" + "=" * 60)
print("TEST 3: el bloque de tecnologías llega al prompt")
print("=" * 60)
import ai_filter
empresa = {"nombre": "TechCorp", "descripcion": "Software house",
           "idioma": "es", "ciudad": "Sevilla", "pais": "España",
           "fuente": "Google", "tecnologias": "React, Firebase, Tailwind CSS"}
# Interceptar el prompt sin llamar a Ollama
capturado = {}
def fake_ollama(prompt, model, temperatura=0.7):
    capturado["prompt"] = prompt
    return '{"asunto": "x", "cuerpo": "y"}'
ai_filter._llamar_ollama = fake_ollama
ai_filter.generar_email_personalizado(
    empresa, {"nombre": "Diego", "telefono": "123", "cv_path": "x.pdf"},
    {**skills, "nivel": "Junior"}, "mistral")
p = capturado.get("prompt", "")
tiene = "React, Firebase" in p and "TAMBIÉN DOMINA" in p
print(f"  {'✅' if tiene else '❌'} El prompt incluye las tecnologías coincidentes")
if tiene:
    idx = p.find("TECNOLOGÍAS DETECTADAS")
    print("  Fragmento del prompt:")
    print("   ", p[idx:idx+180].replace("\n", " "))
