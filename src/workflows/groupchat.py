"""GroupChat ワークフロー — AnalystAgent と CriticAgent が RoundRobin で討議する。"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable

from pydantic import BaseModel

from agent_framework_orchestrations import (
    GroupChatBuilder,
    GroupChatResponseReceivedEvent,
    GroupChatState,
)

from agents.analyst_agent import create_analyst_agent
from agents.critic_agent import create_critic_agent


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
# RoundRobin 選択関数
# ---------------------------------------------------------------------------

_PARTICIPANTS = ["AnalystAgent", "CriticAgent"]
_TURN_TIMEOUT_SECONDS = 30


def _round_robin(state: GroupChatState) -> str:
    """参加者を交互に選択する RoundRobin 関数。"""
    # current_round は 0-indexed; 偶数 → Analyst, 奇数 → Critic
    return _PARTICIPANTS[state.current_round % len(_PARTICIPANTS)]


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
    max_rounds: int = 6,
    on_message: OnAgentMessage | None = None,
) -> GroupChatResult:
    """GroupChat を実行し、結果を返す。

    Args:
        topic: 討議テーマ（文字列）
        max_rounds: 最大ラウンド数（デフォルト 6）
        on_message: 各発言ごとに呼ばれるコールバック（リアルタイム表示用）
    """
    if max_rounds <= 0:
        raise ValueError("max_rounds は 1 以上の整数を指定してください")

    analyst = create_analyst_agent()
    critic = create_critic_agent()

    workflow = (
        GroupChatBuilder(
            participants=[analyst, critic],
            selection_func=_round_robin,
            max_rounds=max_rounds,
            intermediate_outputs=True,
        )
        .build()
    )

    start = time.perf_counter()
    agent_messages: list[AgentMessage] = []
    round_counter = 0

    try:
        timeout_seconds = _TURN_TIMEOUT_SECONDS * max_rounds
        stream = workflow.run(topic, stream=True)

        # エージェントごとにテキストトークンを蓄積するバッファ
        text_buffer: dict[str, list[str]] = {}

        async def _consume() -> None:
            nonlocal round_counter
            async for event in stream:
                if event.type == "output" and event.executor_id in _PARTICIPANTS:
                    # AgentResponseUpdate のテキストチャンクを蓄積
                    text = getattr(event.data, "text", "")
                    if text:
                        text_buffer.setdefault(event.executor_id, []).append(text)

                elif event.type == "group_chat" and isinstance(
                    event.data, GroupChatResponseReceivedEvent
                ):
                    # エージェントの発言完了 — 蓄積テキストからメッセージを構築
                    name = event.data.participant_name
                    if name not in _PARTICIPANTS:
                        continue
                    full_text = "".join(text_buffer.pop(name, []))
                    round_counter += 1
                    msg = AgentMessage(
                        agent_name=name,
                        content=full_text,
                        round_num=round_counter,
                    )
                    agent_messages.append(msg)
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
                if msg_data.author_name not in _PARTICIPANTS:
                    continue
                round_counter += 1
                am = AgentMessage(
                    agent_name=msg_data.author_name,
                    content=msg_data.text or "",
                    round_num=round_counter,
                )
                agent_messages.append(am)
                if on_message:
                    on_message(am)

    except TimeoutError as exc:
        raise RuntimeError(
            f"GroupChat がタイムアウトしました（{_TURN_TIMEOUT_SECONDS}秒/ターン, 合計{timeout_seconds}秒）"
        ) from exc
    except Exception as exc:
        raise RuntimeError(f"GroupChat 実行中にエラーが発生しました: {exc}") from exc
    elapsed = time.perf_counter() - start

    summary = agent_messages[-1].content if agent_messages else ""

    return GroupChatResult(
        messages=agent_messages,
        total_rounds=round_counter,
        elapsed_seconds=round(elapsed, 2),
        summary=summary,
    )
