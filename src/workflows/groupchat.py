"""GroupChat ワークフロー — FacilitatorAgent が議長を務め、CeoAgent / AnalystAgent /
CriticAgent の 3 エージェントが討議する。"""

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
# ファシリテーター制御の選択関数
# ---------------------------------------------------------------------------

_FACILITATOR = "FacilitatorAgent"
_DEBATERS = ["CeoAgent", "AnalystAgent", "CriticAgent"]
_ALL_PARTICIPANTS = [_FACILITATOR] + _DEBATERS
_TURN_TIMEOUT_SECONDS = 30


def _make_facilitator_selection(max_rounds: int) -> Callable[[GroupChatState], str]:
    """ファシリテーターが開閉を担い、討論者が循環発言する選択関数を生成する。

    - Round 0（1 ターン目）: FacilitatorAgent（討議開始・テーマ紹介）
    - Rounds 1〜max_rounds-2: CeoAgent → AnalystAgent → CriticAgent の順で循環
    - Round max_rounds-1（最終ターン）: FacilitatorAgent（討議終了・サマリー）
    """
    def _select(state: GroupChatState) -> str:
        round_idx = state.current_round
        if round_idx == 0 or round_idx == max_rounds - 1:
            return _FACILITATOR
        debater_idx = (round_idx - 1) % len(_DEBATERS)
        return _DEBATERS[debater_idx]

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
    max_rounds: int = 9,
    on_message: OnAgentMessage | None = None,
) -> GroupChatResult:
    """GroupChat を実行し、結果を返す。

    Args:
        topic: 討議テーマ（文字列）
        max_rounds: 最大ラウンド数（デフォルト 9）
        on_message: 各発言ごとに呼ばれるコールバック（リアルタイム表示用）
    """
    if max_rounds <= 0:
        raise ValueError("max_rounds は 1 以上の整数を指定してください")

    facilitator = create_facilitator_agent()
    ceo = create_ceo_agent()
    analyst = create_analyst_agent()
    critic = create_critic_agent()

    workflow = (
        GroupChatBuilder(
            participants=[facilitator, ceo, analyst, critic],
            selection_func=_make_facilitator_selection(max_rounds),
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
                if on_message:
                    on_message(am)

    except TimeoutError as exc:
        raise RuntimeError(
            f"GroupChat がタイムアウトしました（{_TURN_TIMEOUT_SECONDS}秒/ターン, 合計{timeout_seconds}秒）"
        ) from exc
    except Exception as exc:
        raise RuntimeError(f"GroupChat 実行中にエラーが発生しました: {exc}") from exc
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
