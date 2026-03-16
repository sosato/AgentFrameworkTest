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
# 固定スタブデータ（9 ラウンド分）
# ---------------------------------------------------------------------------

_STUB_ASSISTANT_MESSAGES = [
    ("FacilitatorAgent", "【ファシリテーター】本日はトヨタ自動車の ESG 評価について討議します。CEO・アナリスト・クリティックの皆さん、よろしくお願いします。"),
    ("CeoAgent", "【CEO】当社は 2050 年カーボンニュートラルを目標に、EV シフトと再生エネ調達を加速しています。"),
    ("AnalystAgent", "【アナリスト】初期評価スコア 7/10。環境対策は業界平均以上で方向性は評価できます。"),
    ("CriticAgent", "【クリティック】反論評価スコア 5/10。Scope3 排出量の開示が不十分で信頼性に疑問。"),
    ("CeoAgent", "【CEO】Scope3 については来期の報告書で詳細開示を予定しています。"),
    ("AnalystAgent", "【アナリスト】CO2 削減実績は第三者検証済み。開示改善を前提に 8/10 に上方修正。"),
    ("CriticAgent", "【クリティック】改善姿勢は認めつつ 6/10。サプライチェーン全体の取り組みが課題。"),
    ("CeoAgent", "【CEO】サプライヤーへの ESG 要求基準を強化し、2026 年までに全取引先に展開予定です。"),
    ("FacilitatorAgent", "【ファシリテーター】討議を終了します。CEO は具体的施策を提示、アナリスト・クリティックは開示充実と SC 対応を課題として指摘しました。"),
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
    """9 ラウンド分のストリームイベント列を構築する。"""
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
@patch("workflows.groupchat.create_ceo_agent")
@patch("workflows.groupchat.create_facilitator_agent")
@patch("workflows.groupchat.GroupChatBuilder")
async def test_groupchat_returns_result(
    mock_builder_cls: MagicMock,
    mock_create_facilitator: MagicMock,
    mock_create_ceo: MagicMock,
    mock_create_analyst: MagicMock,
    mock_create_critic: MagicMock,
) -> None:
    """正常終了で GroupChatResult が返ること。"""
    mock_create_facilitator.return_value = MagicMock()
    mock_create_ceo.return_value = MagicMock()
    mock_create_analyst.return_value = MagicMock()
    mock_create_critic.return_value = MagicMock()
    mock_builder_cls.return_value.build.return_value = _make_mock_workflow()

    result = await run_groupchat(topic="テスト", max_rounds=9)

    assert isinstance(result, GroupChatResult)
    assert result.summary != ""


@pytest.mark.asyncio
@patch("workflows.groupchat.create_critic_agent")
@patch("workflows.groupchat.create_analyst_agent")
@patch("workflows.groupchat.create_ceo_agent")
@patch("workflows.groupchat.create_facilitator_agent")
@patch("workflows.groupchat.GroupChatBuilder")
async def test_groupchat_message_count(
    mock_builder_cls: MagicMock,
    mock_create_facilitator: MagicMock,
    mock_create_ceo: MagicMock,
    mock_create_analyst: MagicMock,
    mock_create_critic: MagicMock,
) -> None:
    """メッセージ数が max_rounds（= assistant 発言数）と一致すること。"""
    mock_create_facilitator.return_value = MagicMock()
    mock_create_ceo.return_value = MagicMock()
    mock_create_analyst.return_value = MagicMock()
    mock_create_critic.return_value = MagicMock()
    mock_builder_cls.return_value.build.return_value = _make_mock_workflow()

    max_rounds = 9
    result = await run_groupchat(topic="テスト", max_rounds=max_rounds)

    assert len(result.messages) == max_rounds
    assert result.total_rounds == max_rounds


@pytest.mark.asyncio
@patch("workflows.groupchat.create_critic_agent")
@patch("workflows.groupchat.create_analyst_agent")
@patch("workflows.groupchat.create_ceo_agent")
@patch("workflows.groupchat.create_facilitator_agent")
@patch("workflows.groupchat.GroupChatBuilder")
async def test_groupchat_agent_names(
    mock_builder_cls: MagicMock,
    mock_create_facilitator: MagicMock,
    mock_create_ceo: MagicMock,
    mock_create_analyst: MagicMock,
    mock_create_critic: MagicMock,
) -> None:
    """全 4 エージェントの名前が含まれること。"""
    mock_create_facilitator.return_value = MagicMock()
    mock_create_ceo.return_value = MagicMock()
    mock_create_analyst.return_value = MagicMock()
    mock_create_critic.return_value = MagicMock()
    mock_builder_cls.return_value.build.return_value = _make_mock_workflow()

    result = await run_groupchat(topic="テスト", max_rounds=9)

    agent_names = {msg.agent_name for msg in result.messages}
    assert "FacilitatorAgent" in agent_names
    assert "CeoAgent" in agent_names
    assert "AnalystAgent" in agent_names
    assert "CriticAgent" in agent_names


@pytest.mark.asyncio
@patch("workflows.groupchat.create_critic_agent")
@patch("workflows.groupchat.create_analyst_agent")
@patch("workflows.groupchat.create_ceo_agent")
@patch("workflows.groupchat.create_facilitator_agent")
@patch("workflows.groupchat.GroupChatBuilder")
async def test_groupchat_elapsed_time(
    mock_builder_cls: MagicMock,
    mock_create_facilitator: MagicMock,
    mock_create_ceo: MagicMock,
    mock_create_analyst: MagicMock,
    mock_create_critic: MagicMock,
) -> None:
    """エラプスドタイムがゼロ以上であること。"""
    mock_create_facilitator.return_value = MagicMock()
    mock_create_ceo.return_value = MagicMock()
    mock_create_analyst.return_value = MagicMock()
    mock_create_critic.return_value = MagicMock()
    mock_builder_cls.return_value.build.return_value = _make_mock_workflow()

    result = await run_groupchat(topic="テスト", max_rounds=9)

    assert result.elapsed_seconds >= 0


@pytest.mark.asyncio
@patch("workflows.groupchat.create_critic_agent")
@patch("workflows.groupchat.create_analyst_agent")
@patch("workflows.groupchat.create_ceo_agent")
@patch("workflows.groupchat.create_facilitator_agent")
@patch("workflows.groupchat.GroupChatBuilder")
async def test_groupchat_fallback_extracts_from_final_response(
    mock_builder_cls: MagicMock,
    mock_create_facilitator: MagicMock,
    mock_create_ceo: MagicMock,
    mock_create_analyst: MagicMock,
    mock_create_critic: MagicMock,
) -> None:
    """ストリーミングで group_chat イベントが無い場合、フォールバックからメッセージを抽出すること。"""
    mock_create_facilitator.return_value = MagicMock()
    mock_create_ceo.return_value = MagicMock()
    mock_create_analyst.return_value = MagicMock()
    mock_create_critic.return_value = MagicMock()
    mock_builder_cls.return_value.build.return_value = (
        _make_mock_workflow_fallback()
    )

    result = await run_groupchat(topic="テスト", max_rounds=9)

    assert len(result.messages) == 9
    assert result.total_rounds == 9


@pytest.mark.asyncio
@patch("workflows.groupchat.create_critic_agent")
@patch("workflows.groupchat.create_analyst_agent")
@patch("workflows.groupchat.create_ceo_agent")
@patch("workflows.groupchat.create_facilitator_agent")
@patch("workflows.groupchat.GroupChatBuilder")
async def test_groupchat_on_message_callback(
    mock_builder_cls: MagicMock,
    mock_create_facilitator: MagicMock,
    mock_create_ceo: MagicMock,
    mock_create_analyst: MagicMock,
    mock_create_critic: MagicMock,
) -> None:
    """on_message コールバックが各発言ごとに呼ばれること。"""
    mock_create_facilitator.return_value = MagicMock()
    mock_create_ceo.return_value = MagicMock()
    mock_create_analyst.return_value = MagicMock()
    mock_create_critic.return_value = MagicMock()
    mock_builder_cls.return_value.build.return_value = _make_mock_workflow()

    received: list = []
    result = await run_groupchat(
        topic="テスト", max_rounds=9, on_message=lambda msg: received.append(msg)
    )

    assert len(received) == 9
    assert received[0].agent_name == "FacilitatorAgent"
    assert received[1].agent_name == "CeoAgent"
    assert received[2].agent_name == "AnalystAgent"
    assert received[3].agent_name == "CriticAgent"


@pytest.mark.asyncio
@patch("workflows.groupchat.create_critic_agent")
@patch("workflows.groupchat.create_analyst_agent")
@patch("workflows.groupchat.create_ceo_agent")
@patch("workflows.groupchat.create_facilitator_agent")
@patch("workflows.groupchat.GroupChatBuilder")
async def test_groupchat_summary_from_facilitator(
    mock_builder_cls: MagicMock,
    mock_create_facilitator: MagicMock,
    mock_create_ceo: MagicMock,
    mock_create_analyst: MagicMock,
    mock_create_critic: MagicMock,
) -> None:
    """サマリーが FacilitatorAgent の最終発言から取得されること。"""
    mock_create_facilitator.return_value = MagicMock()
    mock_create_ceo.return_value = MagicMock()
    mock_create_analyst.return_value = MagicMock()
    mock_create_critic.return_value = MagicMock()
    mock_builder_cls.return_value.build.return_value = _make_mock_workflow()

    result = await run_groupchat(topic="テスト", max_rounds=9)

    assert result.summary.startswith("【ファシリテーター】")


@pytest.mark.asyncio
async def test_groupchat_rejects_non_positive_rounds() -> None:
    """max_rounds <= 0 は ValueError で拒否されること。"""
    with pytest.raises(ValueError, match="1 以上"):
        await run_groupchat(topic="テスト", max_rounds=0)


@pytest.mark.asyncio
@patch("workflows.groupchat.create_critic_agent")
@patch("workflows.groupchat.create_analyst_agent")
@patch("workflows.groupchat.create_ceo_agent")
@patch("workflows.groupchat.create_facilitator_agent")
@patch("workflows.groupchat.GroupChatBuilder")
async def test_groupchat_summary_fallback_without_facilitator(
    mock_builder_cls: MagicMock,
    mock_create_facilitator: MagicMock,
    mock_create_ceo: MagicMock,
    mock_create_analyst: MagicMock,
    mock_create_critic: MagicMock,
) -> None:
    """FacilitatorAgent の発言がない場合、最終発言がサマリーに使われること。"""
    # FacilitatorAgent を含まない 3 メッセージのみのストリームを作成
    non_facilitator_messages = [
        ("CeoAgent", "【CEO】ESG 取り組みを積極推進中。"),
        ("AnalystAgent", "【アナリスト】評価スコア 7/10。"),
        ("CriticAgent", "【クリティック】課題が残る 5/10。"),
    ]
    events: list[MagicMock] = []
    for i, (agent_name, text) in enumerate(non_facilitator_messages):
        events.append(_make_output_event(agent_name, text))
        events.append(_make_group_chat_response_event(agent_name, i))
    stream = _MockStream(events)
    workflow = MagicMock()
    workflow.run = MagicMock(return_value=stream)

    mock_create_facilitator.return_value = MagicMock()
    mock_create_ceo.return_value = MagicMock()
    mock_create_analyst.return_value = MagicMock()
    mock_create_critic.return_value = MagicMock()
    mock_builder_cls.return_value.build.return_value = workflow

    result = await run_groupchat(topic="テスト", max_rounds=3)

    # FacilitatorAgent がいないので最終メッセージがサマリーになること
    assert result.summary == non_facilitator_messages[-1][1]

