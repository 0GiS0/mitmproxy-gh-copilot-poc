# mitmproxy GitHub Copilot POC

<div align="center">

[![YouTube Channel Subscribers](https://img.shields.io/youtube/channel/subscribers/UC140iBrEZbOtvxWsJ-Tb0lQ?style=for-the-badge&logo=youtube&logoColor=white&color=red)](https://www.youtube.com/c/GiselaTorres?sub_confirmation=1)
[![GitHub followers](https://img.shields.io/github/followers/0GiS0?style=for-the-badge&logo=github&logoColor=white)](https://github.com/0GiS0)
[![LinkedIn Follow](https://img.shields.io/badge/LinkedIn-Sígueme-blue?style=for-the-badge&logo=linkedin&logoColor=white)](https://www.linkedin.com/in/giselatorresbuitrago/)
[![X Follow](https://img.shields.io/badge/X-Sígueme-black?style=for-the-badge&logo=x&logoColor=white)](https://twitter.com/0GiS0)

</div>

---

🌐 **Idioma:** Español | [English](README.md)

¡Hola developer 👋🏻! Esta es una prueba de concepto donde utilizo **mitmproxy** y un addon en Python que intercepta las peticiones entre VS Code / GitHub Copilot y sus APIs (compatibles con OpenAI/Anthropic), y bloquea aquellas cuyo prompt contenga palabras clave prohibidas (política de contenido), respondiendo con un `200 OK` realista en lugar de un error de red.

---

## 📑 Tabla de Contenidos

- [Características](#-características)
- [Tecnologías](#-tecnologías-utilizadas)
- [Requisitos Previos](#-requisitos-previos)
- [Instalación](#-instalación)
- [Uso](#-uso)
- [Filtrado de contenido](#-filtrado-de-contenido)
- [Retos](#-retos)
- [Estructura del Proyecto](#-estructura-del-proyecto)
- [Contribuir](#-contribuir)
- [Sígueme](#-sígueme-en-mis-redes-sociales)

## ✨ Características

- Intercepta de forma transparente el tráfico HTTPS entre VS Code / GitHub Copilot y sus endpoints de API.
- Bloquea las peticiones cuyo prompt contenga alguna de las palabras clave prohibidas configurables.
- Simula respuestas `200 OK` realistas (Anthropic Messages, OpenAI Chat Completions, Completions clásico y sus variantes en streaming SSE) en lugar de devolver un error HTTP.
- Deja pasar sin bloquear las peticiones internas de tool/function calling para no romper el protocolo de la extensión.
- Incluye tests automatizados (`pytest`).
- Integración opcional para reenviar las trazas de OpenTelemetry de Copilot Chat a un OTel Collector → Jaeger / Azure Application Insights (ver [OTEL.md](OTEL.md)).

## 🛠️ Tecnologías Utilizadas

- Python 3.11+
- [mitmproxy](https://mitmproxy.org/) 10+ (addon API)
- pytest / pytest-asyncio (tests)
- OpenTelemetry Collector, Jaeger, Azure Application Insights (observabilidad opcional, ver [OTEL.md](OTEL.md))
- Docker (para ejecutar el OTel Collector)

## 📋 Requisitos Previos

- Python 3.11 o superior
- mitmproxy 10+
- VS Code con la extensión de GitHub Copilot (para probar la interceptación)
- (Opcional) Docker, si quieres levantar el OTel Collector

## 🚀 Instalación

### Paso 1: Clonar el repositorio

```bash
git clone https://github.com/0GiS0/mitmproxy-gh-copilot-poc.git
cd mitmproxy-gh-copilot-poc
```

### Paso 2: Crear el entorno virtual e instalar dependencias

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 💻 Uso

```bash
# Proxy interactivo (UI)
mitmproxy -s addon.py -p 8888

# Modo silencioso (headless)
mitmdump -s addon.py

# Con puerto personalizado (default: 8080)
mitmdump -p 8888 -s addon.py
```

Configura tu cliente/IDE para usar `http://localhost:8080` como proxy HTTP/HTTPS.

### Configurar el certificado de mitmproxy

Para interceptar HTTPS necesitas instalar el certificado raíz de mitmproxy:

```bash
# Arranca mitmdump una vez para generar los certificados
mitmdump &
# El certificado está en ~/.mitmproxy/mitmproxy-ca-cert.pem
```

Puedes abrirlo con :

```bash
open ~/.mitmproxy/mitmproxy-ca-cert.pem
```

En macOS, ábrelo con Keychain Access e instálalo en el llavero **login** o **System**, y marca **"Always Trust"** para TLS. Esto es necesario porque la extensión de GitHub Copilot valida el certificado del servidor y rechazará las respuestas de mitmproxy si la CA no es de confianza.

### Configurar el proxy en VS Code

Hacen falta dos cosas: que VS Code (y sus extensiones) enruten el tráfico por mitmproxy, y que confíen en su certificado. GitHub Copilot no siempre respeta el ajuste `http.proxy` de VS Code (usa librerías de red de Node que leen variables de entorno), así que la forma fiable es combinar `settings.json` con variables de entorno.

#### 1. `settings.json`

```jsonc
{
  "http.proxy": "http://localhost:8080",
  "http.proxyStrictSSL": true, // true si ya confías en el certificado de mitmproxy (ver arriba)
  "http.proxySupport": "on",
  "http.systemCertificates": true,
}
```

#### 2. Variables de entorno (necesario para que Copilot use el proxy)

Arranca VS Code desde una terminal donde estas variables ya estén exportadas, para que la extensión de Copilot (y su proceso de Node) las herede:

```bash
export HTTP_PROXY=http://localhost:8080
export HTTPS_PROXY=http://localhost:8080
export NODE_EXTRA_CA_CERTS=~/.mitmproxy/mitmproxy-ca-cert.pem

code .
```

- `HTTP_PROXY` / `HTTPS_PROXY`: redirigen las peticiones de Copilot al proxy.
- `NODE_EXTRA_CA_CERTS`: hace que el runtime Node de VS Code confíe en el certificado de mitmproxy sin tener que instalarlo a nivel de sistema.

#### 3. Verificación

Con `mitmdump -s addon.py` (o la UI de `mitmproxy`) en marcha, abre Copilot Chat en VS Code y comprueba en la consola/logs de mitmproxy que aparecen las peticiones interceptadas (`Copilot request intercepted: ...`).

### Tests

```bash
pytest -v
```

## 🔒 Filtrado de contenido

### Keywords bloqueadas

Definidas en `BANNED_KEYWORDS` dentro de `addon.py`. Añade o elimina según tu política.

### Respuesta al bloquear

En vez de devolver un error HTTP (403), el addon **suplanta una respuesta válida de la API de Copilot (200 OK)**, para que el bloqueo se muestre como un mensaje normal en el chat en lugar de un error de red en VS Code. El formato de la respuesta simulada se elige según el endpoint/petición real:

- **Anthropic Messages API** (`/v1/messages`, modelos Claude): responde con un `message` (o su variante en streaming SSE con eventos `message_start` / `content_block_delta` / `message_stop` si la petición pide `"stream": true`) donde el "asistente" explica que el mensaje fue bloqueado y por qué.
- **OpenAI Chat Completions** (`messages` sin ser `/v1/messages`): igual pero con el formato `chat.completion` / `chat.completion.chunk`.
- **Completions clásico** (sugerencias inline de código): responde con un `text_completion` con texto vacío, para que simplemente no aparezca sugerencia, sin mostrar ningún error mientras escribes.

**Peticiones internas de tool/function calling** (por ejemplo, la clasificación automática del prompt que la propia extensión de Copilot hace con modelos auxiliares como `gpt-4o-mini` y `tools`/`tool_choice`) **se dejan pasar sin bloquear**, aunque contengan la keyword: sustituir esa respuesta por texto plano rompería el protocolo de `tool_calls` que espera la extensión y provocaría errores tipo "Sorry, no response was returned". El bloqueo real se aplica en la petición de chat/mensajes visible al usuario.

Ejemplo de respuesta para Anthropic Messages API:

```json
{
  "id": "msg_blocked_...",
  "type": "message",
  "role": "assistant",
  "content": [
    {
      "type": "text",
      "text": "🚫 Esta petición ha sido bloqueada por la política de contenido (palabra clave detectada: **robar**). Reformula tu mensaje sin ese contenido."
    }
  ],
  "stop_reason": "end_turn"
}
```

## ⚠️ Retos

Este enfoque de filtrado por palabras clave es sencillo de entender y de testear, pero tiene limitaciones reales que conviene tener presentes:

- **Detección literal, no semántica**: buscar keywords exactas se salta fácilmente con sinónimos, otros idiomas, erratas deliberadas o parafraseo. Para un filtrado robusto haría falta un modelo de IA adicional que analice el contexto de cada prompt, lo cual añade **coste** (tokens/llamadas) y **latencia** a cada petición.
- **Ese modelo extra es otro punto de fallo y de coste recurrente**: hay que mantenerlo, pagarlo y asegurarse de que su propia latencia no degrada la experiencia de Copilot.
- **El payload de las APIs puede cambiar sin previo aviso**: `addon.py` depende de la forma concreta del JSON de OpenAI/Anthropic (`messages`, `prompt`, bloques de contenido, streaming SSE...). Si GitHub Copilot o los proveedores cambian su formato, el parseo (`extract_prompt_text`) puede dejar de detectar el prompt real y el filtro se vuelve inefectivo silenciosamente.
- **Falsos positivos y falsos negativos**: una keyword puede aparecer en un contexto legítimo (bloqueo innecesario) o el contenido problemático puede expresarse sin usar ninguna de las palabras vigiladas (bloqueo fallido).
- **Mantenimiento de la lista de keywords**: es un proceso manual y reactivo; cada nueva forma de eludir el filtro requiere actualizar `BANNED_KEYWORDS`, lo que no escala bien.
- **TLS y confianza del certificado**: este enfoque exige interceptar HTTPS con un certificado propio instalado en el sistema/IDE, lo que introduce fricción de despliegue y una superficie de ataque adicional si el certificado o el proxy se ven comprometidos.
- **Certificate pinning**: si en el futuro la extensión de Copilot (u otro cliente) empieza a fijar ("pinnear") el certificado del servidor en lugar de confiar en la CA del sistema, este tipo de interceptación MITM dejaría de funcionar por completo.
- **Contenido troceado en streaming**: en respuestas/peticiones por SSE el texto puede llegar repartido en varios `content_block_delta`; una keyword partida entre dos chunks podría no detectarse si no se reensambla el mensaje completo antes de analizarlo.
- **Ofuscación del texto**: caracteres unicode similares (homoglifos), caracteres de ancho cero, leetspeak o codificaciones (base64, etc.) pueden saltarse una comparación literal de texto sin mucho esfuerzo.
- **Sin memoria de la conversación**: cada petición se analiza de forma aislada, por lo que un contenido problemático construido poco a poco a lo largo de varios turnos puede pasar desapercibido aunque cada mensaje individual parezca inocuo.
- **Punto único de fallo y privacidad**: todo el tráfico de Copilot depende de que el proxy esté levantado (si se cae, Copilot deja de funcionar), y el addon tiene visibilidad de todos los prompts —incluyendo código o datos sensibles—, lo que exige tratar esos logs con cuidado.

## 📁 Estructura del Proyecto

```
mitmproxy-gh-copilot-poc/
├── addon.py                    # Addon de mitmproxy: filtro de política de contenido
├── test_addon.py                # Suite de tests con pytest
├── requirements.txt              # Dependencias de Python
├── otel-collector-config.yml     # Config del OTel Collector (Jaeger / App Insights)
├── OTEL.md                       # Guía de trazas con OpenTelemetry
├── README.md                     # Versión en inglés
└── README.es.md                  # Este fichero (español)
```

## 🤝 Contribuir

¡Las contribuciones son bienvenidas! Abre un [issue](https://github.com/0GiS0/mitmproxy-gh-copilot-poc/issues) o envía un pull request con mejoras, nuevas estrategias de palabras clave o correcciones.

1. Haz un fork del repositorio
2. Crea una rama (`git checkout -b feature/mi-mejora`)
3. Haz commit de tus cambios (`git commit -m 'Añade mi mejora'`)
4. Sube la rama (`git push origin feature/mi-mejora`)
5. Abre un Pull Request

## 🌐 Sígueme en Mis Redes Sociales

Si te ha gustado este proyecto y quieres ver más contenido como este, no olvides suscribirte a mi canal de YouTube y seguirme en mis redes sociales:

<div align="center">

[![YouTube Channel Subscribers](https://img.shields.io/youtube/channel/subscribers/UC140iBrEZbOtvxWsJ-Tb0lQ?style=for-the-badge&logo=youtube&logoColor=white&color=red)](https://www.youtube.com/c/GiselaTorres?sub_confirmation=1)
[![GitHub followers](https://img.shields.io/github/followers/0GiS0?style=for-the-badge&logo=github&logoColor=white)](https://github.com/0GiS0)
[![LinkedIn Follow](https://img.shields.io/badge/LinkedIn-Sígueme-blue?style=for-the-badge&logo=linkedin&logoColor=white)](https://www.linkedin.com/in/giselatorresbuitrago/)
[![X Follow](https://img.shields.io/badge/X-Sígueme-black?style=for-the-badge&logo=x&logoColor=white)](https://twitter.com/0GiS0)

</div>
