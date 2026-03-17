"""GroupChat ワークフロー — FacilitatorAgent が議長を務め、CeoAgent / AnalystAgent /
CriticAgent の 3 エージェントが討議する。"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable

from pydantic import BaseModel

logger = logging.getLogger(__name__)

from agent_framework_orchestrations import (
    GroupChatBuilder,
    GroupChatResponseReceivedEvent,
    GroupChatState,
)

from agents.analyst_agent import create_analyst_agent
from agents.ceo_agent import create_ceo_agent
from agents.critic_agent import create_critic_agent
from agents.facilitator_agent import create_facilitator_agent


# ---------------------------------------------------------------------------
# 結果モデル
# ---------------------------------------------------------------------------

class AgentMessage(BaseModel):
    """1 発言を表すモデル。"""

    agent_name: str
    content: str
    round_num: int


class GroupChatResult(BaseModel):
    """GroupChat 実行結果。"""

    messages: list[AgentMessage]
    total_rounds: int
    elapsed_seconds: float
    summary: str


# ---------------------------------------------------------------------------
# ファシリテーター制御の選択関数（動的発言者割り当て）
# ---------------------------------------------------------------------------

_FACILITATOR = "FacilitatorAgent"
_DEBATERS = ["CeoAgent", "AnalystAgent", "CriticAgent"]
_ALL_PARTICIPANTS = [_FACILITATOR] + _DEBATERS
_TURN_TIMEOUT_SECONDS = 120

# ファシリテーターが次の発言者を指定するタグのプレフィックス
# 例: 【次の発言者: CeoAgent】
_NEXT_SPEAKER_TAG = "【次の発言者:"

# ラウンド数の制約
_MIN_ROUNDS = 5
_DEFAULT_MAX_ROUNDS = 13

# リトライ設定
_MAX_RETRIES = 3
_RETRY_BASE_DELAY_SECONDS = 2.0

# リトライ対象の例外型
_RETRYABLE_EXCEPTIONS = (ConnectionError, TimeoutError, OSError)


def _extract_next_speaker(content: str) -> str | None:
    """ファシリテーターの発言から次の発言者ディレクティブを抽出する。

    Args:
        content: ファシリテーターの発言テキスト

    Returns:
        発言者エージェント名（_DEBATERS に含まれる場合）、見つからなければ None
    """
    for debater in _DEBATERS:
        if f"{_NEXT_SPEAKER_TAG} {debater}】" in content:
            return debater
    return None


def _make_dynamic_selection(
    max_rounds: int,
    message_history: list[AgentMessage],
) -> Callable[[GroupChatState], str]:
    """ファシリテーターが各討論者の発言後にコメントし、次の発言者を動的に選択する選択関数を生成する。

    ターン構造：
    - Round 0（偶数）: FacilitatorAgent（討議開始・テーマ紹介 + 最初の発言者指定）
    - Round 1, 3, 5, ...（奇数）: 討論者（ファシリテーターのディレクティブで動的に選択）
    - Round 2, 4, 6, ...（偶数・中間）: FacilitatorAgent（コメント + 次の発言者指定）
    - Round max_rounds-1（最終ターン・偶数）: FacilitatorAgent（討議終了・サマリー）

    動的選択ロジック：
    1. GroupChatState.messages（利用可能な場合）またはローカルの message_history から
       ファシリテーターの最新発言を取得する
    2. 発言中の「【次の発言者: XXXAgent】」ディレクティブを解析して次の発言者を決定する
    3. ディレクティブが見つからない場合はラウンドインデックスに基づくラウンドロビンにフォールバックする

    Args:
        max_rounds: 最大ラウンド数
        message_history: 蓄積された AgentMessage のリスト（run_groupchat と共有する参照）

    Returns:
        GroupChatState を受け取り、次の発言者名を返す選択関数
    """
    def _select(state: GroupChatState) -> str:
        round_idx = state.current_round

        # 最初と最後のラウンドはファシリテーター
        if round_idx == 0 or round_idx == max_rounds - 1:
            return _FACILITATOR

        # 偶数ラウンド（中間）: ファシリテーターがコメントし次の発言者を指定
        if round_idx % 2 == 0:
            return _FACILITATOR

        # 奇数ラウンド: ファシリテーターのディレクティブから次の討論者を動的に選択
        # GroupChatState.messages が利用可能な場合はそちらを優先して参照
        state_messages = getattr(state, "messages", None) or []

        for msg in reversed(list(state_messages)):
            name = getattr(msg, "agent_name", None) or getattr(msg, "author_name", None)
            content = getattr(msg, "content", None) or getattr(msg, "text", "") or ""
            if name == _FACILITATOR:
                speaker = _extract_next_speaker(content)
                if speaker:
                    return speaker

        # ローカルの message_history（run_groupchat と共有）からファシリテーターの最新発言を参照
        for msg in reversed(message_history):
            if msg.agent_name == _FACILITATOR:
                speaker = _extract_next_speaker(msg.content)
                if speaker:
                    return speaker

        # フォールバック: ラウンドインデックスに基づくラウンドロビン
        # 奇数ラウンド 1,3,5,7,... に対して debater_turn は 0,1,2,3,... となり
        # _DEBATERS リストをインデックスでサイクルする（0→CEO, 1→Analyst, 2→Critic, 3→CEO...）
        debater_turn = (round_idx - 1) // 2
        return _DEBATERS[debater_turn % len(_DEBATERS)]

    return _select


# ---------------------------------------------------------------------------
# コールバック型
# ---------------------------------------------------------------------------

OnAgentMessage = Callable[[AgentMessage], None]
"""エージェント発言時に呼ばれるコールバック。"""


# ---------------------------------------------------------------------------
# メインワークフロー
# ---------------------------------------------------------------------------

async def run_groupchat(
    topic: str,
    max_rounds: int = _DEFAULT_MAX_ROUNDS,
    on_message: OnAgentMessage | None = None,
) -> GroupChatResult:
    """GroupChat を実行し、結果を返す。

    通信不安定やタイムアウト等の一時的なエラーに対しては指数バックオフで
    最大 ``_MAX_RETRIES`` 回までリトライする。

    Args:
        topic: 討議テーマ（文字列）
        max_rounds: 最大ラウンド数（デフォルト _DEFAULT_MAX_ROUNDS、最小 _MIN_ROUNDS）
        on_message: 各発言ごとに呼ばれるコールバック（リアルタイム表示用）

    Raises:
        ValueError: max_rounds が _MIN_ROUNDS 未満の場合
        RuntimeError: 最大リトライ回数を超えてもエラーが解消されなかった場合。
            TimeoutError の場合はタイムアウト詳細、ConnectionError/OSError の場合は
            通信エラー詳細を含むメッセージが設定される。
    """
    if max_rounds < _MIN_ROUNDS:
        raise ValueError(
            f"max_rounds は {_MIN_ROUNDS} 以上の整数を指定してください"
        )

    timeout_seconds = _TURN_TIMEOUT_SECONDS * max_rounds
    last_exception: BaseException | None = None

    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            return await _execute_groupchat(
                topic=topic,
                max_rounds=max_rounds,
                timeout_seconds=timeout_seconds,
                on_message=on_message,
            )
        except _RETRYABLE_EXCEPTIONS as exc:
            last_exception = exc
            if attempt < _MAX_RETRIES:
                delay = _RETRY_BASE_DELAY_SECONDS * (2 ** (attempt - 1))
                logger.warning(
                    "GroupChat 実行中に一時的なエラーが発生しました "
                    "(試行 %d/%d, %.1f秒後にリトライ): [%s] %s",
                    attempt,
                    _MAX_RETRIES,
                    delay,
                    type(exc).__name__,
                    exc,
                )
                await asyncio.sleep(delay)
            else:
                logger.error(
                    "GroupChat の最大リトライ回数に到達しました "
                    "(試行 %d/%d): [%s] %s",
                    attempt,
                    _MAX_RETRIES,
                    type(exc).__name__,
                    exc,
                )

    # リトライ上限を超えた場合
    assert last_exception is not None
    if isinstance(last_exception, TimeoutError):
        raise RuntimeError(
            f"GroupChat がタイムアウトしました "
            f"（{_TURN_TIMEOUT_SECONDS}秒/ターン, 合計{timeout_seconds}秒, "
            f"{_MAX_RETRIES}回リトライ済み）: [{type(last_exception).__name__}] {last_exception}"
        ) from last_exception
    raise RuntimeError(
        f"GroupChat 実行中に通信エラーが発生しました "
        f"（{_MAX_RETRIES}回リトライ済み）: [{type(last_exception).__name__}] {last_exception}"
    ) from last_exception


async def _execute_groupchat(
    topic: str,
    max_rounds: int,
    timeout_seconds: float,
    on_message: OnAgentMessage | None,
) -> GroupChatResult:
    """GroupChat の単一実行を行う内部関数。

    リトライ対象の例外（TimeoutError, ConnectionError, OSError）はそのまま送出し、
    呼び出し元の ``run_groupchat`` でリトライ制御を行う。

    Args:
        topic: 討議テーマ（文字列）
        max_rounds: 最大ラウンド数
        timeout_seconds: 全体のタイムアウト秒数
        on_message: 各発言ごとに呼ばれるコールバック（リアルタイム表示用）

    Returns:
        GroupChatResult: GroupChat の実行結果

    Raises:
        TimeoutError: ストリーム消費がタイムアウトした場合（リトライ対象）
        ConnectionError: 通信エラーが発生した場合（リトライ対象）
        OSError: OS レベルの通信エラーが発生した場合（リトライ対象）
        RuntimeError: 上記以外のエラーが発生した場合（リトライ対象外）
    """
    # ファシリテーターの動的発言者選択で参照するメッセージ履歴（選択関数と共有する参照）
    shared_message_history: list[AgentMessage] = []

    facilitator = create_facilitator_agent()
    ceo = create_ceo_agent()
    analyst = create_analyst_agent()
    critic = create_critic_agent()

    workflow = (
        GroupChatBuilder(
            participants=[facilitator, ceo, analyst, critic],
            selection_func=_make_dynamic_selection(max_rounds, shared_message_history),
            max_rounds=max_rounds,
            intermediate_outputs=True,
        )
        .build()
    )

    start = time.perf_counter()
    agent_messages: list[AgentMessage] = []
    round_counter = 0

    try:
        stream = workflow.run(topic, stream=True)

        # エージェントごとにテキストトークンを蓄積するバッファ
        text_buffer: dict[str, list[str]] = {}

        async def _consume() -> None:
            nonlocal round_counter
            async for event in stream:
                if event.type == "output" and event.executor_id in _ALL_PARTICIPANTS:
                    # AgentResponseUpdate のテキストチャンクを蓄積
                    text = getattr(event.data, "text", "")
                    if text:
                        text_buffer.setdefault(event.executor_id, []).append(text)

                elif event.type == "group_chat" and isinstance(
                    event.data, GroupChatResponseReceivedEvent
                ):
                    # エージェントの発言完了 — 蓄積テキストからメッセージを構築
                    name = event.data.participant_name
                    if name not in _ALL_PARTICIPANTS:
                        continue
                    full_text = "".join(text_buffer.pop(name, []))
                    round_counter += 1
                    msg = AgentMessage(
                        agent_name=name,
                        content=full_text,
                        round_num=round_counter,
                    )
                    agent_messages.append(msg)
                    # 動的発言者選択で参照できるよう共有リストにも追加する
                    shared_message_history.append(msg)
                    if on_message:
                        on_message(msg)

        await asyncio.wait_for(_consume(), timeout=timeout_seconds)

        # フォールバック: ストリームイベントから取得できなかった場合は最終結果から抽出
        if not agent_messages:
            result = await stream.get_final_response()
            output_history: list | None = None
            for evt in result:
                if evt.type == "output" and isinstance(evt.data, list):
                    output_history = evt.data
            for msg_data in output_history or []:
                if msg_data.role != "assistant" or not msg_data.author_name:
                    continue
                if msg_data.author_name not in _ALL_PARTICIPANTS:
                    continue
                round_counter += 1
                am = AgentMessage(
                    agent_name=msg_data.author_name,
                    content=msg_data.text or "",
                    round_num=round_counter,
                )
                agent_messages.append(am)
                # 動的発言者選択で参照できるよう共有リストにも追加する
                shared_message_history.append(am)
                if on_message:
                    on_message(am)

    except _RETRYABLE_EXCEPTIONS:
        raise
    except Exception as exc:
        raise RuntimeError(
            f"GroupChat 実行中にエラーが発生しました: [{type(exc).__name__}] {exc}"
        ) from exc
    elapsed = time.perf_counter() - start

    # FacilitatorAgent の最終発言をサマリーとして使用（なければ最終メッセージ、それも無ければ空文字）
    facilitator_msgs = [m for m in agent_messages if m.agent_name == _FACILITATOR]
    if facilitator_msgs:
        summary = facilitator_msgs[-1].content
    elif agent_messages:
        summary = agent_messages[-1].content
    else:
        summary = ""

    return GroupChatResult(
        messages=agent_messages,
        total_rounds=round_counter,
        elapsed_seconds=round(elapsed, 2),
        summary=summary,
    )
