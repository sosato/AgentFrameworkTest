"""ESG GroupChat PoC — CLI エントリーポイント。"""

from __future__ import annotations

import argparse
import asyncio
import logging
import re
import sys

# AzureAIClient の "does not support runtime tools" 警告を抑制
# （use_latest_version=True で既存エージェントを参照する際に発生するが動作に影響なし）
logging.getLogger("agent_framework.azure").setLevel(logging.ERROR)
# "Unclosed client session" の asyncio ログを抑制
logging.getLogger("asyncio").setLevel(logging.CRITICAL)

from workflows.groupchat import AgentMessage, GroupChatResult, run_groupchat

DEFAULT_TOPIC = "トヨタ自動車の ESG 評価：環境への取り組みは十分か？"

# ANSI カラーコード
_BLUE = "\033[94m"
_YELLOW = "\033[93m"
_CYAN = "\033[96m"
_GREEN = "\033[92m"
_MAGENTA = "\033[95m"
_RESET = "\033[0m"

_AGENT_COLORS: dict[str, str] = {
    "FacilitatorAgent": _CYAN,
    "CeoAgent": _GREEN,
    "AnalystAgent": _BLUE,
    "CriticAgent": _YELLOW,
}

_SCORE_RE = re.compile(r"(\d{1,2})\s*/\s*10")


def _use_color() -> bool:
    """ANSI カラーが使えるかどうかを判定する。"""
    return sys.stdout.isatty()


def _colorize(text: str, color: str) -> str:
    """色付き文字列を返す。ANSI 非対応ならプレーンテキスト。"""
    if not _use_color():
        return text
    return f"{color}{text}{_RESET}"


def _extract_score(content: str) -> str:
    """発言からスコア（X/10）を抽出する。見つからなければ 'N/A'。"""
    m = _SCORE_RE.search(content)
    return f"{m.group(1)}/10" if m else "N/A"


def _extract_first_last_scores(
    messages: list[AgentMessage], agent_name: str
) -> tuple[str, str]:
    """指定エージェントの初回・最終発言からスコアを抽出する。"""
    agent_msgs = [m for m in messages if m.agent_name == agent_name]
    first = _extract_score(agent_msgs[0].content) if agent_msgs else "N/A"
    last = _extract_score(agent_msgs[-1].content) if agent_msgs else "N/A"
    return first, last


def _print_agent_message(msg: AgentMessage) -> None:
    """コールバック: エージェントの発言をリアルタイム表示する。"""
    color = _AGENT_COLORS.get(msg.agent_name, "")
    header = _colorize(f"[Round {msg.round_num}] {msg.agent_name}", color)
    body = _colorize(f"  {msg.content}", color)
    print(f"\n{header}")
    print(body)
    print("-" * 60)
    sys.stdout.flush()


def display_summary(result: GroupChatResult) -> None:
    """GroupChat 完了後のサマリー（スコア比較・最終結論）を表示する。"""
    print("\n" + "=" * 60)
    print(" ESG GroupChat PoC — 討議完了")
    print("=" * 60)
    print(f"総ラウンド数 : {result.total_rounds}")
    print(f"所要時間     : {result.elapsed_seconds} 秒")
    print("-" * 60)

    # スコア比較表示（アナリストとクリティックのみ）
    print(f"\n{_colorize('スコア比較', _MAGENTA)}")
    for name in ("AnalystAgent", "CriticAgent"):
        first, last = _extract_first_last_scores(result.messages, name)
        color = _AGENT_COLORS.get(name, "")
        label = _colorize(name, color)
        print(f"  {label}: 初期 {first} → 最終 {last}")

    print(f"\n【最終結論】\n  {result.summary}")
    print("=" * 60 + "\n")


async def main(topic: str, max_rounds: int) -> None:
    """GroupChat を実行して結果を表示する。"""
    print(f"テーマ: {topic}")
    print(f"最大ラウンド数: {max_rounds}")
    print("討議を開始します...\n")

    result = await run_groupchat(
        topic=topic,
        max_rounds=max_rounds,
        on_message=_print_agent_message,
    )
    display_summary(result)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    def _positive_int(value: str) -> int:
        ivalue = int(value)
        if ivalue <= 0:
            raise argparse.ArgumentTypeError("1 以上の整数を指定してください")
        return ivalue

    parser = argparse.ArgumentParser(description="ESG GroupChat PoC")
    parser.add_argument(
        "--topic",
        type=str,
        default=DEFAULT_TOPIC,
        help="討議テーマ（省略時はデフォルトテーマを使用）",
    )
    parser.add_argument(
        "--rounds",
        type=_positive_int,
        default=9,
        help="最大ラウンド数（省略時 9）",
    )
    return parser.parse_args(argv)


if __name__ == "__main__":
    args = parse_args()
    try:
        asyncio.run(main(topic=args.topic, max_rounds=args.rounds))
    except Exception as exc:
        print(f"エラー: {exc}")
        raise SystemExit(1) from exc
