"""Stub package for agent_framework_orchestrations — for local testing only.

In production, the real Microsoft Agent Framework RC orchestrations package is installed.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any


class GroupChatState:
    """Stub GroupChatState class."""

    def __init__(self, current_round: int = 0, messages: list | None = None) -> None:
        self.current_round = current_round
        self.messages = messages or []


class GroupChatResponseReceivedEvent:
    """Event fired when a GroupChat participant completes a response."""

    def __init__(self, round_index: int, participant_name: str) -> None:
        self.round_index = round_index
        self.participant_name = participant_name


class GroupChatBuilder:
    """Stub GroupChatBuilder class."""

    def __init__(
        self,
        participants: list | None = None,
        selection_func: Callable | None = None,
        max_rounds: int = 9,
        intermediate_outputs: bool = False,
        **kwargs: Any,
    ) -> None:
        self.participants = participants or []
        self.selection_func = selection_func
        self.max_rounds = max_rounds
        self.intermediate_outputs = intermediate_outputs

    def build(self) -> "GroupChatWorkflow":
        return GroupChatWorkflow()


class GroupChatWorkflow:
    """Stub GroupChatWorkflow class."""

    def run(self, prompt: str, stream: bool = False) -> Any:
        return iter([])
