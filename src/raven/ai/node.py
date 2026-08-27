"""Application-wide AI node with provider-specific discovery behind one contract."""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from threading import Lock
from typing import Any, Protocol

import httpx

from raven.config import AiNodeSettings, AiProvider
from raven.exceptions import (
    GraphAgentError,
    InfrastructureAuthenticationError,
    InfrastructureConfigurationError,
    InfrastructureError,
)
from raven.models import TokenUsage


class HttpClient(Protocol):
    def get(self, url: str) -> Any: ...

    def post(self, url: str, *, json: dict[str, Any]) -> Any: ...

    def stream(self, method: str, url: str, *, json: dict[str, Any]) -> Any: ...

    def close(self) -> None: ...


ClientFactory = Callable[..., HttpClient]
UsageReporter = Callable[[TokenUsage], None]


class SharedAiNode:
    """Own independent inference and embedding clients shared by Raven agents."""

    def __init__(self, client_factory: ClientFactory = httpx.Client) -> None:
        self._client_factory = client_factory
        self._chat_client: HttpClient | None = None
        self._embedding_client: HttpClient | None = None
        self._settings: AiNodeSettings | None = None
        self._request_lock = Lock()

    @property
    def settings(self) -> AiNodeSettings | None:
        """Return the active, validated node settings after a successful check."""
        return self._settings

    def initialize(self, settings: AiNodeSettings) -> None:
        chat_client, embedding_client, settings = self._verified_clients(settings)
        self.close()
        self._chat_client = chat_client
        self._embedding_client = embedding_client
        self._settings = settings

    def probe(self, settings: AiNodeSettings) -> None:
        """Verify draft settings without replacing the active shared client."""
        chat_client, embedding_client, _ = self._verified_clients(settings)
        chat_client.close()
        if embedding_client is not None:
            embedding_client.close()

    @property
    def available(self) -> bool:
        return self._chat_client is not None and self._settings is not None

    def chat(self, system_message: str, user_message: str, *, json_mode: bool = False) -> str:
        """Run one shared-node chat call through Ollama or an OpenAI-compatible API."""
        if self._chat_client is None or self._settings is None:
            raise GraphAgentError("The shared AI node is not connected")
        settings = self._settings
        messages = [
            {"role": "system", "content": system_message},
            {"role": "user", "content": user_message},
        ]
        url = self._chat_url(settings.provider, settings.base_url)
        payload = self._chat_payload(settings, messages, stream=False, json_mode=json_mode)
        try:
            with self._request_lock:
                response = self._chat_client.post(url, json=payload)
            if response.status_code in {401, 403}:
                raise GraphAgentError("The AI provider rejected its configured credentials")
            response.raise_for_status()
            body = response.json()
            content = (
                body["message"]["content"]
                if settings.provider is AiProvider.OLLAMA
                else body["choices"][0]["message"]["content"]
            )
        except GraphAgentError:
            raise
        except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError) as error:
            raise GraphAgentError("The AI node returned an invalid graph-agent response") from error
        cleaned = str(content).strip()
        if not cleaned:
            raise GraphAgentError("The AI node returned an empty graph-agent response")
        return cleaned

    def embed(self, texts: list[str]) -> tuple[tuple[float, ...], ...]:
        """Embed a batch through the configured provider on the shared AI endpoint."""
        if self._embedding_client is None or self._settings is None:
            raise GraphAgentError("The embedding node is not connected")
        if not texts:
            return ()
        settings = self._settings
        model = settings.embedding_model.strip()
        if not model:
            raise GraphAgentError("Configure an embedding model for investigation RAG")
        if settings.embedding_provider is AiProvider.OLLAMA:
            url = f"{settings.embedding_base_url.rstrip('/')}/api/embed"
            payload: dict[str, Any] = {"model": model, "input": texts}
        else:
            url = f"{settings.embedding_base_url.rstrip('/')}/embeddings"
            payload = {"model": model, "input": texts}
        try:
            with self._request_lock:
                response = self._embedding_client.post(url, json=payload)
            if response.status_code in {401, 403}:
                raise GraphAgentError("The AI provider rejected its configured credentials")
            response.raise_for_status()
            body = response.json()
            raw_vectors = (
                body["embeddings"]
                if settings.embedding_provider is AiProvider.OLLAMA
                else [item["embedding"] for item in body["data"]]
            )
            vectors = tuple(tuple(float(value) for value in vector) for vector in raw_vectors)
        except GraphAgentError:
            raise
        except (httpx.HTTPError, AttributeError, KeyError, TypeError, ValueError) as error:
            raise GraphAgentError("The AI node returned invalid embeddings") from error
        if len(vectors) != len(texts) or any(not vector for vector in vectors):
            raise GraphAgentError("The AI node returned an incomplete embedding batch")
        return vectors

    def stream_chat(
        self,
        system_message: str,
        messages: list[dict[str, str]],
        *,
        on_usage: UsageReporter | None = None,
    ) -> Iterator[str]:
        """Yield answer fragments from Ollama or an OpenAI-compatible SSE endpoint."""
        if self._chat_client is None or self._settings is None:
            raise GraphAgentError("The shared AI node is not connected")
        settings = self._settings
        conversation = [{"role": "system", "content": system_message}, *messages]
        url = self._chat_url(settings.provider, settings.base_url)
        payload = self._chat_payload(settings, conversation, stream=True)
        try:
            with (
                self._request_lock,
                self._chat_client.stream("POST", url, json=payload) as response,
            ):
                if response.status_code in {401, 403}:
                    raise GraphAgentError("The AI provider rejected its configured credentials")
                response.raise_for_status()
                for line in response.iter_lines():
                    if not line:
                        continue
                    raw = line.decode() if isinstance(line, bytes) else str(line)
                    if settings.provider is not AiProvider.OLLAMA:
                        if not raw.startswith("data:"):
                            continue
                        raw = raw[5:].strip()
                        if raw == "[DONE]":
                            break
                    body = json.loads(raw)
                    usage = self._token_usage(body, settings.provider)
                    if usage is not None and on_usage is not None:
                        on_usage(usage)
                    if settings.provider is AiProvider.OLLAMA:
                        content = body.get("message", {}).get("content")
                    else:
                        choices = body.get("choices", [])
                        content = choices[0].get("delta", {}).get("content") if choices else None
                    if content:
                        yield str(content)
        except GraphAgentError:
            raise
        except (
            httpx.HTTPError,
            AttributeError,
            json.JSONDecodeError,
            KeyError,
            IndexError,
            TypeError,
        ) as error:
            raise GraphAgentError("The AI node returned an invalid streamed response") from error

    @staticmethod
    def _token_usage(payload: Any, provider: AiProvider) -> TokenUsage | None:
        if not isinstance(payload, dict):
            return None
        raw_usage = payload if provider is AiProvider.OLLAMA else payload.get("usage")
        if not isinstance(raw_usage, dict):
            return None
        input_key = "prompt_eval_count" if provider is AiProvider.OLLAMA else "prompt_tokens"
        output_key = "eval_count" if provider is AiProvider.OLLAMA else "completion_tokens"
        try:
            input_tokens = int(raw_usage[input_key])
            output_tokens = int(raw_usage[output_key])
            total_tokens = int(raw_usage.get("total_tokens", input_tokens + output_tokens))
        except (KeyError, TypeError, ValueError):
            return None
        if min(input_tokens, output_tokens, total_tokens) < 0:
            return None
        return TokenUsage(input_tokens, output_tokens, total_tokens)

    def _verified_clients(
        self, settings: AiNodeSettings
    ) -> tuple[HttpClient, HttpClient | None, AiNodeSettings]:
        settings = settings.validated()
        if not settings.model:
            raise InfrastructureConfigurationError("An AI model must be selected")
        chat_client = self._verified_endpoint(
            settings.provider,
            settings.base_url,
            settings.model,
            settings.api_key,
            settings.timeout_seconds,
            "Inference",
        )
        if not settings.embedding_model:
            return chat_client, None, settings
        try:
            embedding_client = self._verified_endpoint(
                settings.embedding_provider,
                settings.embedding_base_url,
                settings.embedding_model,
                settings.embedding_api_key,
                settings.embedding_timeout_seconds,
                "Embedding",
            )
        except Exception:
            chat_client.close()
            raise
        return chat_client, embedding_client, settings

    def _verified_endpoint(
        self,
        provider: AiProvider,
        base_url: str,
        model: str,
        api_key: str | None,
        timeout_seconds: float,
        label: str,
    ) -> HttpClient:
        if provider is AiProvider.OPENAI and not api_key:
            raise InfrastructureAuthenticationError(f"{label} OpenAI endpoint requires an API key")
        headers = {"Accept": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        client = self._client_factory(
            headers=headers,
            timeout=httpx.Timeout(timeout_seconds, connect=min(5.0, timeout_seconds)),
        )
        try:
            response = client.get(self._models_url(provider, base_url))
            if response.status_code in {401, 403}:
                raise InfrastructureAuthenticationError(f"{label} provider rejected credentials")
            response.raise_for_status()
            models = self._model_ids(provider, response.json())
            if not self._contains_model(provider, model, models):
                raise InfrastructureConfigurationError(
                    f"Configured {label.lower()} model is not available from the provider"
                )
        except (InfrastructureAuthenticationError, InfrastructureConfigurationError):
            client.close()
            raise
        except (httpx.HTTPError, TypeError, ValueError, KeyError) as error:
            client.close()
            raise InfrastructureError(f"{label} provider discovery failed") from error
        return client

    def close(self) -> None:
        if self._chat_client is not None:
            self._chat_client.close()
        if self._embedding_client is not None:
            self._embedding_client.close()
        self._chat_client = None
        self._embedding_client = None
        self._settings = None

    @staticmethod
    def _models_url(provider: AiProvider, base_url: str) -> str:
        suffix = "/api/tags" if provider is AiProvider.OLLAMA else "/models"
        return f"{base_url.rstrip('/')}{suffix}"

    @staticmethod
    def _chat_url(provider: AiProvider, base_url: str) -> str:
        suffix = "/api/chat" if provider is AiProvider.OLLAMA else "/chat/completions"
        return f"{base_url.rstrip('/')}{suffix}"

    @staticmethod
    def _chat_payload(
        settings: AiNodeSettings,
        messages: list[dict[str, str]],
        *,
        stream: bool,
        json_mode: bool = False,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": settings.model,
            "messages": messages,
            "stream": stream,
        }
        if settings.provider is AiProvider.OLLAMA:
            options: dict[str, Any] = {
                "top_k": settings.top_k,
                "num_ctx": settings.context_size,
            }
            if settings.random_seed is not None:
                options["seed"] = settings.random_seed
            payload["options"] = options
            payload["think"] = settings.thinking.value
            if json_mode:
                payload["format"] = "json"
            return payload

        payload["temperature"] = 0
        if stream:
            payload["stream_options"] = {"include_usage": True}
        if settings.random_seed is not None:
            payload["seed"] = settings.random_seed
        if settings.provider in {AiProvider.VLLM, AiProvider.LLAMA_CPP}:
            payload["top_k"] = settings.top_k
        if settings.provider in {AiProvider.OPENAI, AiProvider.VLLM}:
            payload["reasoning_effort"] = settings.thinking.value
        elif settings.provider is AiProvider.LLAMA_CPP:
            payload["chat_template_kwargs"] = {
                "reasoning_effort": settings.thinking.value,
                "enable_thinking": True,
            }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        return payload

    @staticmethod
    def _model_ids(provider: AiProvider, payload: Any) -> set[str]:
        if not isinstance(payload, dict):
            raise TypeError("Model discovery response must be an object")
        entries = payload["models"] if provider is AiProvider.OLLAMA else payload["data"]
        if not isinstance(entries, list):
            raise TypeError("Model discovery response must contain a list")
        key = "model" if provider is AiProvider.OLLAMA else "id"
        return {
            str(entry[key])
            for entry in entries
            if isinstance(entry, dict) and entry.get(key) is not None
        }

    @staticmethod
    def _contains_model(provider: AiProvider, requested: str, models: set[str]) -> bool:
        if requested in models:
            return True
        return (
            provider is AiProvider.OLLAMA
            and ":" not in requested
            and f"{requested}:latest" in models
        )
