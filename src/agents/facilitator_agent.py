"""FacilitatorAgent — 討論を司る議長エージェント。"""

from __future__ import annotations

from agent_framework import Agent

from client import get_chat_client

FACILITATOR_NAME = "FacilitatorAgent"

# setup_agents.py での初期登録に使用するデフォルトインストラクション。
# AzureAIClient は use_latest_version=True で Foundry 登録済みの定義を参照するため、
# ここの instructions はフォールバックとしてのみ使用される。
FACILITATOR_INSTRUCTIONS = """\
あなたは ESG 討論会の議長（ファシリテーター）です。
与えられたテーマに対し、以下の原則で発言してください：
- 討議の開始時はテーマと参加者（CEO・アナリスト・クリティック）を紹介する
- 討議の終了時は各参加者の主要主張を中立的に整理し、共通見解と残課題を提示する
- 自身の意見や評価は述べず、中立・客観的な立場を保つ
- 1 発言は 200 字以内に収める
- 発言の冒頭に「【ファシリテーター】」と付ける

GroupChat での役割：
- Round 1（討議開始）：テーマを宣言し、参加者の役割を紹介、討議の進め方を説明する
- Round 9（討議終了）：各エージェントの主張を要約し、結論と残課題を提示する

出力フォーマット：
【ファシリテーター】<発言内容>
"""


def create_facilitator_agent() -> Agent:
    """専用 AzureAIClient を持つ FacilitatorAgent を生成して返す。"""
    client = get_chat_client(agent_name=FACILITATOR_NAME)
    return Agent(
        client=client,
        instructions=FACILITATOR_INSTRUCTIONS,
        name=FACILITATOR_NAME,
        description="討論の議長として討議の開始・進行・まとめを担うファシリテーター",
    )
