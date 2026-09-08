"""The skill agent's structured, bounded request contract on the dev AI adapter."""

import json

import httpx
import pytest
from test_capabilities import DESCRIPTION

from raven.agents.skill_catalog import SkillCatalogAgent
from raven.ai import SharedAiNode
from raven.config import AiNodeSettings, AiProvider, AiThinkingLevel
from raven.exceptions.chat import InvestigationChatCancelledError
from raven.exceptions.graph import GraphAgentRequestError
from raven.models.capabilities import SkillDefinition
from raven.tui.screens.capabilities import skill_template


class Client:
    def __init__(self, provider):
        self.provider = provider
        self.calls = []
        self.timeout = False
        self.limited = False

    def post(self, url, **kwargs):
        self.calls.append(kwargs)
        if self.timeout:
            raise httpx.ReadTimeout("Timed out")
        content = json.dumps(DESCRIPTION)
        body = (
            {"message": {"content": content}, "done_reason": "length" if self.limited else "stop"}
            if self.provider == AiProvider.OLLAMA
            else {
                "choices": [
                    {
                        "message": {"content": content},
                        "finish_reason": "length" if self.limited else "stop",
                    }
                ]
            }
        )
        return httpx.Response(200, json=body, request=httpx.Request("POST", url))


@pytest.mark.parametrize("provider", [AiProvider.OLLAMA, AiProvider.LLAMA_CPP])
def test_agent_enforces_schema_budget_and_thinking_without_changing_global_settings(provider):
    node = SharedAiNode()
    node._settings = AiNodeSettings(provider=provider, model="test", thinking=AiThinkingLevel.HIGH)
    client = Client(provider)
    node._chat_client = client
    agent = SkillCatalogAgent(node)
    skill = SkillDefinition.parse(skill_template())
    assert agent.describe(skill) == DESCRIPTION
    request = client.calls[0]
    payload = request["json"]
    assert request["timeout"].read <= 120
    if provider == AiProvider.OLLAMA:
        assert payload["format"]["additionalProperties"] is False
        assert payload["options"]["num_predict"] == 2048
        assert payload["think"] == "low"
    else:
        assert payload["response_format"]["json_schema"]["strict"] is True
        assert payload["max_tokens"] == 2048
        assert payload["chat_template_kwargs"]["reasoning_effort"] == "low"
    assert node.settings.thinking == AiThinkingLevel.HIGH
    with pytest.raises(InvestigationChatCancelledError):
        agent.describe(skill, cancelled=lambda: True)
    assert len(client.calls) == 1
    client.timeout = True
    with pytest.raises(GraphAgentRequestError) as error:
        agent.describe(skill)
    assert error.value.code == "timeout"
    client.timeout = False
    client.limited = True
    with pytest.raises(GraphAgentRequestError) as error:
        agent.describe(skill)
    assert error.value.code == "output_limit"
