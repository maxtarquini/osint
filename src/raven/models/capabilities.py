"""Portable skill definitions and deterministic contracts for capability discovery."""

import hashlib
import json
import re
from dataclasses import dataclass

from raven.exceptions.capabilities import CapabilityError


def text_value(value, limit=200):
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise CapabilityError(f"Expected non-empty text, maximum {limit} characters")
    if any(ord(char) < 32 and char not in "\n\t" for char in value):
        raise CapabilityError("Control characters are not allowed")
    return value.strip()


def text_list(value, limit=20):
    if not isinstance(value, list) or len(value) > limit:
        raise CapabilityError(f"Expected a list of at most {limit} items")
    return tuple(text_value(item, 300) for item in value)


@dataclass(frozen=True)
class SkillDefinition:
    skill_id: str
    name: str
    version: str
    description: str
    inputs: tuple[str, ...]
    outputs: tuple[str, ...]
    tools: tuple[str, ...]
    instructions: str
    source: str
    digest: str
    filename: str = ""

    @classmethod
    def parse(cls, source: str, filename: str = ""):
        if len(source.encode("utf-8")) > 32768:
            raise CapabilityError("A .SKILL file must not exceed 32 KiB")
        match = re.match(r"\A\s*```json\s*\n(.*?)\n```\s*\n(.*)\Z", source, re.S)
        if not match:
            raise CapabilityError("Start with a JSON metadata block, followed by Markdown")
        try:
            metadata = json.loads(match[1])
        except ValueError as error:
            raise CapabilityError("Invalid JSON metadata") from error
        required = {"id", "name", "version", "description", "inputs", "outputs", "tools"}
        if not isinstance(metadata, dict) or set(metadata) != required:
            raise CapabilityError("Metadata requires exactly: " + ", ".join(sorted(required)))
        skill_id = text_value(metadata["id"], 64)
        if not re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", skill_id):
            raise CapabilityError("Skill ID must use lowercase letters, numbers, _ or -")
        version = text_value(metadata["version"], 40)
        if not re.fullmatch(r"\d+\.\d+\.\d+", version):
            raise CapabilityError("Version must be major.minor.patch, for example 1.0.0")
        return cls(
            skill_id,
            text_value(metadata["name"]),
            version,
            text_value(metadata["description"], 800),
            text_list(metadata["inputs"]),
            text_list(metadata["outputs"]),
            text_list(metadata["tools"]),
            text_value(match[2], 30000),
            source,
            hashlib.sha256(source.encode("utf-8")).hexdigest(),
            filename,
        )


@dataclass(frozen=True)
class SkillEntry:
    filename: str
    definition: SkillDefinition | None = None
    error: str = ""


@dataclass(frozen=True)
class ToolDefinition:
    tool_id: str
    name: str
    description: str
    parameters: dict
    result: dict
    version: str = "1.0.0"
    timeout_seconds: int = 5
    scope: str = "Current investigation; prepared source snapshot; read only"


def object_schema(properties):
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


def mcp_input_schema(definition):
    if definition.tool_id == "list_investigations":
        return definition.parameters
    return {
        **definition.parameters,
        "properties": {
            **definition.parameters["properties"],
            "investigation_id": {
                "type": "string",
                "minLength": 1,
                "maxLength": 1000,
                "description": "An investigation explicitly authorized when the server started.",
            },
        },
        "required": [*definition.parameters["required"], "investigation_id"],
    }
