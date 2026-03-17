"""Foundry Agent Service にエージェントを事前登録するセットアップスクリプト。

使い方:
    python setup_agents.py create   -- 全エージェントを登録（既存なら新バージョン作成）
    python setup_agents.py list     -- 登録済みエージェント一覧を表示
    python setup_agents.py delete   -- 全エージェントを削除
"""

from __future__ import annotations

import argparse
import os
import sys

from dotenv import load_dotenv

load_dotenv()


def _get_project_client():
    """AIProjectClient を生成して返す。"""
    from azure.ai.projects import AIProjectClient
    from azure.identity import DefaultAzureCredential

    endpoint = os.getenv("FOUNDRY_PROJECT_ENDPOINT")
    if not endpoint:
        print("エラー: FOUNDRY_PROJECT_ENDPOINT が .env に設定されていません")
        sys.exit(1)
    return AIProjectClient(
        endpoint=endpoint,
        credential=DefaultAzureCredential(),
    )


def _get_deployment_name() -> str:
    """モデルデプロイメント名を取得する。"""
    deployment = os.getenv("AZURE_DEPLOYMENT_NAME")
    if not deployment:
        print("エラー: AZURE_DEPLOYMENT_NAME が .env に設定されていません")
        sys.exit(1)
    return deployment


def _get_agent_definitions() -> list[dict]:
    """登録対象のエージェント定義を返す。

    agent モジュールからインストラクション等を取得し、
    定義の一元管理を維持する。
    """
    from agents.analyst_agent import ANALYST_INSTRUCTIONS, ANALYST_NAME
    from agents.ceo_agent import CEO_INSTRUCTIONS, CEO_NAME
    from agents.critic_agent import CRITIC_INSTRUCTIONS, CRITIC_NAME
    from agents.facilitator_agent import FACILITATOR_INSTRUCTIONS, FACILITATOR_NAME

    return [
        {
            "name": FACILITATOR_NAME,
            "description": "討論の議長として討議の開始・進行・まとめを担うファシリテーター",
            "instructions": FACILITATOR_INSTRUCTIONS,
        },
        {
            "name": CEO_NAME,
            "description": "討議テーマの対象企業を代弁し、経営者の視点で主張する CEO",
            "instructions": CEO_INSTRUCTIONS,
        },
        {
            "name": ANALYST_NAME,
            "description": "企業経営・企業統治テーマを肯定的・建設的な視点から評価するアナリスト",
            "instructions": ANALYST_INSTRUCTIONS,
        },
        {
            "name": CRITIC_NAME,
            "description": "企業経営・企業統治テーマを批判的・懐疑的な視点から評価するクリティック",
            "instructions": CRITIC_INSTRUCTIONS,
        },
    ]


def cmd_create() -> None:
    """全エージェントを Foundry Agent Service に登録する。"""
    from azure.ai.projects.models import PromptAgentDefinition

    client = _get_project_client()
    deployment = _get_deployment_name()
    agent_defs = _get_agent_definitions()

    for agent_def in agent_defs:
        result = client.agents.create_version(
            agent_name=agent_def["name"],
            definition=PromptAgentDefinition(
                model=deployment,
                instructions=agent_def["instructions"],
            ),
            description=agent_def["description"],
        )
        print(
            f"✓ 登録完了: {agent_def['name']} "
            f"(version: {result.version}, model: {deployment})"
        )

    print("\nすべてのエージェントを登録しました。")


def cmd_list() -> None:
    """Foundry に登録済みのエージェント一覧を表示する。"""
    client = _get_project_client()
    agents = client.agents.list()

    found = False
    for agent in agents:
        found = True
        latest = getattr(agent.versions, "latest", None)
        version = latest.version if latest else "N/A"
        print(f"  {agent.name}  (latest version: {version})")

    if not found:
        print("  登録済みエージェントはありません。")


def cmd_delete() -> None:
    """全エージェントを Foundry から削除する。"""
    client = _get_project_client()
    agent_defs = _get_agent_definitions()

    for agent_def in agent_defs:
        name = agent_def["name"]
        try:
            client.agents.delete(agent_name=name)
            print(f"✓ 削除完了: {name}")
        except Exception as exc:
            print(f"✗ 削除失敗: {name} — {exc}")

    print("\n削除処理が完了しました。")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Foundry Agent Service エージェント管理スクリプト",
    )
    parser.add_argument(
        "command",
        choices=["create", "list", "delete"],
        help="実行するコマンド",
    )
    args = parser.parse_args()

    commands = {
        "create": cmd_create,
        "list": cmd_list,
        "delete": cmd_delete,
    }
    commands[args.command]()


if __name__ == "__main__":
    main()
