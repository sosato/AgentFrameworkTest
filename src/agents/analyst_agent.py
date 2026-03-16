"""AnalystAgent — ESG テーマを肯定的・建設的に評価するエージェント。"""

from __future__ import annotations

from agent_framework import Agent

from client import get_chat_client

ANALYST_NAME = "AnalystAgent"

# setup_agents.py での初期登録に使用するデフォルトインストラクション。
# AzureAIClient は use_latest_version=True で Foundry 登録済みの定義を参照するため、
# ここの instructions はフォールバックとしてのみ使用される。
ANALYST_INSTRUCTIONS = """\
あなたは ESG 投資調査の専門アナリストです。
与えられたテーマに対し、以下の原則で発言してください：
- 具体的な数値・事実・業界比較を根拠として示す（知識範囲内で）
- 建設的・肯定的な評価視点を優先しつつ、課題も正直に述べる
- 1 発言は 150 字以内に収める
- 発言の冒頭に「【アナリスト】」と付ける

GroupChat での役割：
- 最初にテーマの概要と自分の初期評価スコア（10点満点）を提示する
- CriticAgent の反論に対して根拠を示しながら応答する
- 4 ラウンド以降は議論を収束させる要約的発言を心がける

出力フォーマット：
【アナリスト】<発言内容>（初回：初期評価スコア X/10 を含む）
"""


def create_analyst_agent() -> Agent:
    """専用 AzureAIClient を持つ AnalystAgent を生成して返す。"""
    client = get_chat_client(agent_name=ANALYST_NAME)
    return Agent(
        client=client,
        instructions=ANALYST_INSTRUCTIONS,
        name=ANALYST_NAME,
        description="ESG テーマを肯定的・建設的な視点から評価するアナリスト",
    )
