"""
mitmproxy addon: GitHub Copilot Content Policy Filter

Intercepts requests to GitHub Copilot and blocks those whose prompt
contains any of the banned keywords defined in BANNED_KEYWORDS.
"""

import json
import re
import time
import uuid
import logging

from mitmproxy import http
from mitmproxy.http import HTTPFlow

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("copilot-filter")

# GitHub Copilot known domains
COPILOT_DOMAINS = [
    "copilot-proxy.githubusercontent.com",
    "api.githubcopilot.com",
    "githubcopilot.com",
    "copilot.github.com",
]

# Keywords that will cause the request to be blocked (case-insensitive)
BANNED_KEYWORDS = [
    "robar",
    "robo",
    "hack",
    "exploit",
    "malware",
    "ransomware",
    "phishing",
    "inyección sql",
    "sql injection",
    "ddos",
    "keylogger",
    "perro"
]


def _is_copilot_request(flow: HTTPFlow) -> bool:
    host = flow.request.pretty_host.lower()
    return any(domain in host for domain in COPILOT_DOMAINS)


def _extract_prompt_text(body: bytes) -> str:
    """Extract all text content from a Copilot request body."""
    try:
        data = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return ""

    parts = []

    # Completions API: { "prompt": "..." }
    if isinstance(data.get("prompt"), str):
        parts.append(data["prompt"])

    # Chat completions API: { "messages": [{"role": "...", "content": "..."}] }
    for msg in data.get("messages", []):
        content = msg.get("content", "")
        if isinstance(content, str):
            parts.append(content)
        elif isinstance(content, list):
            # Content can be a list of blocks: [{"type": "text", "text": "..."}]
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    parts.append(block.get("text", ""))

    return " ".join(parts)


def _find_banned_keyword(text: str) -> str | None:
    lower = text.lower()
    for keyword in BANNED_KEYWORDS:
        if re.search(r"\b" + re.escape(keyword) + r"\b", lower):
            return keyword
    return None


def _blocked_message(keyword: str) -> str:
    return (
        "🚫 This request has been blocked by the content policy "
        f"(keyword detected: **{keyword}**). Rephrase your message without that content."
    )


def _detect_api_format(flow: HTTPFlow, data: dict) -> str:
    """Detect the API format to return a compatible simulated response.

    - "anthropic": Anthropic Messages API (used by Copilot with Claude models),
      identifiable by the `/v1/messages` path.
    - "openai_chat": OpenAI Chat Completions API (has `messages`, but isn't `/v1/messages`).
    - "openai_completion": Classic Completions API (inline code suggestions).
    """
    path = flow.request.path.lower()
    if "/messages" in path:
        return "anthropic"
    if isinstance(data.get("messages"), list):
        return "openai_chat"
    return "openai_completion"


def _build_chat_completion_payload(message: str, model: str) -> dict:
    """Non-streaming response compatible with the Chat Completions API."""
    return {
        "id": f"chatcmpl-blocked-{uuid.uuid4().hex[:12]}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": message},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    }


def _build_chat_stream_body(message: str, model: str) -> bytes:
    """SSE (Server-Sent Events) formatted response, as expected by Copilot Chat
    when the request asks for `"stream": true`."""
    chat_id = f"chatcmpl-blocked-{uuid.uuid4().hex[:12]}"
    created = int(time.time())
    content_chunk = {
        "id": chat_id,
        "object": "chat.completion.chunk",
        "created": created,
        "model": model,
        "choices": [{"index": 0, "delta": {"role": "assistant", "content": message}, "finish_reason": None}],
    }
    stop_chunk = {
        "id": chat_id,
        "object": "chat.completion.chunk",
        "created": created,
        "model": model,
        "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
    }
    events = [
        f"data: {json.dumps(content_chunk)}\n\n",
        f"data: {json.dumps(stop_chunk)}\n\n",
        "data: [DONE]\n\n",
    ]
    return "".join(events).encode()


def _build_anthropic_payload(message: str, model: str) -> dict:
    """Non-streaming response compatible with the Anthropic Messages API."""
    return {
        "id": f"msg_blocked_{uuid.uuid4().hex[:24]}",
        "type": "message",
        "role": "assistant",
        "model": model,
        "content": [{"type": "text", "text": message}],
        "stop_reason": "end_turn",
        "stop_sequence": None,
        "usage": {"input_tokens": 0, "output_tokens": 0},
    }


def _build_anthropic_stream_body(message: str, model: str) -> bytes:
    """SSE formatted response for the Anthropic Messages API. Unlike OpenAI,
    each event carries an `event: <type>` line in addition to `data: <json>`, and the
    lifecycle is message_start -> content_block_start -> content_block_delta(s) ->
    content_block_stop -> message_delta -> message_stop."""
    msg_id = f"msg_blocked_{uuid.uuid4().hex[:24]}"

    def _event(name: str, payload: dict) -> str:
        return f"event: {name}\ndata: {json.dumps(payload)}\n\n"

    events = [
        _event("message_start", {
            "type": "message_start",
            "message": {
                "id": msg_id,
                "type": "message",
                "role": "assistant",
                "model": model,
                "content": [],
                "stop_reason": None,
                "stop_sequence": None,
                "usage": {"input_tokens": 0, "output_tokens": 0},
            },
        }),
        _event("content_block_start", {
            "type": "content_block_start",
            "index": 0,
            "content_block": {"type": "text", "text": ""},
        }),
        _event("content_block_delta", {
            "type": "content_block_delta",
            "index": 0,
            "delta": {"type": "text_delta", "text": message},
        }),
        _event("content_block_stop", {"type": "content_block_stop", "index": 0}),
        _event("message_delta", {
            "type": "message_delta",
            "delta": {"stop_reason": "end_turn", "stop_sequence": None},
            "usage": {"output_tokens": 0},
        }),
        _event("message_stop", {"type": "message_stop"}),
    ]
    return "".join(events).encode()


def _build_completion_payload(model: str) -> dict:
    """Empty response compatible with the classic Completions API (inline code
    suggestions). Returning empty text keeps the user from seeing an error while
    typing; simply no suggestion appears."""
    return {
        "id": f"cmpl-blocked-{uuid.uuid4().hex[:12]}",
        "object": "text_completion",
        "created": int(time.time()),
        "model": model,
        "choices": [{"text": "", "index": 0, "logprobs": None, "finish_reason": "stop"}],
    }


def _parse_json_body(body: bytes) -> dict:
    try:
        data = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _wants_tool_call(data: dict) -> bool:
    """Detect internal function/tool-calling requests (e.g. the automatic prompt
    classification that the Copilot extension itself performs, with `tools` +
    `tool_choice` forced to a specific function and auxiliary models like
    gpt-4o-mini). For these requests the expected response is a `tool_calls` with
    JSON arguments, not a text message: blocking them with our simulated response
    would break that protocol and the extension would fail ("Sorry,
    no response was returned"). That's why they're let through unblocked; the
    actual block happens on the visible chat/messages request.

    Important: it's NOT enough to check that `tools`/`tool_choice` exist, because
    Copilot Chat in agent mode includes `tools` + `tool_choice: "auto"` in
    practically every real user request (so it can invoke tools like read_file,
    edit, etc.). Treating that as "internal" would let all real traffic through
    unfiltered. A request is only considered internal when `tool_choice` FORCES a
    specific function (an object `{"type": "function", "function": {"name": "..."}}`
    or a string other than "auto"/"none"/"required"), which is the pattern of
    automatic classification calls, not a normal chat/agent turn."""
    tool_choice = data.get("tool_choice")
    if isinstance(tool_choice, dict):
        return True
    if isinstance(tool_choice, str) and tool_choice not in ("auto", "none", "required"):
        return True
    return False


def _build_blocked_response(flow: HTTPFlow, keyword: str) -> http.Response:
    """Build an HTTP 200 response that impersonates the real Copilot API format,
    instead of a bare 403. This way the block shows up as a normal assistant
    message (or, for inline suggestions, as the absence of a suggestion) instead
    of a network error in the UI."""
    data = _parse_json_body(flow.request.content)

    model = data.get("model", "gpt-4o")
    api_format = _detect_api_format(flow, data)
    is_stream = bool(data.get("stream"))

    if api_format == "openai_completion":
        payload = _build_completion_payload(model)
        return http.Response.make(200, json.dumps(payload), {"Content-Type": "application/json"})

    message = _blocked_message(keyword)

    if api_format == "anthropic":
        if is_stream:
            content = _build_anthropic_stream_body(message, model)
            return http.Response.make(200, content, {"Content-Type": "text/event-stream"})
        payload = _build_anthropic_payload(message, model)
        return http.Response.make(200, json.dumps(payload), {"Content-Type": "application/json"})

    # openai_chat
    if is_stream:
        content = _build_chat_stream_body(message, model)
        return http.Response.make(200, content, {"Content-Type": "text/event-stream"})

    payload = _build_chat_completion_payload(message, model)
    return http.Response.make(200, json.dumps(payload), {"Content-Type": "application/json"})


class CopilotContentFilter:
    def request(self, flow: HTTPFlow) -> None:
        if not _is_copilot_request(flow):
            return

        logger.info("Copilot request intercepted: %s %s", flow.request.method, flow.request.pretty_url)

        prompt_text = _extract_prompt_text(flow.request.content)
        if not prompt_text:
            return

        banned = _find_banned_keyword(prompt_text)
        if not banned:
            return

        if _wants_tool_call(_parse_json_body(flow.request.content)):
            logger.warning(
                "Keyword '%s' detected in an internal tool-calling request — letting it "
                "through unblocked to avoid breaking the function calling protocol | URL: %s",
                banned,
                flow.request.pretty_url,
            )
            return

        logger.warning(
            "BLOCKED request — banned keyword detected: '%s' | URL: %s",
            banned,
            flow.request.pretty_url,
        )
        flow.response = _build_blocked_response(flow, banned)


addons = [CopilotContentFilter()]
