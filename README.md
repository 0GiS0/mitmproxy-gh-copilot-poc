# mitmproxy GitHub Copilot POC

Addon para **mitmproxy** que intercepta peticiones a GitHub Copilot y bloquea aquellas cuyo prompt contenga palabras clave prohibidas (política de contenido).

## Requisitos

- Python 3.11+
- mitmproxy 10+

## Instalación

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Uso

```bash
# Proxy interactivo (UI)
mitmproxy -s addon.py -p 8888

# Modo silencioso (headless)
mitmdump -s addon.py

# Con puerto personalizado (default: 8080)
mitmdump -p 8888 -s addon.py
```

Configura tu cliente/IDE para usar `http://localhost:8080` como proxy HTTP/HTTPS.

## Configurar el certificado de mitmproxy

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

## Configurar el proxy en VS Code

Hacen falta dos cosas: que VS Code (y sus extensiones) enruten el tráfico por mitmproxy, y que confíen en su certificado. GitHub Copilot no siempre respeta el ajuste `http.proxy` de VS Code (usa librerías de red de Node que leen variables de entorno), así que la forma fiable es combinar `settings.json` con variables de entorno.

### 1. `settings.json`

```jsonc
{
  "http.proxy": "http://localhost:8080",
  "http.proxyStrictSSL": true, // true si ya confías en el certificado de mitmproxy (ver arriba)
  "http.proxySupport": "on",
  "http.systemCertificates": true,
}
```

### 2. Variables de entorno (necesario para que Copilot use el proxy)

Arranca VS Code desde una terminal donde estas variables ya estén exportadas, para que la extensión de Copilot (y su proceso de Node) las herede:

```bash
export HTTP_PROXY=http://localhost:8080
export HTTPS_PROXY=http://localhost:8080
export NODE_EXTRA_CA_CERTS=~/.mitmproxy/mitmproxy-ca-cert.pem

code .
```

- `HTTP_PROXY` / `HTTPS_PROXY`: redirigen las peticiones de Copilot al proxy.
- `NODE_EXTRA_CA_CERTS`: hace que el runtime Node de VS Code confíe en el certificado de mitmproxy sin tener que instalarlo a nivel de sistema.

### 3. Verificación

Con `mitmdump -s addon.py` (o la UI de `mitmproxy`) en marcha, abre Copilot Chat en VS Code y comprueba en la consola/logs de mitmproxy que aparecen las peticiones interceptadas (`Copilot request intercepted: ...`).

## Tests

```bash
pytest -v
```

## Keywords bloqueadas

Definidas en `BANNED_KEYWORDS` dentro de `addon.py`. Añade o elimina según tu política.

## Respuesta al bloquear

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
