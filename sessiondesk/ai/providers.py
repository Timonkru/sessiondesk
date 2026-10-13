"""AI providers - every user brings their own key (or runs a local model with Ollama).

All providers expose one async generator:  stream(system, messages, max_tokens, effort) -> text chunks
and record token usage in self.last_usage. Streaming is what makes answers feel instant: the first
words show up while the rest is still being generated.

  anthropic   official Anthropic SDK. Default model claude-opus-5-5. Server-side refusal fallback
              (fallbacks="default") is switched on for the models that support it.
  openai      Chat Completions API (also used for OpenRouter and any OpenAI-compatible server)
  gemini      Google Generative Language API (streamGenerateContent, SSE)
  ollama      local models, no key, nothing leaves the machine
"""
from __future__ import annotations

import json
import re
from typing import AsyncIterator

from ..connectors.base import Connector, ConnectorError, Field

# Models that accept output_config.effort, and models with server-side refusal fallback.
EFFORT_MODELS = re.compile(r"^claude-(opus|sonnet|fable|haiku)-(5|4-[678])")
FALLBACK_MODELS = {"claude-opus-5-5", "claude-opus-5", "claude-sonnet-5-5", "claude-fable-5-1", "claude-fable-5"}
ANTHROPIC_PRICES = {  # USD per million tokens (input, output) - for the usage estimate shown in Settings
    "claude-fable-5-1": (10, 50), "claude-opus-5-5": (4, 20), "claude-opus-5": (5, 25),
    "claude-sonnet-5-5": (2, 10), "claude-sonnet-5": (2, 10), "claude-haiku-5-5": (0.10, 0.50),
}
SUGGESTED_MODELS = {
    "anthropic": ["claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5", "claude-fable-5-1"],
    "openai": ["gpt-5", "gpt-5-mini"],
    "gemini": ["gemini-2.5-flash", "gemini-2.5-pro"],
    "openrouter": ["openrouter/auto"],
    "ollama": ["llama3.1", "qwen2.5", "mistral"],
    "custom": [],
}


class AIProvider(Connector):
    kind = "ai"
    capabilities = ("ai",)

    def __init__(self, ctx):
        super().__init__(ctx)
        self.last_usage: dict = {}

    def model(self) -> str:
        return self.ctx.settings.get(f"ai.models.{self.id}") or (SUGGESTED_MODELS.get(self.id) or [""])[0]

    async def stream(self, system: str, messages: list[dict], max_tokens: int = 4000,
                     effort: str | None = None) -> AsyncIterator[str]:
        raise NotImplementedError
        yield ""  # pragma: no cover

    async def test(self) -> dict:
        text = ""
        async for chunk in self.stream("Reply with exactly: OK", [{"role": "user", "content": "ping"}], max_tokens=200, effort="low"):
            text += chunk
        return {"ok": bool(text.strip()), "detail": f"{self.model()}: {text.strip()[:40]}"}

    def describe(self) -> dict:
        d = super().describe()
        d["model"] = self.model()
        d["suggested_models"] = SUGGESTED_MODELS.get(self.id, [])
        return d


# ------------------------------------------------------------------ Anthropic
class AnthropicProvider(AIProvider):
    id = "anthropic"
    name = "Anthropic Claude"
    tier = "paid"
    fields = (Field("api_key", "API key", help="console.anthropic.com -> API keys. Or set ANTHROPIC_API_KEY."),)
    homepage = "https://console.anthropic.com"
    description = "Claude models via the official SDK. Default Claude Opus 5.5; Sonnet 5.5 and Haiku 5.5 are cheaper."
    verified = True

    async def stream(self, system, messages, max_tokens=4000, effort=None):
        try:
            import anthropic
        except ImportError as exc:
            raise ConnectorError("package 'anthropic' is not installed (pip install anthropic)") from exc
        model = self.model()
        client = anthropic.AsyncAnthropic(api_key=self.secret("api_key"), max_retries=2, timeout=120)
        kwargs = {"model": model, "max_tokens": max_tokens, "messages": messages,
                  # The system prompt (rules + docs) is stable between calls -> cache it.
                  "system": [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}]}
        if effort and EFFORT_MODELS.match(model):
            kwargs["output_config"] = {"effort": effort}
        if model in FALLBACK_MODELS:
            kwargs["betas"] = ["server-side-fallback-2026-07-01"]
            kwargs["fallbacks"] = "default"
        try:
            async with client.beta.messages.stream(**kwargs) as stream:
                async for text in stream.text_stream:
                    yield text
                final = await stream.get_final_message()
        except anthropic.AuthenticationError as exc:
            raise ConnectorError("Anthropic: invalid API key") from exc
        except anthropic.PermissionDeniedError as exc:
            raise ConnectorError("Anthropic: key has no access to this model") from exc
        except anthropic.NotFoundError as exc:
            raise ConnectorError(f"Anthropic: unknown model '{model}'") from exc
        except anthropic.RateLimitError as exc:
            raise ConnectorError("Anthropic: rate limit - try again in a minute") from exc
        except anthropic.BadRequestError as exc:
            raise ConnectorError(f"Anthropic: bad request - {exc.message}") from exc
        except anthropic.APIStatusError as exc:
            raise ConnectorError(f"Anthropic: API error {exc.status_code}") from exc
        except anthropic.APIConnectionError as exc:
            raise ConnectorError("Anthropic: cannot reach the API") from exc
        usage = final.usage
        self.last_usage = {"model": final.model, "in": getattr(usage, "input_tokens", 0) or 0,
                           "out": getattr(usage, "output_tokens", 0) or 0,
                           "cache_read": getattr(usage, "cache_read_input_tokens", 0) or 0}
        if final.stop_reason == "refusal":
            yield "\n\n[The model declined this request.]"
        elif final.stop_reason == "max_tokens":
            yield "\n\n[Answer cut off at the length limit.]"


# ------------------------------------------------------------------ OpenAI-compatible
class OpenAIProvider(AIProvider):
    id = "openai"
    name = "OpenAI"
    tier = "paid"
    fields = (Field("api_key", "API key", help="platform.openai.com -> API keys. Or set OPENAI_API_KEY."),)
    homepage = "https://platform.openai.com"
    description = "GPT models via the Chat Completions API. Enter any model id your key can use."
    verified = False
    base_url = "https://api.openai.com/v1"

    def _base(self) -> str:
        return self.base_url

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.secret('api_key') or ''}", "Content-Type": "application/json"}

    async def stream(self, system, messages, max_tokens=4000, effort=None):
        body = {"model": self.model(), "stream": True, "stream_options": {"include_usage": True},
                "messages": [{"role": "system", "content": system}] + messages}
        async with self.ctx.http.stream("POST", self._base().rstrip("/") + "/chat/completions", json=body,
                                        headers=self._headers(), timeout=120) as resp:
            if resp.status_code != 200:
                detail = (await resp.aread()).decode("utf-8", "replace")[:200]
                raise ConnectorError(f"{self.name}: HTTP {resp.status_code} {detail}")
            async for line in resp.aiter_lines():
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                try:
                    chunk = json.loads(data)
                except ValueError:
                    continue
                if chunk.get("usage"):
                    u = chunk["usage"]
                    self.last_usage = {"model": self.model(), "in": u.get("prompt_tokens", 0), "out": u.get("completion_tokens", 0)}
                for choice in chunk.get("choices") or []:
                    text = (choice.get("delta") or {}).get("content")
                    if text:
                        yield text


class OpenRouterProvider(OpenAIProvider):
    id = "openrouter"
    name = "OpenRouter"
    fields = (Field("api_key", "API key", help="openrouter.ai/keys - one key, many model vendors."),)
    homepage = "https://openrouter.ai"
    description = "Hundreds of models (Claude, GPT, Llama, Mistral ...) through one OpenAI-compatible key."
    base_url = "https://openrouter.ai/api/v1"


class CustomProvider(OpenAIProvider):
    id = "custom"
    name = "OpenAI-compatible server"
    tier = "free"
    fields = (Field("api_key", "API key", required=False, help="Leave empty for local servers like LM Studio or vLLM."),)
    homepage = ""
    description = "Any server that speaks the OpenAI Chat Completions protocol (LM Studio, vLLM, Groq, Together ...). Base URL in AI settings."

    def configured(self) -> bool:
        return bool(self.ctx.settings.get("ai.custom_base_url"))

    def _base(self) -> str:
        return self.ctx.settings.get("ai.custom_base_url") or ""


# ------------------------------------------------------------------ Gemini
class GeminiProvider(AIProvider):
    id = "gemini"
    name = "Google Gemini"
    tier = "free-key"
    fields = (Field("api_key", "API key", help="aistudio.google.com -> Get API key. Or set GEMINI_API_KEY."),)
    homepage = "https://aistudio.google.com"
    description = "Gemini models via the Generative Language API (free tier available)."
    verified = False

    async def stream(self, system, messages, max_tokens=4000, effort=None):
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model()}:streamGenerateContent"
        contents = [{"role": "model" if m["role"] == "assistant" else "user", "parts": [{"text": m["content"]}]} for m in messages]
        body = {"systemInstruction": {"parts": [{"text": system}]}, "contents": contents,
                "generationConfig": {"maxOutputTokens": max_tokens}}
        async with self.ctx.http.stream("POST", url, params={"alt": "sse"}, json=body, timeout=120,
                                        headers={"x-goog-api-key": self.secret("api_key") or ""}) as resp:
            if resp.status_code != 200:
                detail = (await resp.aread()).decode("utf-8", "replace")[:200]
                raise ConnectorError(f"Gemini: HTTP {resp.status_code} {detail}")
            async for line in resp.aiter_lines():
                if not line.startswith("data:"):
                    continue
                try:
                    chunk = json.loads(line[5:].strip())
                except ValueError:
                    continue
                if chunk.get("usageMetadata"):
                    u = chunk["usageMetadata"]
                    self.last_usage = {"model": self.model(), "in": u.get("promptTokenCount", 0), "out": u.get("candidatesTokenCount", 0)}
                for cand in chunk.get("candidates") or []:
                    for part in (cand.get("content") or {}).get("parts") or []:
                        if part.get("text"):
                            yield part["text"]


# ------------------------------------------------------------------ Ollama
class OllamaProvider(AIProvider):
    id = "ollama"
    name = "Ollama (local)"
    tier = "free"
    fields = ()
    homepage = "https://ollama.com"
    description = "Run open models on your own machine. No key, no cost, nothing leaves your computer. Slower and less precise than hosted models."
    verified = False
    default_enabled = True

    def configured(self) -> bool:
        return True

    async def stream(self, system, messages, max_tokens=4000, effort=None):
        base = (self.ctx.settings.get("ai.ollama_url") or "http://127.0.0.1:11434").rstrip("/")
        body = {"model": self.model(), "stream": True, "options": {"num_predict": max_tokens},
                "messages": [{"role": "system", "content": system}] + messages}
        try:
            async with self.ctx.http.stream("POST", base + "/api/chat", json=body, timeout=300) as resp:
                if resp.status_code != 200:
                    detail = (await resp.aread()).decode("utf-8", "replace")[:200]
                    raise ConnectorError(f"Ollama: HTTP {resp.status_code} {detail}")
                async for line in resp.aiter_lines():
                    if not line.strip():
                        continue
                    try:
                        chunk = json.loads(line)
                    except ValueError:
                        continue
                    text = (chunk.get("message") or {}).get("content")
                    if text:
                        yield text
                    if chunk.get("done"):
                        self.last_usage = {"model": self.model(), "in": chunk.get("prompt_eval_count", 0), "out": chunk.get("eval_count", 0)}
        except ConnectorError:
            raise
        except Exception as exc:
            raise ConnectorError(f"Ollama not reachable at {base} - is it running? ({type(exc).__name__})") from exc


PROVIDERS = (AnthropicProvider, OpenAIProvider, GeminiProvider, OpenRouterProvider, OllamaProvider, CustomProvider)


def estimate_cost(usage: dict) -> float | None:
    price = ANTHROPIC_PRICES.get(usage.get("model", ""))
    if not price:
        return None
    fresh_in = max(0, usage.get("in", 0))
    return (fresh_in * price[0] + usage.get("cache_read", 0) * price[0] * 0.1 + usage.get("out", 0) * price[1]) / 1e6
