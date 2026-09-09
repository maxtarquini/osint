"""Provider discovery checks for inference and embedding nodes."""

from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Event, Thread
from time import monotonic
from typing import Any

import pytest

from raven.ai import SharedAiNode
from raven.config import AiNodeSettings, AiProvider, AiThinkingLevel
from raven.exceptions import (
    InfrastructureAuthenticationError,
    InfrastructureConfigurationError,
)
from raven.exceptions.chat import InvestigationChatCancelledError
from raven.exceptions.graph import GraphAgentRequestError
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

    def post(self, url: str, *, json: dict[str, Any]) -> FakeResponse:
        self.posted_url = url
        self.posted_json = json
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


@pytest.mark.parametrize("stop", ["cancel", "deadline"])
def test_pending_real_http_request_closes_on_cancel_or_deadline(stop):
    received, disconnected = Event(), Event()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            body = b'{"models":[{"model":"test-model"}]}'
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            self.rfile.read(int(self.headers["Content-Length"]))
            received.set()
            self.connection.settimeout(3)
            if self.connection.recv(1) == b"":
                disconnected.set()

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = Thread(target=server.serve_forever, daemon=True)
    worker.start()
    node = SharedAiNode()
    try:
        node.initialize(
            AiNodeSettings(
                model="test-model",
                base_url=f"http://127.0.0.1:{server.server_port}",
                timeout_seconds=1200,
            )
        )
        started = monotonic()
        error = InvestigationChatCancelledError if stop == "cancel" else GraphAgentRequestError
        with pytest.raises(error) as caught:
            node.chat(
                "system",
                "question",
                timeout_seconds=1200 if stop == "cancel" else 0.5,
                cancelled=received.is_set if stop == "cancel" else None,
            )
        assert received.is_set()
        assert monotonic() - started < 2
        assert disconnected.wait(1), "Cancellation must close the socket, not abandon a thread"
        assert not node._request_lock.locked()
        if stop == "deadline":
            assert caught.value.code == "timeout"
    finally:
        node.close()
        server.shutdown()
        server.server_close()
        worker.join(timeout=2)


def test_headless_embedding_connection_does_not_require_or_probe_chat_model() -> None:
    create, clients = client_factory(FakeResponse({"models": [{"model": "embed-only"}]}))
    node = SharedAiNode(create)
    node.initialize_embeddings(AiNodeSettings(embedding_model="embed-only"))
    assert len(clients) == 1
    clients[0].post_response = FakeResponse({"embeddings": [[0.1, 0.2]]})
    assert node.embed(["query"]) == ((0.1, 0.2),)
    assert not node.available
    node.close()
    assert clients[0].closed
