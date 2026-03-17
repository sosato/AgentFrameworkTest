"""Stub package for agent_framework — for local testing only.

In production, the real Microsoft Agent Framework RC package is installed.
"""

from __future__ import annotations

from typing import Any


class BaseChatClient:
    """Stub base class for chat clients."""
    pass


class Agent:
    """Stub Agent class."""

    def __init__(
        self,
        client: BaseChatClient | None = None,
        instructions: str = "",
        name: str = "",
        description: str = "",
        **kwargs: Any,
    ) -> None:
        self.client = client
        self.instructions = instructions
        self.name = name
        self.description = description

    async def run(self, prompt: str) -> "AgentResponse":
        return AgentResponse(text="stub response")


class AgentResponse:
    """Stub AgentResponse class."""

    def __init__(self, text: str = "") -> None:
        self.text = text


class Message:
    """Stub Message class."""

    def __init__(
        self,
        role: str = "user",
        text: str = "",
        author_name: str | None = None,
        **kwargs: Any,
    ) -> None:
        self.role = role
        self.text = text
        self.author_name = author_name
