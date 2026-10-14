"""Small OpenAI-compatible Chat Completions client used by all LLM workflows."""
import json
import os
import urllib.error
import urllib.request
from urllib.parse import urlparse


DEFAULT_URL = "https://api.siliconflow.cn/v1/chat/completions"
DEFAULT_MODEL = "Qwen/Qwen3.5-4B"


def is_configured():
    return bool(os.environ.get("LLM_API_URL") or os.environ.get("LLM_API_KEY") or
                os.environ.get("OPENAI_API_KEY"))


def _settings():
    url = os.environ.get("LLM_API_URL", DEFAULT_URL).strip()
    parsed = urlparse(url)
    local_http = parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost", "::1"}
    if parsed.scheme != "https" and not local_http:
        raise ValueError("LLM_API_URL must use HTTPS, except for a loopback local API")
    return {
        "url": url,
        "key": os.environ.get("LLM_API_KEY", os.environ.get("OPENAI_API_KEY", "")).strip(),
        "model": os.environ.get("LLM_MODEL", DEFAULT_MODEL).strip(),
        "timeout": float(os.environ.get("LLM_TIMEOUT_SECONDS", "60")),
    }


def chat(messages, temperature=0.1):
    if not is_configured():
        raise ValueError("Set LLM_API_KEY (or OPENAI_API_KEY), or configure a local LLM_API_URL")
    settings = _settings()
    payload = {"model": settings["model"], "messages": messages, "temperature": temperature}
    headers = {"Content-Type": "application/json"}
    if settings["key"]:
        headers["Authorization"] = "Bearer " + settings["key"]
    request = urllib.request.Request(settings["url"], data=json.dumps(payload).encode("utf-8"),
                                     headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=settings["timeout"]) as response:
            result = json.load(response)
        content = result["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError, json.JSONDecodeError) as error:
        raise ValueError("LLM response did not match the Chat Completions format") from error
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as error:
        detail = error.read().decode(errors="replace")[:700] if isinstance(error, urllib.error.HTTPError) else str(error)
        raise ValueError("LLM request failed: " + detail) from error
    if isinstance(content, list):
        content = "".join(part.get("text", "") for part in content if isinstance(part, dict))
    if not isinstance(content, str) or not content.strip():
        raise ValueError("LLM returned empty content")
    return content.strip()
