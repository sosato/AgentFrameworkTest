"""tests for src/workflows/groupchat.py"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# src/ をインポートパスに追加
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from agent_framework import Message  # noqa: E402
from agent_framework_orchestrations import GroupChatResponseReceivedEvent  # noqa: E402

from workflows.groupchat import GroupChatResult, run_groupchat  # noqa: E402

# ---------------------------------------------------------------------------
# 固定スタブデータ（6 ラウンド分）
# ---------------------------------------------------------------------------

_STUB_ASSISTANT_MESSAGES = [
    ("AnalystAgent", "【アナリスト】初期評価スコア 7/10。環境対策は業界平均以上。"),
    ("CriticAgent", "【クリティック】反論評価スコア 5/10。データの信頼性に疑問。"),
    ("AnalystAgent", "【アナリスト】CO2 削減実績は第三者検証済み。"),
    ("CriticAgent", "【クリティック】Scope3 排出量の開示が不十分。"),
    ("AnalystAgent", "【アナリスト】総合 8/10 に上方修正。"),
    ("CriticAgent", "【クリティック】改善は認めつつ 6/10。課題は残る。"),
]


def _make_output_event(executor_id: str, text: str) -> MagicMock:
    """type='output' の WorkflowEvent モック（AgentResponseUpdate 相当）を生成する。"""
    event = MagicMock()
    event.type = "output"
    event.executor_id = executor_id
    event.data = MagicMock()
    event.data.text = text
    return event


def _make_group_chat_response_event(participant_name: str, round_index: int) -> MagicMock:
    """type='group_chat' の GroupChatResponseReceivedEvent モックを生成する。"""
    event = MagicMock()
    event.type = "group_chat"
    event.data = GroupChatResponseReceivedEvent(
        round_index=round_index,
        participant_name=participant_name,
    )
    return event


def _build_stream_events() -> list[MagicMock]:
    """6 ラウンド分のストリームイベント列を構築する。"""
    events: list[MagicMock] = []
    for i, (agent_name, text) in enumerate(_STUB_ASSISTANT_MESSAGES):
        events.append(_make_output_event(agent_name, text))
        events.append(_make_group_chat_response_event(agent_name, i))
    return events


class _MockStream:
    """workflow.run(topic, stream=True) が返す async iterable のモック。"""

    def __init__(self, events: list[MagicMock]) -> None:
        self._events = events

    def __aiter__(self):
        return self._iter_events()

    async def _iter_events(self):
        for event in self._events:
            yield event

    async def get_final_response(self):
        return self._events


def _make_mock_workflow() -> MagicMock:
    """ストリーミングモードのモックワークフローを生成する。"""
    events = _build_stream_events()
    stream = _MockStream(events)
    workflow = MagicMock()
    workflow.run = MagicMock(return_value=stream)
    return workflow


def _make_mock_workflow_fallback() -> MagicMock:
    """ストリーミングで group_chat イベントが無い場合（フォールバック用）のモックワークフロー。"""
    # output イベントのみ（group_chat イベントなし → フォールバックパスが動作する）
    # フォールバックでは get_final_response() の結果から抽出する
    final_output_event = MagicMock()
    final_output_event.type = "output"
    final_output_event.executor_id = "group_chat_orchestrator"
    messages = [
        Message(role="user", text="トヨタ自動車の ESG 評価"),
    ]
    for agent_name, text in _STUB_ASSISTANT_MESSAGES:
        messages.append(Message(role="assistant", text=text, author_name=agent_name))
    final_output_event.data = messages

    # ストリームでは group_chat イベントが来ない（オーケストレータの output のみ）
    stream_events: list[MagicMock] = [final_output_event]
    stream = _MockStream(stream_events)
    workflow = MagicMock()
    workflow.run = MagicMock(return_value=stream)
    return workflow


# ---------------------------------------------------------------------------
# テストケース
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@patch("workflows.groupchat.create_critic_agent")
@patch("workflows.groupchat.create_analyst_agent")
@patch("workflows.groupchat.GroupChatBuilder")
async def test_groupchat_returns_result(
    mock_builder_cls: MagicMock,
    mock_create_analyst: MagicMock,
    mock_create_critic: MagicMock,
) -> None:
    """正常終了で GroupChatResult が返ること。"""
    mock_create_analyst.return_value = MagicMock()
    mock_create_critic.return_value = MagicMock()
    mock_builder_cls.return_value.build.return_value = _make_mock_workflow()

    result = await run_groupchat(topic="テスト", max_rounds=6)

    assert isinstance(result, GroupChatResult)
    assert result.summary != ""


@pytest.mark.asyncio
@patch("workflows.groupchat.create_critic_agent")
@patch("workflows.groupchat.create_analyst_agent")
@patch("workflows.groupchat.GroupChatBuilder")
async def test_groupchat_message_count(
    mock_builder_cls: MagicMock,
    mock_create_analyst: MagicMock,
    mock_create_critic: MagicMock,
) -> None:
    """メッセージ数が max_rounds（= assistant 発言数）と一致すること。"""
    mock_create_analyst.return_value = MagicMock()
    mock_create_critic.return_value = MagicMock()
    mock_builder_cls.return_value.build.return_value = _make_mock_workflow()

    max_rounds = 6
    result = await run_groupchat(topic="テスト", max_rounds=max_rounds)

    assert len(result.messages) == max_rounds
    assert result.total_rounds == max_rounds


@pytest.mark.asyncio
@patch("workflows.groupchat.create_critic_agent")
@patch("workflows.groupchat.create_analyst_agent")
@patch("workflows.groupchat.GroupChatBuilder")
async def test_groupchat_agent_names(
    mock_builder_cls: MagicMock,
    mock_create_analyst: MagicMock,
    mock_create_critic: MagicMock,
) -> None:
    """AnalystAgent と CriticAgent の名前が含まれること。"""
    mock_create_analyst.return_value = MagicMock()
    mock_create_critic.return_value = MagicMock()
    mock_builder_cls.return_value.build.return_value = _make_mock_workflow()

    result = await run_groupchat(topic="テスト", max_rounds=6)

    agent_names = {msg.agent_name for msg in result.messages}
    assert "AnalystAgent" in agent_names
    assert "CriticAgent" in agent_names


@pytest.mark.asyncio
@patch("workflows.groupchat.create_critic_agent")
@patch("workflows.groupchat.create_analyst_agent")
@patch("workflows.groupchat.GroupChatBuilder")
async def test_groupchat_elapsed_time(
    mock_builder_cls: MagicMock,
    mock_create_analyst: MagicMock,
    mock_create_critic: MagicMock,
) -> None:
    """エラプスドタイムがゼロ以上であること。"""
    mock_create_analyst.return_value = MagicMock()
    mock_create_critic.return_value = MagicMock()
    mock_builder_cls.return_value.build.return_value = _make_mock_workflow()

    result = await run_groupchat(topic="テスト", max_rounds=6)

    assert result.elapsed_seconds >= 0


@pytest.mark.asyncio
@patch("workflows.groupchat.create_critic_agent")
@patch("workflows.groupchat.create_analyst_agent")
@patch("workflows.groupchat.GroupChatBuilder")
async def test_groupchat_fallback_extracts_from_final_response(
    mock_builder_cls: MagicMock,
    mock_create_analyst: MagicMock,
    mock_create_critic: MagicMock,
) -> None:
    """ストリーミングで group_chat イベントが無い場合、フォールバックからメッセージを抽出すること。"""
    mock_create_analyst.return_value = MagicMock()
    mock_create_critic.return_value = MagicMock()
    mock_builder_cls.return_value.build.return_value = (
        _make_mock_workflow_fallback()
    )

    result = await run_groupchat(topic="テスト", max_rounds=6)

    assert len(result.messages) == 6
    assert result.total_rounds == 6


@pytest.mark.asyncio
@patch("workflows.groupchat.create_critic_agent")
@patch("workflows.groupchat.create_analyst_agent")
@patch("workflows.groupchat.GroupChatBuilder")
async def test_groupchat_on_message_callback(
    mock_builder_cls: MagicMock,
    mock_create_analyst: MagicMock,
    mock_create_critic: MagicMock,
) -> None:
    """on_message コールバックが各発言ごとに呼ばれること。"""
    mock_create_analyst.return_value = MagicMock()
    mock_create_critic.return_value = MagicMock()
    mock_builder_cls.return_value.build.return_value = _make_mock_workflow()

    received: list = []
    result = await run_groupchat(
        topic="テスト", max_rounds=6, on_message=lambda msg: received.append(msg)
    )

    assert len(received) == 6
    assert received[0].agent_name == "AnalystAgent"
    assert received[1].agent_name == "CriticAgent"


@pytest.mark.asyncio
async def test_groupchat_rejects_non_positive_rounds() -> None:
    """max_rounds <= 0 は ValueError で拒否されること。"""
    with pytest.raises(ValueError, match="1 以上"):
        await run_groupchat(topic="テスト", max_rounds=0)
