# mitmproxy GitHub Copilot POC

<div align="center">

[![YouTube Channel Subscribers](https://img.shields.io/youtube/channel/subscribers/UC140iBrEZbOtvxWsJ-Tb0lQ?style=for-the-badge&logo=youtube&logoColor=white&color=red)](https://www.youtube.com/c/GiselaTorres?sub_confirmation=1)
[![GitHub followers](https://img.shields.io/github/followers/0GiS0?style=for-the-badge&logo=github&logoColor=white)](https://github.com/0GiS0)
[![LinkedIn Follow](https://img.shields.io/badge/LinkedIn-Sígueme-blue?style=for-the-badge&logo=linkedin&logoColor=white)](https://www.linkedin.com/in/giselatorresbuitrago/)
[![X Follow](https://img.shields.io/badge/X-Sígueme-black?style=for-the-badge&logo=x&logoColor=white)](https://twitter.com/0GiS0)

</div>

---

🌐 **Language:** English | [Español](README.es.md)

¡Hi developer 👋🏻! This is a proof of concept where I use **mitmproxy** and a Python addon that intercepts requests between VS Code / GitHub Copilot and its APIs (OpenAI/Anthropic compatible), blocking those whose prompt contains banned keywords (content policy), responding with a realistic `200 OK` instead of a network error.

## 📑 Table of Contents

- [Features](#-features)
- [Technologies](#-technologies-used)
- [Prerequisites](#-prerequisites)
- [Installation](#-installation)
- [Usage](#-usage)
- [Content filtering](#-content-filtering)
- [Challenges](#-challenges)
- [Project Structure](#-project-structure)
- [Contributing](#-contributing)
- [Follow me](#-follow-me-on-my-social-media)

## ✨ Features

- Transparently intercepts HTTPS traffic between VS Code / GitHub Copilot and its API endpoints.
- Blocks requests whose prompt contains any of the configurable banned keywords.
- Simulates realistic `200 OK` responses (Anthropic Messages, OpenAI Chat Completions, classic Completions, and their SSE streaming variants) instead of returning an HTTP error.
- Lets internal tool/function-calling requests through unblocked so it doesn't break the extension's protocol.
- Ships with automated tests (`pytest`).
- Optional integration to forward Copilot Chat's OpenTelemetry traces to an OTel Collector → Jaeger / Azure Application Insights (see [OTEL.md](OTEL.md)).

## 🛠️ Technologies Used

- Python 3.11+
- [mitmproxy](https://mitmproxy.org/) 10+ (addon API)
- pytest / pytest-asyncio (tests)
- OpenTelemetry Collector, Jaeger, Azure Application Insights (optional observability, see [OTEL.md](OTEL.md))
- Docker (to run the OTel Collector)

## 📋 Prerequisites

- Python 3.11 or higher
- mitmproxy 10+
- VS Code with the GitHub Copilot extension (to test the interception)
- (Optional) Docker, if you want to run the OTel Collector

## 🚀 Installation

### Step 1: Clone the repository

```bash
git clone https://github.com/0GiS0/mitmproxy-gh-copilot-poc.git
cd mitmproxy-gh-copilot-poc
```

### Step 2: Create the virtual environment and install dependencies

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 💻 Usage

```bash
# Interactive proxy (UI)
mitmproxy -s addon.py -p 8888

# Silent mode (headless)
mitmdump -s addon.py

# With a custom port (default: 8080)
mitmdump -p 8888 -s addon.py
```

Configure your client/IDE to use `http://localhost:8080` as the HTTP/HTTPS proxy.

### Setting up the mitmproxy certificate

To intercept HTTPS you need to install mitmproxy's root certificate:

```bash
# Start mitmdump once to generate the certificates
mitmdump &
# The certificate is at ~/.mitmproxy/mitmproxy-ca-cert.pem
```

You can open it with:

```bash
open ~/.mitmproxy/mitmproxy-ca-cert.pem
```

On macOS, open it with Keychain Access and install it in the **login** or **System** keychain, marking **"Always Trust"** for TLS. This is required because the GitHub Copilot extension validates the server certificate and will reject mitmproxy's responses if the CA isn't trusted.

### Configuring the proxy in VS Code

Two things are needed: VS Code (and its extensions) must route traffic through mitmproxy, and they must trust its certificate. GitHub Copilot doesn't always respect VS Code's `http.proxy` setting (it uses Node network libraries that read environment variables instead), so the reliable approach is to combine `settings.json` with environment variables.

#### 1. `settings.json`

```jsonc
{
  "http.proxy": "http://localhost:8080",
  "http.proxyStrictSSL": true, // true once you trust the mitmproxy certificate (see above)
  "http.proxySupport": "on",
  "http.systemCertificates": true,
}
```

#### 2. Environment variables (needed for Copilot to use the proxy)

Start VS Code from a terminal where these variables are already exported, so the Copilot extension (and its Node process) inherit them:

```bash
export HTTP_PROXY=http://localhost:8080
export HTTPS_PROXY=http://localhost:8080
export NODE_EXTRA_CA_CERTS=~/.mitmproxy/mitmproxy-ca-cert.pem

code .
```

- `HTTP_PROXY` / `HTTPS_PROXY`: redirect Copilot's requests to the proxy.
- `NODE_EXTRA_CA_CERTS`: makes VS Code's Node runtime trust the mitmproxy certificate without installing it system-wide.

#### 3. Verification

With `mitmdump -s addon.py` (or the `mitmproxy` UI) running, open Copilot Chat in VS Code and check the mitmproxy console/logs for intercepted requests (`Copilot request intercepted: ...`).

### Tests

```bash
pytest -v
```

## 🔒 Content filtering

### Blocked keywords

Defined in `BANNED_KEYWORDS` inside `addon.py`. Add or remove entries according to your policy.

### Response when blocking

Instead of returning an HTTP error (403), the addon **impersonates a valid Copilot API response (200 OK)**, so the block shows up as a normal chat message instead of a network error in VS Code. The simulated response format is chosen based on the actual endpoint/request:

- **Anthropic Messages API** (`/v1/messages`, Claude models): responds with a `message` (or its SSE streaming variant with `message_start` / `content_block_delta` / `message_stop` events if the request asks for `"stream": true`) where the "assistant" explains that the message was blocked and why.
- **OpenAI Chat Completions** (`messages` but not `/v1/messages`): same idea but with the `chat.completion` / `chat.completion.chunk` format.
- **Classic Completions** (inline code suggestions): responds with a `text_completion` with empty text, so simply no suggestion appears, without showing any error while typing.

**Internal tool/function-calling requests** (for example, the automatic prompt classification that the Copilot extension itself performs with auxiliary models like `gpt-4o-mini` and `tools`/`tool_choice`) **are let through unblocked**, even if they contain the keyword: replacing that response with plain text would break the `tool_calls` protocol expected by the extension and cause errors like "Sorry, no response was returned". The actual block is applied on the visible chat/messages request.

Example response for the Anthropic Messages API:

```json
{
  "id": "msg_blocked_...",
  "type": "message",
  "role": "assistant",
  "content": [
    {
      "type": "text",
      "text": "🚫 This request has been blocked by the content policy (keyword detected: **robar**). Rephrase your message without that content."
    }
  ],
  "stop_reason": "end_turn"
}
```

## ⚠️ Challenges

This keyword-based filtering approach is easy to understand and test, but it comes with real limitations worth keeping in mind:

- **Literal, not semantic, detection**: matching exact keywords is easily bypassed with synonyms, other languages, deliberate typos or paraphrasing. Robust filtering would require an extra AI model to analyze the context of each prompt, which adds **cost** (tokens/calls) and **latency** to every request.
- **That extra model is another point of failure and recurring cost**: it has to be maintained, paid for, and its own latency must not degrade the Copilot experience.
- **API payloads can change without notice**: `addon.py` depends on the specific shape of the OpenAI/Anthropic JSON (`messages`, `prompt`, content blocks, SSE streaming...). If GitHub Copilot or the providers change their format, the parsing logic (`extract_prompt_text`) may silently stop detecting the real prompt, making the filter ineffective.
- **False positives and false negatives**: a keyword can appear in a legitimate context (unnecessary block), or problematic content can be phrased without using any of the watched words (missed block).
- **Keyword list maintenance**: this is a manual, reactive process; every new way to evade the filter requires updating `BANNED_KEYWORDS`, which doesn't scale well.
- **TLS and certificate trust**: this approach requires intercepting HTTPS with a custom certificate installed on the system/IDE, which adds deployment friction and an extra attack surface if the certificate or the proxy is compromised.
- **Certificate pinning**: if the Copilot extension (or another client) starts pinning the server certificate instead of trusting the system CA, this kind of MITM interception would stop working entirely.
- **Content split across streaming chunks**: in SSE responses/requests the text can arrive split across several `content_block_delta` events; a keyword split between two chunks might go undetected if the full message isn't reassembled before analysis.
- **Text obfuscation**: lookalike unicode characters (homoglyphs), zero-width characters, leetspeak or encodings (base64, etc.) can bypass a literal text comparison fairly easily.
- **No conversation memory**: each request is analyzed in isolation, so problematic content built up gradually across several turns can go unnoticed even if each individual message looks innocuous.
- **Single point of failure and privacy**: all Copilot traffic depends on the proxy being up (if it crashes, Copilot stops working), and the addon has visibility into every prompt —including sensitive or proprietary code—, which requires handling those logs carefully.

## 📁 Project Structure

```
mitmproxy-gh-copilot-poc/
├── addon.py                    # mitmproxy addon: content policy filter
├── test_addon.py                # pytest test suite
├── requirements.txt              # Python dependencies
├── otel-collector-config.yml     # OTel Collector config (Jaeger / App Insights)
├── OTEL.md                       # OpenTelemetry tracing guide
├── README.md                     # This file (English)
└── README.es.md                  # Versión en español
```

## 🤝 Contributing

Contributions are welcome! Feel free to open an [issue](https://github.com/0GiS0/mitmproxy-gh-copilot-poc/issues) or submit a pull request with improvements, new banned-keyword strategies, or bug fixes.

1. Fork the repository
2. Create a branch (`git checkout -b feature/my-feature`)
3. Commit your changes (`git commit -m 'Add my feature'`)
4. Push the branch (`git push origin feature/my-feature`)
5. Open a Pull Request

## 🌐 Follow me on my Social Media

If you liked this project and want to see more content like this, don't forget to subscribe to my YouTube channel and follow me on my social media:

<div align="center">

[![YouTube Channel Subscribers](https://img.shields.io/youtube/channel/subscribers/UC140iBrEZbOtvxWsJ-Tb0lQ?style=for-the-badge&logo=youtube&logoColor=white&color=red)](https://www.youtube.com/c/GiselaTorres?sub_confirmation=1)
[![GitHub followers](https://img.shields.io/github/followers/0GiS0?style=for-the-badge&logo=github&logoColor=white)](https://github.com/0GiS0)
[![LinkedIn Follow](https://img.shields.io/badge/LinkedIn-Sígueme-blue?style=for-the-badge&logo=linkedin&logoColor=white)](https://www.linkedin.com/in/giselatorresbuitrago/)
[![X Follow](https://img.shields.io/badge/X-Sígueme-black?style=for-the-badge&logo=x&logoColor=white)](https://twitter.com/0GiS0)

</div>
