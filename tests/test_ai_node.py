"""Provider discovery checks for inference and embedding nodes."""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from raven.ai import SharedAiNode
from raven.config import AiNodeSettings, AiProvider, AiThinkingLevel
from raven.exceptions import (
    GraphAgentError,
    InfrastructureAuthenticationError,
    InfrastructureConfigurationError,
)
from raven.models import TokenUsage


class FakeResponse:
    def __init__(self, payload: dict[str, Any], status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code

    def json(self) -> dict[str, Any]:
        return self._payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError("unexpected status")


class FakeClient:
    def __init__(self, response: FakeResponse, **options: Any) -> None:
        self.response = response
        self.options = options
        self.requested_url: str | None = None
        self.post_response: FakeResponse | None = None
        self.posted_url: str | None = None
        self.posted_json: dict[str, Any] | None = None
        self.stream_response: FakeStreamResponse | None = None
        self.closed = False

    def get(self, url: str) -> FakeResponse:
        self.requested_url = url
        return self.response

    def post(self, url: str, *, json: dict[str, Any], **options: Any) -> FakeResponse:
        self.posted_url = url
        self.posted_json = json
        self.post_options = options
        return self.post_response or self.response

    def stream(self, method: str, url: str, *, json: dict[str, Any]):
        self.posted_url = url
        self.posted_json = json
        assert method == "POST"
        assert self.stream_response is not None
        return self.stream_response

    def close(self) -> None:
        self.closed = True


class FakeStreamResponse(FakeResponse):
    def __init__(self, lines: list[str], status_code: int = 200) -> None:
        super().__init__({}, status_code)
        self.lines = lines

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        return None

    def iter_lines(self):
        return iter(self.lines)


def client_factory(response: FakeResponse) -> tuple[Any, list[FakeClient]]:
    clients: list[FakeClient] = []

    def create(**options: Any) -> FakeClient:
        client = FakeClient(response, **options)
        clients.append(client)
        return client

    return create, clients


@pytest.mark.parametrize(
    ("provider", "base_url"),
    [
        (AiProvider.VLLM, "http://localhost:8000/v1"),
        (AiProvider.LLAMA_CPP, "http://localhost:8080/v1"),
        (AiProvider.OPENAI, "https://api.openai.com/v1"),
    ],
)
def test_openai_compatible_providers_share_model_discovery(
    provider: AiProvider, base_url: str
) -> None:
    create, clients = client_factory(FakeResponse({"data": [{"id": "model-a"}]}))
    node = SharedAiNode(create)

    node.initialize(
        AiNodeSettings(
            provider=provider,
            base_url=base_url,
            model="model-a",
            api_key="secret" if provider is AiProvider.OPENAI else None,
        )
    )

    assert node.settings is not None
    assert node.settings.model == "model-a"
    assert clients[0].requested_url == f"{base_url}/models"


def test_ollama_uses_native_tags_and_accepts_implicit_latest_tag() -> None:
    create, clients = client_factory(FakeResponse({"models": [{"model": "qwen3:latest"}]}))
    node = SharedAiNode(create)

    node.initialize(AiNodeSettings(model="qwen3"))

    assert clients[0].requested_url == "http://localhost:11434/api/tags"


def test_probe_closes_its_client_without_replacing_active_node() -> None:
    create, clients = client_factory(FakeResponse({"models": [{"model": "qwen3"}]}))
    node = SharedAiNode(create)
    settings = AiNodeSettings(model="qwen3")
    node.initialize(settings)

    node.probe(settings)

    assert node.settings == settings
    assert not clients[0].closed
    assert clients[1].closed


def test_probe_executes_embedding_and_returns_its_dimension() -> None:
    clients: list[FakeClient] = []
    models = FakeResponse({"models": [{"model": "qwen3"}, {"model": "bge-m3"}]})

    def create(**options: Any) -> FakeClient:
        client = FakeClient(models, **options)
        if clients:
            client.post_response = FakeResponse({"embeddings": [[0.1, 0.2, 0.3]]})
        clients.append(client)
        return client

    dimension = SharedAiNode(create).probe(AiNodeSettings(model="qwen3", embedding_model="bge-m3"))

    assert dimension == 3
    assert clients[1].posted_url == "http://localhost:11434/api/embed"
    assert all(client.closed for client in clients)


def test_missing_or_unknown_model_requires_configuration() -> None:
    create, clients = client_factory(FakeResponse({"models": []}))
    node = SharedAiNode(create)

    with pytest.raises(InfrastructureConfigurationError, match="selected"):
        node.initialize(AiNodeSettings())
    assert clients == []

    with pytest.raises(InfrastructureConfigurationError, match="not available"):
        node.initialize(AiNodeSettings(model="missing"))
    assert clients[0].closed


def test_openai_requires_api_key_without_making_a_request() -> None:
    create, clients = client_factory(FakeResponse({"data": []}))
    node = SharedAiNode(create)

    with pytest.raises(InfrastructureAuthenticationError, match="API key"):
        node.initialize(
            AiNodeSettings(
                provider=AiProvider.OPENAI,
                base_url="https://api.openai.com/v1",
                model="gpt-5.4-mini",
            )
        )

    assert clients == []


def test_provider_authentication_failure_is_classified_and_secret_is_not_exposed() -> None:
    create, clients = client_factory(FakeResponse({}, status_code=401))
    node = SharedAiNode(create)

    with pytest.raises(InfrastructureAuthenticationError):
        node.initialize(AiNodeSettings(model="private", api_key="top-secret"))

    assert clients[0].options["headers"]["Authorization"] == "Bearer top-secret"
    assert clients[0].closed


def test_ollama_chat_uses_the_initialized_shared_node_and_json_mode() -> None:
    create, clients = client_factory(FakeResponse({"models": [{"model": "qwen3"}]}))
    node = SharedAiNode(create)
    node.initialize(AiNodeSettings(model="qwen3"))
    clients[0].post_response = FakeResponse({"message": {"content": '{"entities":[]}'}})

    output = node.chat("system", "Evidence", json_mode=True)

    assert output == '{"entities":[]}'
    assert clients[0].posted_url == "http://localhost:11434/api/chat"
    assert clients[0].posted_json == {
        "model": "qwen3",
        "messages": [
            {"role": "system", "content": "system"},
            {"role": "user", "content": "Evidence"},
        ],
        "stream": False,
        "format": "json",
        "options": {"top_k": 40, "num_ctx": 32768},
        "think": "medium",
    }


def test_chat_timeout_reports_configured_duration() -> None:
    class TimeoutClient(FakeClient):
        def post(self, url: str, *, json: dict[str, Any]) -> FakeResponse:
            raise httpx.ReadTimeout("model response timed out")

    clients: list[TimeoutClient] = []

    def create(**options: Any) -> TimeoutClient:
        client = TimeoutClient(FakeResponse({"models": [{"model": "qwen3"}]}), **options)
        clients.append(client)
        return client

    node = SharedAiNode(create)
    node.initialize(AiNodeSettings(model="qwen3", timeout_seconds=45))

    with pytest.raises(GraphAgentError, match="timed out after 45 seconds"):
        node.chat("system", "Evidence")


def test_ollama_embeddings_use_the_configured_embedding_model() -> None:
    create, clients = client_factory(
        FakeResponse({"models": [{"model": "qwen3"}, {"model": "nomic-embed-text"}]})
    )
    node = SharedAiNode(create)
    node.initialize(AiNodeSettings(model="qwen3", embedding_model="nomic-embed-text"))
    clients[1].post_response = FakeResponse({"embeddings": [[0.1, 0.2], [0.3, 0.4]]})

    vectors = node.embed(["first", "second"])

    assert vectors == ((0.1, 0.2), (0.3, 0.4))
    assert clients[1].posted_url == "http://localhost:11434/api/embed"
    assert clients[1].posted_json == {
        "model": "nomic-embed-text",
        "input": ["first", "second"],
    }


def test_openai_compatible_chat_stream_parses_sse_fragments() -> None:
    create, clients = client_factory(
        FakeResponse({"data": [{"id": "chat-model"}, {"id": "embed-model"}]})
    )
    node = SharedAiNode(create)
    node.initialize(
        AiNodeSettings(
            provider=AiProvider.VLLM,
            base_url="http://localhost:8000/v1",
            model="chat-model",
            thinking=AiThinkingLevel.HIGH,
            top_k=18,
            random_seed=1234,
            timeout_seconds=75,
            embedding_provider=AiProvider.VLLM,
            embedding_base_url="http://localhost:8000/v1",
            embedding_model="embed-model",
        )
    )
    clients[0].stream_response = FakeStreamResponse(
        [
            'data: {"choices":[{"delta":{"content":"Hello "}}]}',
            'data: {"choices":[{"delta":{"content":"world"}}]}',
            'data: {"choices":[],"usage":{"prompt_tokens":12,'
            '"completion_tokens":3,"total_tokens":15}}',
            "data: [DONE]",
        ]
    )
    usage: list[TokenUsage] = []

    fragments = tuple(
        node.stream_chat(
            "Ground your answer",
            [{"role": "user", "content": "Question"}],
            on_usage=usage.append,
        )
    )

    assert fragments == ("Hello ", "world")
    assert clients[0].posted_url == "http://localhost:8000/v1/chat/completions"
    assert clients[0].posted_json["stream"] is True
    assert clients[0].posted_json["stream_options"] == {"include_usage": True}
    assert clients[0].posted_json["reasoning_effort"] == "high"
    assert clients[0].posted_json["top_k"] == 18
    assert clients[0].posted_json["seed"] == 1234
    assert clients[0].options["timeout"].read == 75
    assert usage == [TokenUsage(12, 3, 15)]


def test_embedding_endpoint_has_independent_provider_credentials_and_timeout() -> None:
    discovery = FakeResponse(
        {
            "models": [{"model": "qwen3"}],
            "data": [{"id": "text-embedding-3-small"}],
        }
    )
    create, clients = client_factory(discovery)
    node = SharedAiNode(create)
    node.initialize(
        AiNodeSettings(
            model="qwen3",
            embedding_provider=AiProvider.OPENAI,
            embedding_base_url="https://api.openai.com/v1",
            embedding_model="text-embedding-3-small",
            embedding_api_key="embedding-secret",
            embedding_timeout_seconds=35,
        )
    )
    clients[1].post_response = FakeResponse({"data": [{"embedding": [0.1, 0.2]}]})

    vectors = node.embed(["Evidence"])

    assert vectors == ((0.1, 0.2),)
    assert clients[0].requested_url == "http://localhost:11434/api/tags"
    assert clients[1].requested_url == "https://api.openai.com/v1/models"
    assert clients[1].options["headers"]["Authorization"] == "Bearer embedding-secret"
    assert clients[1].options["timeout"].read == 35
    assert clients[1].posted_url == "https://api.openai.com/v1/embeddings"


def test_ollama_chat_stream_reports_native_token_usage() -> None:
    create, clients = client_factory(FakeResponse({"models": [{"model": "qwen3"}]}))
    node = SharedAiNode(create)
    node.initialize(AiNodeSettings(model="qwen3"))
    clients[0].stream_response = FakeStreamResponse(
        [
            '{"message":{"content":"Hello"},"done":false}',
            '{"message":{"content":""},"done":true,"prompt_eval_count":21,"eval_count":5}',
        ]
    )
    usage: list[TokenUsage] = []

    fragments = tuple(
        node.stream_chat(
            "Ground your answer",
            [{"role": "user", "content": "Question"}],
            on_usage=usage.append,
        )
    )

    assert fragments == ("Hello",)
    assert usage == [TokenUsage(21, 5, 26)]


def test_llama_cpp_receives_sampling_and_template_thinking_controls() -> None:
    create, clients = client_factory(FakeResponse({"data": [{"id": "local-model"}]}))
    node = SharedAiNode(create)
    node.initialize(
        AiNodeSettings(
            provider=AiProvider.LLAMA_CPP,
            base_url="http://localhost:8080/v1",
            model="local-model",
            thinking=AiThinkingLevel.LOW,
            top_k=64,
            random_seed=9,
        )
    )
    clients[0].stream_response = FakeStreamResponse(["data: [DONE]"])

    assert tuple(node.stream_chat("system", [{"role": "user", "content": "Question"}])) == ()
    assert clients[0].posted_json["top_k"] == 64
    assert clients[0].posted_json["seed"] == 9
    assert clients[0].posted_json["chat_template_kwargs"] == {
        "reasoning_effort": "low",
        "enable_thinking": True,
    }


@pytest.mark.parametrize("provider", list(AiProvider))
def test_bounded_catalog_request_preserves_global_settings(provider):
    model = "catalog-model"
    discovery = (
        {"models": [{"model": model}]}
        if provider is AiProvider.OLLAMA
        else {"data": [{"id": model}]}
    )
    create, clients = client_factory(FakeResponse(discovery))
    node = SharedAiNode(create)
    node.initialize(
        AiNodeSettings(
            provider=provider,
            model=model,
            api_key="test-key",
            timeout_seconds=1200,
            thinking=AiThinkingLevel.HIGH,
        )
    )
    clients[0].post_response = FakeResponse(
        {"message": {"content": "{}"}, "done_reason": "stop"}
        if provider is AiProvider.OLLAMA
        else {"choices": [{"message": {"content": "{}"}, "finish_reason": "stop"}]}
    )
    assert (
        node.chat(
            "system",
            "source",
            json_mode=True,
            json_schema={"type": "object", "properties": {}},
            max_output_tokens=4096,
            timeout_seconds=180,
            thinking=AiThinkingLevel.LOW,
        )
        == "{}"
    )
    payload = clients[0].posted_json
    if provider is AiProvider.OLLAMA:
        assert payload["format"] == {"type": "object", "properties": {}}
        assert payload["options"]["num_predict"] == 4096
        assert payload["think"] == "low"
    else:
        assert payload["response_format"]["type"] == "json_schema"
        assert payload["response_format"]["json_schema"]["strict"] is True
        assert payload["response_format"]["json_schema"]["schema"] == {
            "type": "object",
            "properties": {},
        }
        key = "max_completion_tokens" if provider is AiProvider.OPENAI else "max_tokens"
        assert payload[key] == 4096
    assert 0 < clients[0].post_options["timeout"].read <= 180
    assert node.settings.thinking is AiThinkingLevel.HIGH
    assert node.settings.timeout_seconds == 1200


def test_output_limit_is_an_error_even_if_partial_response_is_valid_json():
    from raven.exceptions import GraphAgentRequestError

    create, clients = client_factory(FakeResponse({"data": [{"id": "model"}]}))
    node = SharedAiNode(create)
    node.initialize(AiNodeSettings(provider=AiProvider.LLAMA_CPP, model="model"))
    clients[0].post_response = FakeResponse(
        {"choices": [{"message": {"content": "{}"}, "finish_reason": "length"}]}
    )
    with pytest.raises(GraphAgentRequestError) as failure:
        node.chat("system", "source", max_output_tokens=4096)
    assert failure.value.code == "output_limit"


def test_cancelled_request_waiting_for_shared_node_never_posts():
    from raven.exceptions import InvestigationChatCancelledError

    create, clients = client_factory(FakeResponse({"models": [{"model": "qwen3"}]}))
    node = SharedAiNode(create)
    node.initialize(AiNodeSettings(model="qwen3"))
    checks = 0

    def cancelled():
        nonlocal checks
        checks += 1
        return checks > 1

    node._request_lock.acquire()
    try:
        with pytest.raises(InvestigationChatCancelledError):
            node.chat("system", "source", timeout_seconds=180, cancelled=cancelled)
    finally:
        node._request_lock.release()
    assert clients[0].posted_json is None
