"""CriticAgent — 企業経営・企業統治テーマを批判的・懐疑的に評価するエージェント。"""

from __future__ import annotations

from agent_framework import Agent

from client import get_chat_client

CRITIC_NAME = "CriticAgent"

# setup_agents.py での初期登録に使用するデフォルトインストラクション。
# AzureAIClient は use_latest_version=True で Foundry 登録済みの定義を参照するため、
# ここの instructions はフォールバックとしてのみ使用される。
CRITIC_INSTRUCTIONS = """\
あなたは企業経営・コーポレートガバナンス評価において批判的合理主義の立場をとるリサーチャーです。
与えられたテーマに対し、以下の原則で発言してください：
- アナリストの主張に対し、反証・データの欠如・論理の飛躍を指摘する
- 感情的批判ではなく、論理的・定量的な懐疑を示す
- 1 発言は 50〜500 字を目安にする
- 発言の冒頭に「【クリティック】」と付ける

GroupChat での役割：
- アナリストの初期評価に対してカウンター評価スコアを提示する
- 具体的な反論・追加調査が必要な点を列挙する
- 4 ラウンド以降は改善提案を含む建設的収束メッセージに移行する

出力フォーマット：
【クリティック】<発言内容>（初回：反論評価スコア X/10 を含む）
"""


def create_critic_agent() -> Agent:
    """専用 AzureAIClient を持つ CriticAgent を生成して返す。"""
    client = get_chat_client(agent_name=CRITIC_NAME)
    return Agent(
        client=client,
        instructions=CRITIC_INSTRUCTIONS,
        name=CRITIC_NAME,
        description="企業経営・企業統治テーマを批判的・懐疑的な視点から評価するクリティック",
    )
