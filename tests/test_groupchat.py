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

from workflows.groupchat import (  # noqa: E402
    AgentMessage,
    GroupChatResult,
    _DEFAULT_MAX_ROUNDS,
    _MAX_RETRIES,
    _MIN_ROUNDS,
    _RETRYABLE_EXCEPTIONS,
    _TURN_TIMEOUT_SECONDS,
    _extract_next_speaker,
    _make_dynamic_selection,
    run_groupchat,
)

# ---------------------------------------------------------------------------
# 固定スタブデータ（13 ラウンド分 — ファシリテーターが偶数ターン、討論者が奇数ターン）
# ---------------------------------------------------------------------------

_STUB_ASSISTANT_MESSAGES = [
    # idx 0 (even): Facilitator opens + directs CEO
    ("FacilitatorAgent", "【ファシリテーター】本日はトヨタ自動車の ESG 評価について討議します。CEO・アナリスト・クリティックの皆さん、よろしくお願いします。【次の発言者: CeoAgent】"),
    # idx 1 (odd): CEO
    ("CeoAgent", "【CEO】当社は 2050 年カーボンニュートラルを目標に、EV シフトと再生エネ調達を加速しています。"),
    # idx 2 (even): Facilitator intermediate + directs Analyst
    ("FacilitatorAgent", "【ファシリテーター】CEO の見解を伺いました。次にアナリストからの評価をお願いします。【次の発言者: AnalystAgent】"),
    # idx 3 (odd): Analyst
    ("AnalystAgent", "【アナリスト】初期評価スコア 7/10。環境対策は業界平均以上で方向性は評価できます。"),
    # idx 4 (even): Facilitator intermediate + directs Critic
    ("FacilitatorAgent", "【ファシリテーター】アナリストの評価を受け、クリティックからの反論をお願いします。【次の発言者: CriticAgent】"),
    # idx 5 (odd): Critic
    ("CriticAgent", "【クリティック】反論評価スコア 5/10。Scope3 排出量の開示が不十分で信頼性に疑問。"),
    # idx 6 (even): Facilitator intermediate + directs CEO
    ("FacilitatorAgent", "【ファシリテーター】クリティックの指摘を受け、CEOからの応答をお願いします。【次の発言者: CeoAgent】"),
    # idx 7 (odd): CEO
    ("CeoAgent", "【CEO】Scope3 については来期の報告書で詳細開示を予定しています。"),
    # idx 8 (even): Facilitator intermediate + directs Analyst
    ("FacilitatorAgent", "【ファシリテーター】CEO の応答を受けて、アナリストの評価を改めてお願いします。【次の発言者: AnalystAgent】"),
    # idx 9 (odd): Analyst
    ("AnalystAgent", "【アナリスト】CO2 削減実績は第三者検証済み。開示改善を前提に 8/10 に上方修正。"),
    # idx 10 (even): Facilitator intermediate + directs Critic
    ("FacilitatorAgent", "【ファシリテーター】アナリストの評価が変わりました。クリティックの最終見解をお願いします。【次の発言者: CriticAgent】"),
    # idx 11 (odd): Critic
    ("CriticAgent", "【クリティック】改善姿勢は認めつつ 6/10。サプライチェーン全体の取り組みが課題。"),
    # idx 12 (even, last): Facilitator closes
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
    """13 ラウンド分のストリームイベント列を構築する。"""
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

    result = await run_groupchat(topic="テスト", max_rounds=_DEFAULT_MAX_ROUNDS)

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

    max_rounds = _DEFAULT_MAX_ROUNDS
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

    result = await run_groupchat(topic="テスト", max_rounds=_DEFAULT_MAX_ROUNDS)

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

    result = await run_groupchat(topic="テスト", max_rounds=_DEFAULT_MAX_ROUNDS)

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

    result = await run_groupchat(topic="テスト", max_rounds=_DEFAULT_MAX_ROUNDS)

    assert len(result.messages) == _DEFAULT_MAX_ROUNDS
    assert result.total_rounds == _DEFAULT_MAX_ROUNDS


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
        topic="テスト", max_rounds=_DEFAULT_MAX_ROUNDS, on_message=lambda msg: received.append(msg)
    )

    assert len(received) == _DEFAULT_MAX_ROUNDS
    # 新しいパターン: ファシリテーターが偶数ラウンド、討論者が奇数ラウンド
    assert received[0].agent_name == "FacilitatorAgent"
    assert received[1].agent_name == "CeoAgent"
    assert received[2].agent_name == "FacilitatorAgent"
    assert received[3].agent_name == "AnalystAgent"


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

    result = await run_groupchat(topic="テスト", max_rounds=_DEFAULT_MAX_ROUNDS)

    assert result.summary.startswith("【ファシリテーター】")


@pytest.mark.asyncio
async def test_groupchat_rejects_below_min_rounds() -> None:
    """max_rounds < _MIN_ROUNDS は ValueError で拒否されること。"""
    with pytest.raises(ValueError, match=f"{_MIN_ROUNDS} 以上"):
        await run_groupchat(topic="テスト", max_rounds=_MIN_ROUNDS - 1)


@pytest.mark.asyncio
async def test_groupchat_rejects_non_positive_rounds() -> None:
    """max_rounds <= 0 は ValueError で拒否されること。"""
    with pytest.raises(ValueError, match=f"{_MIN_ROUNDS} 以上"):
        await run_groupchat(topic="テスト", max_rounds=0)


@pytest.mark.asyncio
@patch("workflows.groupchat.create_critic_agent")
@patch("workflows.groupchat.create_analyst_agent")
@patch("workflows.groupchat.create_ceo_agent")
@patch("workflows.groupchat.create_facilitator_agent")
@patch("workflows.groupchat.GroupChatBuilder")
async def test_groupchat_accepts_min_rounds(
    mock_builder_cls: MagicMock,
    mock_create_facilitator: MagicMock,
    mock_create_ceo: MagicMock,
    mock_create_analyst: MagicMock,
    mock_create_critic: MagicMock,
) -> None:
    """max_rounds == _MIN_ROUNDS は正常に受け付けられること。"""
    min_messages = [
        ("FacilitatorAgent", "【ファシリテーター】討議を開始します。【次の発言者: CeoAgent】"),
        ("CeoAgent", "【CEO】ESG 施策について説明します。"),
        ("FacilitatorAgent", "【ファシリテーター】ありがとうございます。【次の発言者: AnalystAgent】"),
        ("AnalystAgent", "【アナリスト】評価スコア 7/10。"),
        ("FacilitatorAgent", "【ファシリテーター】討議を終了します。"),
    ]
    events: list[MagicMock] = []
    for i, (agent_name, text) in enumerate(min_messages):
        events.append(_make_output_event(agent_name, text))
        events.append(_make_group_chat_response_event(agent_name, i))
    stream = _MockStream(events)
    mock_workflow = MagicMock()
    mock_workflow.run = MagicMock(return_value=stream)

    mock_create_facilitator.return_value = MagicMock()
    mock_create_ceo.return_value = MagicMock()
    mock_create_analyst.return_value = MagicMock()
    mock_create_critic.return_value = MagicMock()
    mock_builder_cls.return_value.build.return_value = mock_workflow

    result = await run_groupchat(topic="テスト", max_rounds=_MIN_ROUNDS)

    assert isinstance(result, GroupChatResult)
    assert result.total_rounds == _MIN_ROUNDS


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
    # FacilitatorAgent を含まない 5 メッセージのみのストリームを作成（_MIN_ROUNDS = 5）
    non_facilitator_messages = [
        ("CeoAgent", "【CEO】ESG 取り組みを積極推進中。"),
        ("AnalystAgent", "【アナリスト】評価スコア 7/10。"),
        ("CriticAgent", "【クリティック】課題が残る 5/10。"),
        ("CeoAgent", "【CEO】来期の取り組み詳細を説明します。"),
        ("AnalystAgent", "【アナリスト】評価スコア 8/10 に上方修正。"),
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

    result = await run_groupchat(topic="テスト", max_rounds=_MIN_ROUNDS)

    # FacilitatorAgent がいないので最終メッセージがサマリーになること
    assert result.summary == non_facilitator_messages[-1][1]


# ---------------------------------------------------------------------------
# 動的発言者選択ユニットテスト
# ---------------------------------------------------------------------------


def test_extract_next_speaker_returns_correct_agent() -> None:
    """【次の発言者: XXXAgent】ディレクティブから正しいエージェント名を抽出できること。"""
    assert _extract_next_speaker("内容です。【次の発言者: CeoAgent】") == "CeoAgent"
    assert _extract_next_speaker("内容です。【次の発言者: AnalystAgent】") == "AnalystAgent"
    assert _extract_next_speaker("内容です。【次の発言者: CriticAgent】") == "CriticAgent"


def test_extract_next_speaker_returns_none_when_no_directive() -> None:
    """ディレクティブがない場合 None を返すこと。"""
    assert _extract_next_speaker("ファシリテーターの通常の発言。") is None
    assert _extract_next_speaker("") is None


def test_dynamic_selection_facilitator_on_even_rounds() -> None:
    """偶数ラウンドはファシリテーターが選択されること。"""
    history: list[AgentMessage] = []
    select = _make_dynamic_selection(max_rounds=13, message_history=history)

    for round_idx in [0, 2, 4, 6, 8, 10, 12]:
        state = MagicMock()
        state.current_round = round_idx
        assert select(state) == "FacilitatorAgent", f"round_idx={round_idx} should be FacilitatorAgent"


def test_dynamic_selection_fallback_round_robin_on_odd_rounds() -> None:
    """ディレクティブがない場合、奇数ラウンドはラウンドロビンフォールバックが動作すること。"""
    history: list[AgentMessage] = []
    select = _make_dynamic_selection(max_rounds=13, message_history=history)

    # フォールバック: debater_turn = (round_idx - 1) // 2
    # round 1: debater_turn=0 → CeoAgent
    # round 3: debater_turn=1 → AnalystAgent
    # round 5: debater_turn=2 → CriticAgent
    # round 7: debater_turn=3 → CeoAgent (循環)
    expected = {1: "CeoAgent", 3: "AnalystAgent", 5: "CriticAgent", 7: "CeoAgent"}
    for round_idx, expected_agent in expected.items():
        state = MagicMock()
        state.current_round = round_idx
        assert select(state) == expected_agent, f"round_idx={round_idx} should be {expected_agent}"


def test_dynamic_selection_uses_directive_from_message_history() -> None:
    """message_history にファシリテーターのディレクティブがある場合、それに従って討論者を選択すること。"""
    history: list[AgentMessage] = [
        AgentMessage(
            agent_name="FacilitatorAgent",
            content="CEOの見解を受けて、アナリストにお願いします。【次の発言者: AnalystAgent】",
            round_num=1,
        )
    ]
    select = _make_dynamic_selection(max_rounds=13, message_history=history)

    state = MagicMock()
    state.current_round = 3  # 奇数ラウンド → 討論者が発言
    assert select(state) == "AnalystAgent"


def test_dynamic_selection_uses_directive_from_state_messages() -> None:
    """GroupChatState.messages にファシリテーターのディレクティブがある場合、それに従って討論者を選択すること。"""
    history: list[AgentMessage] = []
    select = _make_dynamic_selection(max_rounds=13, message_history=history)

    # state.messages にファシリテーターの発言を含める
    mock_state_msg = MagicMock()
    mock_state_msg.agent_name = "FacilitatorAgent"
    mock_state_msg.content = "クリティックにお願いします。【次の発言者: CriticAgent】"

    state = MagicMock()
    state.current_round = 5
    state.messages = [mock_state_msg]

    assert select(state) == "CriticAgent"


def test_dynamic_selection_last_round_always_facilitator() -> None:
    """最終ラウンドは常にファシリテーターが選択されること。"""
    history: list[AgentMessage] = [
        AgentMessage(
            agent_name="FacilitatorAgent",
            content="【次の発言者: CeoAgent】",
            round_num=1,
        )
    ]
    select = _make_dynamic_selection(max_rounds=13, message_history=history)

    state = MagicMock()
    state.current_round = 12  # max_rounds - 1 = 12
    assert select(state) == "FacilitatorAgent"


# ---------------------------------------------------------------------------
# タイムアウト値・リトライ設定のテスト
# ---------------------------------------------------------------------------


def test_turn_timeout_is_adequate_for_ai_agents() -> None:
    """ターンタイムアウトが AI エージェント接続に適した値（120秒以上）であること。"""
    assert _TURN_TIMEOUT_SECONDS >= 120


def test_max_retries_is_positive() -> None:
    """最大リトライ回数が正の整数であること。"""
    assert _MAX_RETRIES >= 1


def test_retryable_exceptions_includes_connection_errors() -> None:
    """リトライ対象に ConnectionError, TimeoutError, OSError が含まれること。"""
    assert ConnectionError in _RETRYABLE_EXCEPTIONS
    assert TimeoutError in _RETRYABLE_EXCEPTIONS
    assert OSError in _RETRYABLE_EXCEPTIONS


# ---------------------------------------------------------------------------
# リトライロジックのテスト
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@patch("workflows.groupchat.create_critic_agent")
@patch("workflows.groupchat.create_analyst_agent")
@patch("workflows.groupchat.create_ceo_agent")
@patch("workflows.groupchat.create_facilitator_agent")
@patch("workflows.groupchat.GroupChatBuilder")
async def test_groupchat_retries_on_connection_error(
    mock_builder_cls: MagicMock,
    mock_create_facilitator: MagicMock,
    mock_create_ceo: MagicMock,
    mock_create_analyst: MagicMock,
    mock_create_critic: MagicMock,
) -> None:
    """ConnectionError 発生時にリトライし、成功すれば結果を返すこと。"""
    mock_create_facilitator.return_value = MagicMock()
    mock_create_ceo.return_value = MagicMock()
    mock_create_analyst.return_value = MagicMock()
    mock_create_critic.return_value = MagicMock()

    # 1 回目は ConnectionError、2 回目は正常動作
    fail_workflow = MagicMock()
    fail_workflow.run = MagicMock(side_effect=ConnectionError("接続が切断されました"))
    success_workflow = _make_mock_workflow()

    mock_builder_cls.return_value.build.side_effect = [fail_workflow, success_workflow]

    with patch("workflows.groupchat.asyncio.sleep", new_callable=AsyncMock):
        result = await run_groupchat(topic="テスト", max_rounds=_DEFAULT_MAX_ROUNDS)

    assert isinstance(result, GroupChatResult)
    assert result.summary != ""


@pytest.mark.asyncio
@patch("workflows.groupchat.create_critic_agent")
@patch("workflows.groupchat.create_analyst_agent")
@patch("workflows.groupchat.create_ceo_agent")
@patch("workflows.groupchat.create_facilitator_agent")
@patch("workflows.groupchat.GroupChatBuilder")
async def test_groupchat_retries_on_timeout_error(
    mock_builder_cls: MagicMock,
    mock_create_facilitator: MagicMock,
    mock_create_ceo: MagicMock,
    mock_create_analyst: MagicMock,
    mock_create_critic: MagicMock,
) -> None:
    """TimeoutError 発生時にリトライし、成功すれば結果を返すこと。"""
    mock_create_facilitator.return_value = MagicMock()
    mock_create_ceo.return_value = MagicMock()
    mock_create_analyst.return_value = MagicMock()
    mock_create_critic.return_value = MagicMock()

    fail_workflow = MagicMock()
    fail_workflow.run = MagicMock(side_effect=TimeoutError("応答タイムアウト"))
    success_workflow = _make_mock_workflow()

    mock_builder_cls.return_value.build.side_effect = [fail_workflow, success_workflow]

    with patch("workflows.groupchat.asyncio.sleep", new_callable=AsyncMock):
        result = await run_groupchat(topic="テスト", max_rounds=_DEFAULT_MAX_ROUNDS)

    assert isinstance(result, GroupChatResult)
    assert result.summary != ""


@pytest.mark.asyncio
@patch("workflows.groupchat.create_critic_agent")
@patch("workflows.groupchat.create_analyst_agent")
@patch("workflows.groupchat.create_ceo_agent")
@patch("workflows.groupchat.create_facilitator_agent")
@patch("workflows.groupchat.GroupChatBuilder")
async def test_groupchat_raises_after_max_retries_timeout(
    mock_builder_cls: MagicMock,
    mock_create_facilitator: MagicMock,
    mock_create_ceo: MagicMock,
    mock_create_analyst: MagicMock,
    mock_create_critic: MagicMock,
) -> None:
    """TimeoutError が最大リトライ回数を超えた場合、詳細なエラーメッセージで RuntimeError を送出すること。"""
    mock_create_facilitator.return_value = MagicMock()
    mock_create_ceo.return_value = MagicMock()
    mock_create_analyst.return_value = MagicMock()
    mock_create_critic.return_value = MagicMock()

    fail_workflow = MagicMock()
    fail_workflow.run = MagicMock(side_effect=TimeoutError("応答タイムアウト"))
    mock_builder_cls.return_value.build.return_value = fail_workflow

    with patch("workflows.groupchat.asyncio.sleep", new_callable=AsyncMock):
        with pytest.raises(RuntimeError, match="タイムアウト") as exc_info:
            await run_groupchat(topic="テスト", max_rounds=_DEFAULT_MAX_ROUNDS)

    error_msg = str(exc_info.value)
    assert "リトライ済み" in error_msg
    assert "TimeoutError" in error_msg


@pytest.mark.asyncio
@patch("workflows.groupchat.create_critic_agent")
@patch("workflows.groupchat.create_analyst_agent")
@patch("workflows.groupchat.create_ceo_agent")
@patch("workflows.groupchat.create_facilitator_agent")
@patch("workflows.groupchat.GroupChatBuilder")
async def test_groupchat_raises_after_max_retries_connection(
    mock_builder_cls: MagicMock,
    mock_create_facilitator: MagicMock,
    mock_create_ceo: MagicMock,
    mock_create_analyst: MagicMock,
    mock_create_critic: MagicMock,
) -> None:
    """ConnectionError が最大リトライ回数を超えた場合、詳細なエラーメッセージで RuntimeError を送出すること。"""
    mock_create_facilitator.return_value = MagicMock()
    mock_create_ceo.return_value = MagicMock()
    mock_create_analyst.return_value = MagicMock()
    mock_create_critic.return_value = MagicMock()

    fail_workflow = MagicMock()
    fail_workflow.run = MagicMock(side_effect=ConnectionError("サーバーに接続できません"))
    mock_builder_cls.return_value.build.return_value = fail_workflow

    with patch("workflows.groupchat.asyncio.sleep", new_callable=AsyncMock):
        with pytest.raises(RuntimeError, match="通信エラー") as exc_info:
            await run_groupchat(topic="テスト", max_rounds=_DEFAULT_MAX_ROUNDS)

    error_msg = str(exc_info.value)
    assert "リトライ済み" in error_msg
    assert "ConnectionError" in error_msg


@pytest.mark.asyncio
@patch("workflows.groupchat.create_critic_agent")
@patch("workflows.groupchat.create_analyst_agent")
@patch("workflows.groupchat.create_ceo_agent")
@patch("workflows.groupchat.create_facilitator_agent")
@patch("workflows.groupchat.GroupChatBuilder")
async def test_groupchat_no_retry_on_non_retryable_error(
    mock_builder_cls: MagicMock,
    mock_create_facilitator: MagicMock,
    mock_create_ceo: MagicMock,
    mock_create_analyst: MagicMock,
    mock_create_critic: MagicMock,
) -> None:
    """リトライ対象外の例外（例: ValueError）はリトライせず即座に RuntimeError を送出すること。"""
    mock_create_facilitator.return_value = MagicMock()
    mock_create_ceo.return_value = MagicMock()
    mock_create_analyst.return_value = MagicMock()
    mock_create_critic.return_value = MagicMock()

    fail_workflow = MagicMock()
    fail_workflow.run = MagicMock(side_effect=ValueError("不正な入力"))
    mock_builder_cls.return_value.build.return_value = fail_workflow

    with pytest.raises(RuntimeError, match="エラーが発生しました") as exc_info:
        await run_groupchat(topic="テスト", max_rounds=_DEFAULT_MAX_ROUNDS)

    error_msg = str(exc_info.value)
    assert "ValueError" in error_msg


@pytest.mark.asyncio
@patch("workflows.groupchat.create_critic_agent")
@patch("workflows.groupchat.create_analyst_agent")
@patch("workflows.groupchat.create_ceo_agent")
@patch("workflows.groupchat.create_facilitator_agent")
@patch("workflows.groupchat.GroupChatBuilder")
async def test_groupchat_error_message_includes_exception_type(
    mock_builder_cls: MagicMock,
    mock_create_facilitator: MagicMock,
    mock_create_ceo: MagicMock,
    mock_create_analyst: MagicMock,
    mock_create_critic: MagicMock,
) -> None:
    """エラーメッセージに例外クラス名が含まれること。"""
    mock_create_facilitator.return_value = MagicMock()
    mock_create_ceo.return_value = MagicMock()
    mock_create_analyst.return_value = MagicMock()
    mock_create_critic.return_value = MagicMock()

    fail_workflow = MagicMock()
    fail_workflow.run = MagicMock(side_effect=RuntimeError("内部エラー"))
    mock_builder_cls.return_value.build.return_value = fail_workflow

    with pytest.raises(RuntimeError, match=r"\[RuntimeError\]"):
        await run_groupchat(topic="テスト", max_rounds=_DEFAULT_MAX_ROUNDS)

