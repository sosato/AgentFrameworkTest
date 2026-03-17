"""CeoAgent — 討議テーマの対象企業を代弁するエージェント。"""

from __future__ import annotations

from agent_framework import Agent

from client import get_chat_client

CEO_NAME = "CeoAgent"

# setup_agents.py での初期登録に使用するデフォルトインストラクション。
# AzureAIClient は use_latest_version=True で Foundry 登録済みの定義を参照するため、
# ここの instructions はフォールバックとしてのみ使用される。
CEO_INSTRUCTIONS = """\
あなたは討議テーマの対象企業の CEO です。
与えられたテーマに対し、以下の原則で発言してください：
- 自社の ESG 取り組み実績・方針・目標を具体的に述べる
- アナリストやクリティックの指摘に対して、誠実かつ建設的に応答する
- 課題については認めつつ、改善への意欲と具体的な施策を示す
- 1 発言は 50〜500 字を目安にする
- 発言の冒頭に「【CEO】」と付ける

GroupChat での役割：
- 最初の発言で企業の ESG 基本方針と主要取り組みを表明する
- アナリスト・クリティックの指摘に対して追加情報と改善意向を示す
- 最後の発言で今後の改善コミットメントを明確に述べる

出力フォーマット：
【CEO】<発言内容>
"""


def create_ceo_agent() -> Agent:
    """専用 AzureAIClient を持つ CeoAgent を生成して返す。"""
    client = get_chat_client(agent_name=CEO_NAME)
    return Agent(
        client=client,
        instructions=CEO_INSTRUCTIONS,
        name=CEO_NAME,
        description="討議テーマの対象企業を代弁し、経営者の視点で主張する CEO",
    )
