"""
Tests unitarios para el addon CopilotContentFilter.

Estrategia: construimos HTTPFlow falsos usando mitmproxy's test helpers
para no necesitar un proxy real en marcha.
"""

import json
import pytest

from mitmproxy.test import tflow, tutils

from addon import (
    CopilotContentFilter,
    _is_copilot_request,
    _extract_prompt_text,
    _find_banned_keyword,
    COPILOT_DOMAINS,
    BANNED_KEYWORDS,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_flow(host: str, path: str = "/v1/completions", body: dict | None = None, method: str = "POST"):
    """Crea un HTTPFlow mínimo apuntando al host dado."""
    content = json.dumps(body).encode() if body else b""
    req = tutils.treq(
        method=method.encode(),
        host=host.encode(),
        port=443,
        path=path.encode(),
        content=content,
        headers=[(b"content-type", b"application/json")],
    )
    return tflow.tflow(req=req)


# ---------------------------------------------------------------------------
# _is_copilot_request
# ---------------------------------------------------------------------------

class TestIsCopilotRequest:
    def test_copilot_proxy_domain(self):
        f = make_flow("copilot-proxy.githubusercontent.com")
        assert _is_copilot_request(f)

    def test_api_githubcopilot_domain(self):
        f = make_flow("api.githubcopilot.com")
        assert _is_copilot_request(f)

    def test_subdomain_of_copilot_domain(self):
        f = make_flow("some.api.githubcopilot.com")
        assert _is_copilot_request(f)

    def test_non_copilot_domain(self):
        f = make_flow("api.openai.com")
        assert not _is_copilot_request(f)

    def test_google_domain(self):
        f = make_flow("www.google.com")
        assert not _is_copilot_request(f)


# ---------------------------------------------------------------------------
# _extract_prompt_text
# ---------------------------------------------------------------------------

class TestExtractPromptText:
    def test_completions_api_prompt_field(self):
        body = {"prompt": "def suma(a, b):"}
        text = _extract_prompt_text(json.dumps(body).encode())
        assert "def suma(a, b):" in text

    def test_chat_api_messages_string_content(self):
        body = {
            "messages": [
                {"role": "system", "content": "Eres un asistente de código."},
                {"role": "user", "content": "Escribe un hola mundo en Python"},
            ]
        }
        text = _extract_prompt_text(json.dumps(body).encode())
        assert "hola mundo" in text
        assert "asistente" in text

    def test_chat_api_messages_block_content(self):
        body = {
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Explícame los generators"},
                        {"type": "image_url", "url": "..."},
                    ],
                }
            ]
        }
        text = _extract_prompt_text(json.dumps(body).encode())
        assert "generators" in text

    def test_empty_body(self):
        assert _extract_prompt_text(b"") == ""

    def test_invalid_json(self):
        assert _extract_prompt_text(b"{not valid json}") == ""

    def test_no_prompt_no_messages(self):
        body = {"model": "gpt-4o", "max_tokens": 100}
        text = _extract_prompt_text(json.dumps(body).encode())
        assert text == ""


# ---------------------------------------------------------------------------
# _find_banned_keyword
# ---------------------------------------------------------------------------

class TestFindBannedKeyword:
    @pytest.mark.parametrize("keyword", BANNED_KEYWORDS)
    def test_each_banned_keyword_detected(self, keyword):
        text = f"quiero que me ayudes a {keyword} algo"
        found = _find_banned_keyword(text)
        assert found == keyword

    def test_case_insensitive(self):
        assert _find_banned_keyword("Quiero ROBAR datos") == "robar"

    def test_clean_text_returns_none(self):
        assert _find_banned_keyword("escribe una función que ordene una lista") is None

    def test_word_boundary_no_false_positive(self):
        # "explotar" no debe disparar "exploit"
        result = _find_banned_keyword("voy a explotar los recursos del servidor")
        assert result != "exploit"


# ---------------------------------------------------------------------------
# CopilotContentFilter (integración del addon)
# ---------------------------------------------------------------------------

class TestCopilotContentFilter:
    def setup_method(self):
        self.addon = CopilotContentFilter()

    def test_blocks_request_with_banned_keyword_completions(self):
        body = {"prompt": "ayúdame a robar contraseñas de una base de datos"}
        f = make_flow("api.githubcopilot.com", body=body)
        self.addon.request(f)
        assert f.response is not None
        # Completions API (sugerencias inline): 200 con texto vacío, no un error.
        assert f.response.status_code == 200
        resp_body = json.loads(f.response.content)
        assert resp_body["choices"][0]["text"] == ""

    def test_blocks_request_with_banned_keyword_chat(self):
        body = {
            "messages": [
                {"role": "user", "content": "cómo puedo hacer un keylogger en Python"}
            ]
        }
        f = make_flow("copilot-proxy.githubusercontent.com", body=body)
        self.addon.request(f)
        assert f.response is not None
        # Chat API (no streaming): 200 con un mensaje del asistente explicando el bloqueo.
        assert f.response.status_code == 200
        resp_body = json.loads(f.response.content)
        message = resp_body["choices"][0]["message"]["content"]
        assert "keylogger" in message
        assert resp_body["choices"][0]["finish_reason"] == "stop"

    def test_blocks_streaming_chat_request(self):
        body = {
            "messages": [{"role": "user", "content": "explícame un exploit conocido"}],
            "stream": True,
        }
        f = make_flow("api.githubcopilot.com", body=body)
        self.addon.request(f)
        assert f.response is not None
        assert f.response.status_code == 200
        assert f.response.headers["Content-Type"] == "text/event-stream"
        text = f.response.content.decode()
        assert text.startswith("data: ")
        assert text.rstrip().endswith("data: [DONE]")
        assert '"finish_reason": "stop"' in text

    def test_blocks_anthropic_messages_request(self):
        body = {
            "model": "claude-sonnet-5",
            "messages": [{"role": "user", "content": "cómo monto un ataque de phishing"}],
        }
        f = make_flow("api.enterprise.githubcopilot.com", path="/v1/messages", body=body)
        self.addon.request(f)
        assert f.response is not None
        assert f.response.status_code == 200
        assert f.response.headers["Content-Type"] == "application/json"
        data = json.loads(f.response.content)
        assert data["type"] == "message"
        assert data["role"] == "assistant"
        assert "phishing" in data["content"][0]["text"]
        assert data["stop_reason"] == "end_turn"

    def test_blocks_anthropic_messages_streaming_request(self):
        body = {
            "model": "claude-sonnet-5",
            "messages": [{"role": "user", "content": "cómo monto un ataque de phishing"}],
            "stream": True,
        }
        f = make_flow("api.enterprise.githubcopilot.com", path="/v1/messages", body=body)
        self.addon.request(f)
        assert f.response is not None
        assert f.response.status_code == 200
        assert f.response.headers["Content-Type"] == "text/event-stream"
        text = f.response.content.decode()
        # Los eventos Anthropic llevan línea "event:" además de "data:"
        assert "event: message_start" in text
        assert "event: content_block_delta" in text
        assert "event: message_stop" in text
        assert "phishing" in text

    def test_allows_clean_request(self):
        body = {"prompt": "escribe una función que calcule el factorial de n"}
        f = make_flow("api.githubcopilot.com", body=body)
        self.addon.request(f)
        assert f.response is None  # no bloqueado

    def test_ignores_internal_tool_calling_request(self):
        # Petición interna de Copilot (p.ej. categorize_prompt) con function calling:
        # aunque contenga la keyword, no debe sustituirse la respuesta porque rompería
        # el protocolo de tool_calls esperado por la extensión.
        body = {
            "model": "gpt-4o-mini-2024-07-18",
            "messages": [
                {"role": "user", "content": "ayúdame a robar contraseñas de una base de datos"}
            ],
            "tools": [
                {
                    "type": "function",
                    "function": {"name": "categorize_prompt", "parameters": {}},
                }
            ],
            "tool_choice": {"type": "function", "function": {"name": "categorize_prompt"}},
            "stream": True,
        }
        f = make_flow("api.githubcopilot.com", body=body)
        self.addon.request(f)
        assert f.response is None

    def test_blocks_agent_mode_request_with_tools_and_auto_choice(self):
        # Petición real de Copilot Chat en modo agente: incluye `tools` disponibles
        # y `tool_choice: "auto"`, pero es el turno de chat visible del usuario y
        # SÍ debe bloquearse si contiene una keyword baneada.
        body = {
            "model": "gpt-4o",
            "messages": [{"role": "user", "content": "cuéntame sobre mi perro"}],
            "tools": [
                {"type": "function", "function": {"name": "read_file", "parameters": {}}}
            ],
            "tool_choice": "auto",
        }
        f = make_flow("api.githubcopilot.com", body=body)
        self.addon.request(f)
        assert f.response is not None

    def test_ignores_non_copilot_request(self):
        body = {"prompt": "robar contraseñas"}
        f = make_flow("api.openai.com", body=body)
        self.addon.request(f)
        # No debe bloquear aunque tenga keyword, porque no es Copilot
        assert f.response is None

    def test_allows_request_with_no_body(self):
        f = make_flow("api.githubcopilot.com", body=None, method="GET")
        self.addon.request(f)
        assert f.response is None

    def test_blocked_chat_response_is_json(self):
        body = {"messages": [{"role": "user", "content": "explícame un exploit conocido"}]}
        f = make_flow("api.githubcopilot.com", body=body)
        self.addon.request(f)
        assert f.response is not None
        # Debe ser JSON válido con forma de chat.completion
        data = json.loads(f.response.content)
        assert data["object"] == "chat.completion"
        assert data["choices"][0]["message"]["role"] == "assistant"
