# 📧 Automatización de Envío de Curriculum

Busca empresas tech en múltiples portales y fuentes, usa **llama3.1:8b via Ollama** para filtrar
y personalizar cada email, y los envía automáticamente con tu CV adjunto.

---

## 📁 Estructura del proyecto

```
Automatizacion-Correos/
├── main.py              # Orquestador principal, punto de entrada
├── scraper.py           # Búsqueda de empresas (LinkedIn, Indeed, Tecnoempleo, InfoJobs, Google, GitHub)
├── ai_filter.py         # Filtrado y personalización de emails con Ollama
├── email_sender.py      # Envío de emails vía Gmail (yagmail)
├── database.py          # Base de datos SQLite
├── config.yaml          # ⚙️  Configuración principal (edita esto primero)
├── curriculum/
│   ├── CV_Diego_Garcia.pdf       # CV en español (empresas ES)
│   └── CV_Diego_Garcia_EN.pdf    # CV en inglés (Irlanda, UK, Alemania)
├── data/                # Base de datos SQLite (se genera automáticamente)
└── logs/                # Log de cada ejecución (se genera automáticamente)
```

---

## 🚀 Requisitos previos

### 1. Python 3.9+
El proyecto usa el Python del sistema. Comprueba que funciona:
```bash
python3 --version
```

### 2. Dependencias Python
```bash
pip3 install --user PyYAML requests beautifulsoup4 lxml yagmail
```

### 3. Ollama con llama3.1:8b
Ollama debe estar instalado y corriendo con el modelo descargado:
```bash
# Instalar Ollama desde https://ollama.com si no lo tienes
ollama pull llama3.1:8b
ollama serve          # déjalo corriendo en una terminal aparte
```

Comprueba que responde:
```bash
curl http://localhost:11434/api/tags
```

---

## ⚙️ Configuración (`config.yaml`)

Abre `config.yaml` y revisa/ajusta estos campos:

### Datos personales
```yaml
personal:
  nombre: "Tu Nombre"
  email_remitente: "tu@gmail.com"
  email_password: "xxxx xxxx xxxx xxxx"   # Contraseña de aplicación Gmail (ver abajo)
  telefono: "+34 600 000 000"
  cv_es: "curriculum/CV_Es.pdf"
  cv_en: "curriculum/CV_En.pdf"
  cv_path: "curriculum/CV_Es.pdf"         # CV por defecto
```

> **Contraseña de aplicación Gmail**: ve a myaccount.google.com → Seguridad →
> Verificación en 2 pasos → Contraseñas de aplicaciones → genera una para "Correo".

### Token de GitHub (muy recomendado)
Sin token solo se pueden hacer 60 peticiones/hora a la API de GitHub.
Con token gratuito: 5000 peticiones/hora.

1. Ve a **github.com/settings/tokens**
2. "Generate new token (classic)"
3. Dale un nombre, **no marques ningún permiso** (solo acceso público)
4. Copia el token generado (`ghp_xxxx...`)
5. Pégalo en `config.yaml`:

```yaml
github:
  token: "ghp_xxxxxxxxxxxxxxxxxxxx"
```

### Ajustes de búsqueda
```yaml
filtros:
  max_paginas: 5    # Páginas por término/fuente. Más = más resultados pero más lento.
                    # Recomendado para primera prueba: 2
```

---

## ▶️ Cómo ejecutar

Todos los comandos se lanzan desde la carpeta del proyecto:
```bash
cd /ruta/a/Automatizacion-Correos
```

### 🔌 Paso 1 — Probar conexión de email
Antes de nada, comprueba que el email funciona:
```bash
python3 main.py --test-smtp
```
Deberías ver: `✅ Conexion Gmail OK`

### 🔍 Paso 2 — Solo buscar empresas (sin enviar emails)
Ideal para la primera ejecución. Busca, filtra con IA y guarda en la BD pero **no envía nada**:
```bash
python3 main.py --solo-buscar
```
Al terminar verás cuántas empresas se encontraron y guardaron.

### 📊 Paso 3 — Ver estadísticas
Consulta el estado actual de la base de datos:
```bash
python3 main.py --estadisticas
```

### � Paso 4 — Solo enviar emails
Usa las empresas ya guardadas en BD y envía los emails:
```bash
python3 main.py --solo-enviar
```

### ⚡ Pipeline completo (buscar + filtrar + enviar todo de una vez)
```bash
python3 main.py
```

---

## 🔄 Flujo completo del programa

```
python3 main.py
        │
        ├─ scraper.py ──────────── Busca en LinkedIn, Indeed, Tecnoempleo,
        │                          InfoJobs, Google y GitHub API
        │                          → Lista de empresas con nombre, web, email...
        │
        ├─ ai_filter.py ─────────── Para cada empresa:
        │                            1. Puntúa relevancia 0-10 (Ollama)
        │                            2. Si ≥ 4: genera email personalizado (Ollama)
        │                            3. Selecciona CV español o inglés según país
        │
        ├─ database.py ─────────── Guarda empresas nuevas en SQLite
        │                          (evita duplicados por email)
        │
        └─ email_sender.py ─────── Envía email + CV adjunto por Gmail
                                   Respeta el límite diario y pausa entre envíos
                                   Registra cada envío en la BD
```

---

## 🔄 Automatización diaria (opcional)

Para ejecutarlo cada día automáticamente en segundo plano:

```bash
# Abrir crontab
crontab -e

# Añadir esta línea (ejecuta cada día laborable a las 9:00)
0 9 * * 1-5 cd /Users/diegogarciajimenez/Documents/Automatizacion-Correos && /usr/bin/python3 main.py
```

---

## ⚠️ Notas importantes

- **Límite diario de emails**: 20/día por defecto (configurable en `email.max_emails_por_dia`). Gmail puede bloquear si envías demasiados seguidos.
- **Pausa entre emails**: 30 segundos por defecto (`email.espera_entre_emails`). No lo bajes de 15s.
- **La primera ejecución tarda**: buscar + analizar con IA puede llevar 30-60 minutos dependiendo de `max_paginas` y las ciudades configuradas.
- **Ollama debe estar corriendo**: asegúrate de tener `ollama serve` activo antes de ejecutar.
- **Logs**: cada ejecución genera un `.log` en `logs/` con todo el detalle de lo que ocurrió.
- **No se envía dos veces al mismo email**: la BD lleva registro completo de todos los envíos.
